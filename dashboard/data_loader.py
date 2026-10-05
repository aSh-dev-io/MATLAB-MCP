"""Loading of the existing Stage 1 / Stage 2 artefacts for the dashboard.

This module performs no analysis of its own. Every value it returns is either
read straight out of an existing JSON artefact or is a display-level aggregation
(percentiles, counts) over an existing, unmodified output CSV. Nothing here
recomputes a physics result, and no value is invented: where the upstream
artefact records a quantity as unavailable, the loader returns ``None`` and the
UI renders ``N/A``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

# ``dashboard/data_loader.py`` -> project root is two parents up.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGE1_DIR = PROJECT_ROOT / "results"
STAGE2_OUTPUT = PROJECT_ROOT / "stage2" / "output"

#: The Phase 2B report is emitted under this name by the existing pipeline.
PHASE2B_REPORT = "stress_analysis_report.md"

#: Numeric trace channels offered in the interactive time-series view.
TRACE_CHANNELS: dict[str, str] = {
    "VGS": "vgs_V",
    "VDS": "vds_V",
    "ID": "id_A",
    "RON": "ron_stage1_ohm",
    "Tj": "tj_C",
    "Tcase": "tcase_C",
    "Pcond": "pcond_W",
    "Psw": "psw_W",
    "Ploss": "ploss_W",
}

#: Units for each trace channel, so the axis is labelled rather than guessed.
TRACE_UNITS: dict[str, str] = {
    "VGS": "V",
    "VDS": "V",
    "ID": "A",
    "RON": "ohm",
    "Tj": "degC",
    "Tcase": "degC",
    "Pcond": "W",
    "Psw": "W",
    "Ploss": "W",
}

UTILISATION_LABELS: dict[str, str] = {
    "vds_rating_utilisation": "VDS vs absolute maximum",
    "id_continuous_rating_utilisation": "ID vs continuous rating",
    "id_pulse_rating_utilisation": "ID vs pulse rating",
    "vgs_gate_window_utilisation": "VGS vs gate window",
    "junction_rating_utilisation": "Tj vs maximum",
}


class MissingArtefact(RuntimeError):
    """Raised when a required upstream artefact is absent."""


def _require(path: Path) -> Path:
    if not path.exists():
        raise MissingArtefact(
            f"Required input not found: {path}\n"
            "Generate it first with:  python -m ganstage2.run  (from the stage2 folder)"
        )
    return path


@lru_cache(maxsize=None)
def _load_json(path_str: str) -> dict[str, Any]:
    with open(path_str, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_manifest() -> dict[str, Any]:
    """Phase 2A manifest: device identity, provenance and quality counts."""
    return _load_json(str(_require(STAGE2_OUTPUT / "stage2_manifest.json")))


def load_stress() -> dict[str, Any]:
    """Phase 2B stress analysis: RON, switching, thermal, capacitance, coverage."""
    return _load_json(str(_require(STAGE2_OUTPUT / "stress_analysis.json")))


def load_indicators() -> dict[str, Any]:
    """Phase 2C exposure indicators, including the explicitly blocked ones."""
    return _load_json(str(_require(STAGE2_OUTPUT / "exposure_indicators.json")))


def load_stage1_summary() -> dict[str, Any]:
    """Stage 1 summary, when present. Never required: Stage 2 is authoritative."""
    path = STAGE1_DIR / "stage1_summary.json"
    if not path.exists():
        return {}
    return _load_json(str(path))


@lru_cache(maxsize=1)
def load_stress_dataset() -> pd.DataFrame:
    """The existing Phase 2B stress dataset, read verbatim.

    Only columns already present in the file are used. No column is added,
    renamed or recomputed.
    """
    path = _require(STAGE2_OUTPUT / "stress_dataset.csv")
    frame = pd.read_csv(path, low_memory=False)

    # Boolean columns arrive as 0/1 from the CSV writer; restore real booleans so
    # downstream filtering does not silently treat 1 as "truthy string".
    for column in ("ron_valid", "is_conducting", "is_rating_exceeded"):
        if column in frame.columns:
            frame[column] = frame[column].astype(bool)
    return frame


# ---------------------------------------------------------------------------
# Display-level aggregations over the existing dataset
# ---------------------------------------------------------------------------

def ron_samples() -> pd.DataFrame:
    """RON-valid conduction samples only, as flagged by the existing Phase 2 run."""
    frame = load_stress_dataset()
    return frame[frame["ron_valid"]].copy()


def ron_statistics() -> dict[str, float]:
    """Percentile spread of RON over the RON-valid samples.

    Purely a display aggregation of the existing ``ron_stage1_ohm`` column over
    rows the existing pipeline already marked ``ron_valid``. No validity rule is
    re-implemented here.
    """
    values = ron_samples()["ron_stage1_ohm"].to_numpy(dtype=float)
    if values.size == 0:
        return {}
    return {
        "samples": int(values.size),
        "min_ohm": float(values.min()),
        "median_ohm": float(pd.Series(values).median()),
        "p95_ohm": float(pd.Series(values).quantile(0.95)),
        "p99_ohm": float(pd.Series(values).quantile(0.99)),
        "max_ohm": float(values.max()),
    }


def current_parameters() -> dict[str, dict[str, Any]]:
    """Latest operating point per trace channel, with its evidence.

    Returns ``None`` for any channel that carries no usable numeric value at the
    selected operating point, so the UI can print N/A rather than substitute a
    default.
    """
    frame = load_stress_dataset()
    evidence = frame.iloc[-1]
    out: dict[str, dict[str, Any]] = {}
    for label, column in TRACE_CHANNELS.items():
        series = frame[column]
        finite = series[series.notna() & pd.Series(series).map(lambda v: v == v)]
        if finite.empty:
            out[label] = {"value": None, "unit": TRACE_UNITS[label], "column": column}
            continue
        out[label] = {
            "value": float(finite.iloc[-1]),
            "unit": TRACE_UNITS[label],
            "column": column,
        }
    out["_evidence_class"] = {
        "value": str(evidence.get("evidence_class", "")),
        "unit": "",
        "column": "evidence_class",
    }
    return out


def utilisation_maxima() -> dict[str, dict[str, Any]]:
    """Worst-case rating utilisation per channel, read from the dataset columns."""
    frame = load_stress_dataset()
    out: dict[str, dict[str, Any]] = {}
    for column, label in UTILISATION_LABELS.items():
        if column not in frame.columns:
            out[column] = {"label": label, "value": None}
            continue
        series = frame[column]
        out[column] = {
            "label": label,
            "value": float(series.max()) if series.notna().any() else None,
        }
    return out


def data_quality() -> dict[str, Any]:
    """Sample counts and validation status from the existing artefacts."""
    frame = load_stress_dataset()
    stress = load_stress()
    coverage = stress["coverage"]
    total = int(coverage["total_samples"])
    ron_valid = int(stress["on_resistance"]["valid_samples"])
    manifest = load_manifest()
    evidence = manifest["evidence"]
    return {
        "total_samples": total,
        "rows_in_dataset": int(len(frame)),
        "ron_valid_samples": ron_valid,
        "ron_valid_pct": 100.0 * ron_valid / total if total else None,
        "outside_envelope_pct": 100.0 * float(coverage["outside_rated_envelope_share"]),
        "outside_envelope_count": int(coverage["outside_rated_envelope_total"]),
        "trajectory_count": int(stress["trajectory_count"]),
        "experimental_validation": "NOT AVAILABLE",
        "has_experimental_validation": bool(evidence["has_experimental_validation"]),
        "model_prediction_label": evidence["model_prediction_label"],
        "evidence_class": evidence["evidence_class"],
        "is_aging_measurement": bool(evidence["is_aging_measurement"]),
    }


def device_cards() -> dict[str, Any]:
    """Device identity and model/validation status from the Phase 2A manifest."""
    manifest = load_manifest()
    device = manifest["device"]
    evidence = manifest["evidence"]
    return {
        "manufacturer": device["manufacturer"],
        "part_number": device["part_number"],
        "technology": device["technology"],
        "package": device["package"],
        "datasheet_revision": device["datasheet_revision"],
        "model_status": "MODEL PREDICTION - NOT VALIDATED",
        "validation_status": "NOT AVAILABLE",
        "model_file": device["model_file"],
        "generated_utc": device["generated_utc"],
        "matlab_release": device["matlab_release"],
        "evidence_class": evidence["evidence_class"],
        "has_experimental_validation": evidence["has_experimental_validation"],
        "thermal_note": evidence["thermal_note"],
    }


def profile_frame(profile: str) -> pd.DataFrame:
    """Rows for one measurement profile, as stored in the existing dataset."""
    return load_stress_dataset()[lambda d: d["profile"] == profile]


def trajectory_options() -> list[tuple[str, str, int]]:
    """Selectable (profile, operating_point_key, samples) triples for the trace view."""
    frame = load_stress_dataset()
    grouped = (
        frame.groupby(["profile", "operating_point_key"], sort=True)
        .size()
        .reset_index(name="samples")
    )
    return [
        (str(row.profile), str(row.operating_point_key), int(row.samples))
        for row in grouped.itertuples()
    ]


def read_report(name: str) -> str:
    """Read a generated Markdown report, returning a short message if absent."""
    path = STAGE2_OUTPUT / name
    if not path.exists():
        return f"_Report not found: {name}. Run `python -m ganstage2.run` to generate it._"
    return path.read_text(encoding="utf-8")
