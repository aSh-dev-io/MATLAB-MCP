"""MAT v7.3 reader tests.

The logical-decoding test here pins a bug that was silently wrong: MATLAB stores
a ``logical`` as a ``uint8`` tagged ``MATLAB_class = 'logical'``, so decoding by
dtype alone turned ``true`` into the one-character string ``"\\x01"``. Every
``isinstance(value, bool)`` test then failed, and check Q13 reported "Stage 1
recorded 0 dataset defects" for a file that records four.
"""

from __future__ import annotations

import h5py
import numpy as np

from ganstage2.matv73 import (
    as_series,
    decode_text,
    decode_value,
    flatten_group,
    is_logical,
    is_v73,
    nested_section,
)


def test_is_v73_accepts_real_file_and_rejects_text(cfg):
    assert is_v73(str(cfg.mat_path))
    assert not is_v73(str(cfg.json_path))


def test_decode_text_reads_matlab_char_rows(cfg):
    with h5py.File(cfg.mat_path, "r") as fh:
        assert decode_text(fh["meta/part_number"]) == "NTLEF2D2N15GN1"


def test_matlab_logical_decodes_to_bool_not_text(cfg):
    """The regression this module exists to prevent."""
    with h5py.File(cfg.mat_path, "r") as fh:
        flag = fh["report/dataset_defects/curves_absent"]
        assert is_logical(flag), "the stored node should be tagged as a MATLAB logical"

        value = decode_value(flag, fh)
        assert value is True
        assert not isinstance(value, str), "a logical must never decode as text"

        assert decode_value(fh["report/dataset_defects/thermal_absent"], fh) is True
        assert decode_value(fh["report/dataset_defects/qg_not_sum_of_parts"], fh) is True
        assert decode_value(fh["report/dataset_defects/qgd_test_condition"], fh) is True

        # And a logical false must not read as a non-empty truthy string either.
        assert decode_value(fh["p/charge/qg_is_consistent"], fh) is False


def test_plain_uint8_is_not_mistaken_for_a_logical(cfg):
    """dtype alone is ambiguous, so the MAT class tag has to be what decides."""
    with h5py.File(cfg.mat_path, "r") as fh:
        char_row = fh["meta/part_number"]
        assert char_row.dtype == np.uint16
        assert not is_logical(char_row)


def test_empty_char_cell_decodes_to_empty_string(cfg):
    """An empty MATLAB char is a null placeholder, not two NUL characters."""
    with h5py.File(cfg.mat_path, "r") as fh:
        units = fh["report/checks/condition_units"]
        decoded = decode_value(units, fh)
        assert decoded, "expected a list of one entry per check row"
        assert decoded[0] == "", "an empty unit cell should decode to ''"
        assert all(u == "" or isinstance(u, str) for u in decoded)


def test_float_nan_survives_decoding(cfg):
    """NaN marks an unverifiable quantity and must not become a number."""
    with h5py.File(cfg.mat_path, "r") as fh:
        model = decode_value(fh["report/checks/model"], fh)
        assert any(isinstance(v, float) and np.isnan(v) for v in model)


def test_as_series_ravels_transposed_row(cfg):
    """MATLAB 1xN lands in HDF5 as (1, N); len() would report 1."""
    with h5py.File(cfg.mat_path, "r") as fh:
        group = fh["data/output"]
        raw = group["time"]
        assert len(raw.shape) == 2 and raw.shape[0] == 1
        series = as_series(raw)
        assert series.ndim == 1
        assert series.size == raw.shape[1]
        # The sample count is the one the loader uses, not the row count.
        assert series.size == as_series(group["ID"]).size


def test_nested_section_is_the_inverse_of_flattening():
    flat = {
        "dataset_defects.curves_absent": True,
        "dataset_defects.qg_detail": "detail",
        "summary.pass": 12.0,
    }
    section = nested_section(flat, "dataset_defects")
    assert section == {"curves_absent": True, "qg_detail": "detail"}
    assert "summary.pass" not in section


def test_nested_section_rebuilds_deeper_subtrees():
    flat = {"defects.group.inner.flag": True, "defects.group.other": 1.0}
    section = nested_section(flat, "defects")
    assert section == {"group": {"inner": {"flag": True}, "other": 1.0}}


def test_nested_section_returns_empty_when_section_absent():
    """Guards the failure mode this helper exists to prevent."""
    assert nested_section({"unrelated.key": 1}, "dataset_defects") == {}
    assert nested_section({}, "dataset_defects") == {}


def test_flatten_group_produces_dotted_keys(cfg):
    with h5py.File(cfg.mat_path, "r") as fh:
        flat = flatten_group(fh["report"]["dataset_defects"])
    assert "curves_absent" in flat
    assert all("." not in key for key in flat)
