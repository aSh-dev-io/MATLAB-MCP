"""Ingestion tests.

The most important test in Phase 2A lives here: it pins down that the Stage 1
CSV really is defective and that the repair is exact. If Stage 1 ever fixes the
trailing comma, ``test_csv_defect_is_detected`` will start failing, which is the
correct signal to retire the workaround rather than leave it silently in place.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ganstage2.config import Stage2Config
from ganstage2.matv73 import is_v73


def test_mat_is_v73(cfg: Stage2Config):
    assert is_v73(str(cfg.mat_path))


def test_ingests_all_profiles(bundle, cfg: Stage2Config):
    assert set(bundle.frame["profile"].unique()) == set(cfg.profile_roles)
    assert len(bundle.frame) == 15904


def test_profile_row_counts_match_stage1_summary(bundle):
    declared = {p["name"]: p["samples"] for p in bundle.summary_json["profiles"]}
    actual = bundle.frame.groupby("profile").size().to_dict()
    assert actual == declared


def test_schema_columns_present(bundle, cfg: Stage2Config):
    for column, _ in cfg.schema:
        assert column in bundle.frame.columns


def test_profile_column_is_categorical(bundle):
    """A naive read turns profile into floats; the loader must not."""
    assert bundle.frame["profile"].dtype == object or str(bundle.frame["profile"].dtype).startswith("string")
    sample = bundle.frame["profile"].iloc[0]
    assert isinstance(sample, str)
    assert sample in ("output", "transfer", "capacitance", "charge", "switching", "thermal")


def test_csv_defect_is_detected(bundle):
    parse = bundle.csv_parse
    assert parse is not None
    assert parse.is_defective, "Stage 1 CSV was expected to carry the trailing-delimiter defect"
    assert parse.header_field_count == 18
    assert parse.rows_repaired_trailing_delimiter == parse.rows_read
    assert parse.rows_dropped_malformed == 0


def test_naive_pandas_read_is_known_to_be_wrong(cfg: Stage2Config):
    """Documents *why* the defensive reader exists.

    If this test ever fails, Stage 1 fixed the CSV and the workaround can be
    retired.
    """
    naive = pd.read_csv(cfg.csv_path)
    assert list(naive.columns)[-1] == "Crss_F"
    assert naive["Crss_F"].isna().all(), "naive read should lose Crss entirely"
    assert set(naive.index.astype(str)) == {
        "output",
        "transfer",
        "capacitance",
        "charge",
        "switching",
        "thermal",
    }, "naive read should promote field 0 to the index"
    # And the signals are shifted one column left, so the column labelled
    # t_s actually holds Vgs and cannot start at zero.
    assert float(naive["t_s"].iloc[0]) != 0.0


def test_csv_header_is_renamed_to_canonical_schema(bundle, cfg: Stage2Config):
    """The CSV keeps MATLAB identifiers; ingestion must map them."""
    assert bundle.csv_frame is not None
    for column, _ in cfg.schema:
        assert column in bundle.csv_frame.columns, f"CSV column {column} was not mapped"
    # And the MATLAB names must be gone, otherwise a later consumer would read
    # a stale, differently-typed duplicate.
    for matlab_name in ("Vgs_V", "ID_A", "RON_ohm", "Crss_F"):
        assert matlab_name not in bundle.csv_frame.columns


def test_repaired_csv_matches_mat_within_csv_text_precision(bundle, cfg: Stage2Config):
    csv_df = bundle.csv_frame
    mat = bundle.frame
    assert csv_df is not None
    assert len(csv_df) == len(mat)
    # Align on (profile, sample ordinal): the MAT is read in alphabetical
    # profile order, the CSV in Stage 1 run order, and MATLAB's CSV writer
    # truncates t_s precision, so neither row position nor raw time is a
    # reliable join key.
    left = csv_df.assign(_k=csv_df.groupby("profile").cumcount()).set_index(["profile", "_k"]).sort_index()
    right = mat.assign(_k=mat.groupby("profile").cumcount()).set_index(["profile", "_k"]).sort_index()
    assert left.index.equals(right.index)
    # MATLAB writes CSV text at ~10 significant digits, so agreement is bounded
    # by the text format rather than exact.
    for column in [c for c, u in cfg.schema if u != "categorical"]:
        np.testing.assert_allclose(
            left[column].to_numpy(float),
            right[column].to_numpy(float),
            rtol=cfg.csv_mat_rtol.value,
            atol=0.0,
            equal_nan=True,
        )


def test_crss_present_in_ingested_frame(bundle):
    """The signal a naive CSV read destroys must survive ingestion."""
    crss = bundle.frame["crss_F"].to_numpy(float)
    assert not np.isnan(crss).any()
    assert crss.max() > 0.0


def test_only_ron_has_missing_values(bundle):
    for column, unit in Stage2Config().schema:
        if unit == "categorical":
            continue
        missing = int(bundle.frame[column].isna().sum())
        if column == "ron_stage1_ohm":
            assert missing > 0, "RON should be NaN where Stage 1 masks it"
        else:
            assert missing == 0, f"{column} unexpectedly has {missing} missing values"


def test_device_identity(bundle):
    assert bundle.mat_meta["part_number"] == "NTLEF2D2N15GN1"
    assert "NOT VALIDATED" in str(bundle.mat_meta["model_prediction_label"])
