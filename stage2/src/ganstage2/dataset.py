"""Assemble the Phase 2B-ready dataset.

The output is a single tidy frame, one row per Stage 1 sample, carrying three
things the raw export does not:

1. **Conditioning context.** Every row states the bias and temperature at which
   it was produced, plus an ``operating_point_key`` that groups samples taken at
   nominally identical conditions. This is what lets Phase 2B compare like with
   like instead of correlating across a whole sweep.
2. **Interpretability flags.** ``ron_valid`` and its reason, the operating
   regime, and whether the sample is a characterisation measurement or a
   plausible application operating point.
3. **Explicit provenance.** ``evidence_class``, ``has_experimental_validation``
   and ``is_aging_measurement`` on every row, so no downstream consumer can
   mistake a simulation sweep for a measurement or for aging data.

Deliberately absent: any degradation coefficient, health score, health state,
remaining-useful-life figure or predictive-accuracy estimate. The source data
supports none of them, and Phase 2A is not the phase that would add them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import Stage2Config
from .ingestion import Stage1Bundle
from .matv73 import nested_section
from .physics import PhysicsCheck, add_physics_columns, estimate_differential_ron, run_physics_checks
from .provenance import build_provenance_record
from .quality import QualityReport, run_quality_checks

#: Columns appended by Stage 2, in order, with the unit or meaning of each.
DERIVED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("sample_index", "index within profile"),
    ("operating_point_key", "vgs|vds|tcase snapped to the configured rounding"),
    ("i_leak_A", "A; Stage 1 leakage equation"),
    ("conduction_threshold_A", "A; conduction_leakage_multiple x i_leak_A"),
    ("is_conducting", "bool; |ID| >= conduction threshold"),
    ("is_positive_vds", "bool"),
    ("is_triode", "bool; VDS <= VDSAT(VGS)"),
    ("vdsat_vgs_V", "V; Stage 1 knee voltage at this VGS"),
    ("operating_regime", "zero_bias | off_or_leakage | triode_ohmic | saturation_or_cvdrive"),
    ("ron_static_ohm", "Ohm; VDS/ID, NaN unless ron_valid"),
    ("ron_valid", "bool; conducting AND triode AND VDS>0"),
    ("ron_valid_reason", "why ron_valid is False"),
    ("ron_differential_ohm", "Ohm; dVDS/dID from the DC sweep, NaN if unavailable"),
    ("ron_differential_available", "bool"),
    ("ron_temp_normalised_ohm", "always NaN in Phase 2A"),
    ("ron_tempnorm_status", "reason temperature normalisation is unavailable"),
    ("profile_role", "what the profile is for"),
    ("is_characterisation_sweep", "bool"),
    ("is_application_operating_point", "bool"),
    ("vds_rating_utilisation", "ratio; |VDS| / 150 V"),
    ("vgs_rating_utilisation", "ratio; VGS / 6 V"),
    ("id_continuous_rating_utilisation", "ratio; |ID| / 115 A"),
    ("is_rating_exceeded", "bool"),
    ("kcl_residual_A", "A; ID+IG+IS, identity residual"),
    ("ploss_identity_residual_W", "W; Ploss-(Pcond+Psw), identity residual"),
    ("pcond_minus_vds_id_W", "W; displacement-attributed power, not model error"),
    ("cgd_derived_F", "F; = Crss"),
    ("cds_derived_F", "F; = Coss - Crss"),
    ("cgs_derived_F", "F; = Ciss - 2*Crss"),
    ("evidence_class", "provenance class of the row"),
    ("has_experimental_validation", "always False"),
    ("is_aging_measurement", "always False"),
    ("aging_time_h", "always NaN; no aging axis exists"),
)

EVIDENCE_CALCULATED = "calculated_from_stage1_simulation"


@dataclass
class Stage2Artifacts:
    dataset: pd.DataFrame
    quality: QualityReport
    physics_checks: list[PhysicsCheck]
    manifest: dict[str, Any]

    @property
    def schema(self) -> list[dict[str, str]]:
        cfg_units = dict(Stage2Config().schema)
        rows = [{"column": c, "unit": u, "origin": "stage1"} for c, u in Stage2Config().schema]
        rows += [{"column": c, "unit": u, "origin": "stage2_derived"} for c, u in DERIVED_COLUMNS]
        return rows


def build_dataset(bundle: Stage1Bundle, cfg: Stage2Config) -> Stage2Artifacts:
    """Build the Phase 2A dataset, quality report and manifest."""
    params = dict(bundle.mat_params)
    ratings = bundle.summary_json.get("ratings", {}) or {}
    # Carry the printed ratings into the physics rules. They are datasheet
    # values, so they are used directly rather than restated as constants.
    params["_ratings"] = ratings

    enriched = add_physics_columns(bundle.frame, params, cfg)
    enriched = estimate_differential_ron(enriched, cfg)

    # --- conditioning context -------------------------------------------
    dec = int(cfg.operating_point_decimals.value)
    snap = {c: enriched[c].round(dec) for c in ("vgs_V", "vds_V", "tcase_C")}
    enriched["operating_point_key"] = (
        snap["vgs_V"].astype(str)
        + "|"
        + snap["vds_V"].astype(str)
        + "|"
        + snap["tcase_C"].astype(str)
    )
    enriched["sample_index"] = enriched.groupby("profile").cumcount().astype(int)

    # --- honest placeholders ---------------------------------------------
    # Requirement 3 cannot be met from this dataset (see physics check P09),
    # so the column exists and is explicitly empty rather than absent, which
    # would let a consumer assume the normalisation had simply been forgotten.
    enriched["ron_temp_normalised_ohm"] = np.nan
    enriched["ron_tempnorm_status"] = pd.Series(
        "unavailable: Stage 1 channel current has no temperature term and the datasheet "
        "prints no RON(T) coefficient",
        index=enriched.index,
        dtype="string",
    )

    # --- provenance -------------------------------------------------------
    enriched["evidence_class"] = EVIDENCE_CALCULATED
    enriched["has_experimental_validation"] = False
    enriched["is_aging_measurement"] = False
    enriched["aging_time_h"] = np.nan

    ordered = [c for c, _ in cfg.schema] + [c for c, _ in DERIVED_COLUMNS]
    dataset = enriched[ordered].sort_values(["profile", "sample_index"]).reset_index(drop=True)

    quality = run_quality_checks(bundle, cfg)
    physics_checks = run_physics_checks(dataset, params, cfg)

    manifest = _build_manifest(dataset, bundle, quality, physics_checks, cfg, params)
    return Stage2Artifacts(dataset=dataset, quality=quality, physics_checks=physics_checks, manifest=manifest)


def _build_manifest(
    dataset: pd.DataFrame,
    bundle: Stage1Bundle,
    quality: QualityReport,
    physics_checks: list[PhysicsCheck],
    cfg: Stage2Config,
    params: dict[str, Any],
) -> dict[str, Any]:
    per_profile = {
        name: {
            "rows": int(len(block)),
            "t_start_s": float(block["t_s"].min()),
            "t_stop_s": float(block["t_s"].max()),
            "dt_median_s": float(np.median(np.diff(block["t_s"].to_numpy(float)))) if len(block) > 1 else None,
            "vgs_values": sorted({round(float(v), 6) for v in block["vgs_V"]}),
            "vds_range_V": [float(block["vds_V"].min()), float(block["vds_V"].max())],
            "tcase_values_C": sorted({round(float(v), 6) for v in block["tcase_C"]}),
            "operating_point_keys": int(block["operating_point_key"].nunique()),
            "ron_valid_rows": int(block["ron_valid"].sum()),
            "application_operating_rows": int(block["is_application_operating_point"].sum()),
        }
        for name, block in dataset.groupby("profile", sort=True)
    }

    return {
        "stage": "2A",
        "purpose": "ingestion, data-quality validation and physics-consistency screening",
        "not_in_scope": [
            "degradation modelling",
            "health-indicator weighting",
            "health-state classification",
            "remaining useful life",
            "predictive accuracy",
            "dashboard",
        ],
        "authoritative_source": "stage1_output.mat",
        "sources": bundle.sources,
        "csv_parse": bundle.csv_parse.to_dict() if bundle.csv_parse is not None else None,
        "device": {
            # The MAT splits identity across two groups: the `meta` group holds
            # part_number and datasheet_revision, while `manufacturer` and the
            # rest of the identity live under `p/meta`. Read both so the header
            # names the actual device instead of printing None.
            "part_number": bundle.mat_meta.get("part_number") or bundle.param("meta.device_part_number"),
            "datasheet_revision": bundle.mat_meta.get("datasheet_revision") or bundle.param("meta.datasheet_revision"),
            "manufacturer": bundle.mat_meta.get("manufacturer") or bundle.param("meta.manufacturer"),
            "technology": bundle.param("meta.technology"),
            "package": bundle.param("meta.package"),
            "publication_order": bundle.param("meta.publication_order"),
            "datasheet_pages": bundle.param("meta.datasheet_pages"),
            "model_file": bundle.mat_meta.get("model_file"),
            "generated_by": bundle.mat_meta.get("generated_by"),
            "generated_utc": bundle.mat_meta.get("generated_utc"),
            "matlab_release": bundle.mat_meta.get("matlab_release"),
        },
        "evidence": {
            "evidence_class": EVIDENCE_CALCULATED,
            "has_experimental_validation": False,
            "is_aging_measurement": False,
            "model_prediction_label": bundle.mat_meta.get("model_prediction_label"),
            "thermal_note": bundle.mat_meta.get("thermal_note"),
            "unvalidatable": bundle.mat_report.get("unvalidatable", []),
            "dataset_defects": nested_section(bundle.mat_report, "dataset_defects"),
            "stage1_verification_summary": nested_section(bundle.mat_report, "summary"),
        },
        "provenance": build_provenance_record(bundle.mat_params, cfg.mapping_path),
        "row_count": int(len(dataset)),
        "column_count": int(dataset.shape[1]),
        "profiles": per_profile,
        "quality_summary": quality.to_dict()["summary"],
        "physics_summary": {
            "total": len(physics_checks),
            "passed": sum(1 for c in physics_checks if c.status == "PASS"),
            "warned": sum(1 for c in physics_checks if c.status == "WARN"),
            "blocked": sum(1 for c in physics_checks if c.status == "BLOCKED"),
            "info": sum(1 for c in physics_checks if c.status == "INFO"),
        },
        "blockers": [c.check_id for c in quality.blockers] + [
            c.check_id for c in physics_checks if c.severity == "BLOCKER"
        ],
        "analysis_conventions": {
            "conduction_leakage_multiple": {
                "value": cfg.conduction_leakage_multiple.value,
                "justification": cfg.conduction_leakage_multiple.justification,
            },
            "vds_positive_floor_V": {
                "value": cfg.vds_positive_floor_V.value,
                "justification": cfg.vds_positive_floor_V.justification,
            },
            "operating_point_decimals": {
                "value": cfg.operating_point_decimals.value,
                "justification": cfg.operating_point_decimals.justification,
            },
        },
        "tolerances": {
            "kcl_atol": {"value": cfg.kcl_atol.value, "justification": cfg.kcl_atol.justification},
            "power_balance_atol": {
                "value": cfg.power_balance_atol.value,
                "justification": cfg.power_balance_atol.justification,
            },
            "csv_mat_rtol": {
                "value": cfg.csv_mat_rtol.value,
                "justification": cfg.csv_mat_rtol.justification,
            },
            "ron_positive_floor_ohm": {
                "value": cfg.ron_positive_floor_ohm.value,
                "justification": cfg.ron_positive_floor_ohm.justification,
            },
        },
        "schema": [{"column": c, "unit": u, "origin": "stage1"} for c, u in cfg.schema]
        + [{"column": c, "unit": u, "origin": "stage2_derived"} for c, u in DERIVED_COLUMNS],
    }


def write_artifacts(artifacts: Stage2Artifacts, cfg: Stage2Config) -> dict[str, str]:
    """Write the dataset, manifest and quality report under ``output_dir``.

    Each file is staged in a temporary sibling and moved into place, so a run
    that is interrupted part-way cannot leave a half-written artefact behind for
    the next reader to trust.
    """
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    _atomic_write_csv(artifacts.dataset, cfg.dataset_path)
    _atomic_write_json(artifacts.manifest, cfg.manifest_path)

    payload = artifacts.quality.to_dict()
    payload["physics_checks"] = [
        {
            "check_id": c.check_id,
            "name": c.name,
            "status": c.status,
            "severity": c.severity,
            "detail": c.detail,
            "affected": c.affected,
        }
        for c in artifacts.physics_checks
    ]
    _atomic_write_json(payload, cfg.quality_path)

    return {
        "dataset": str(cfg.dataset_path),
        "manifest": str(cfg.manifest_path),
        "quality_report": str(cfg.quality_path),
    }


def _atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    staged = path.with_name(f".{path.name}.partial")
    try:
        frame.to_csv(staged, index=False)
        staged.replace(path)
    finally:
        if staged.exists():
            staged.unlink()


def _atomic_write_json(payload: dict[str, Any], path: Path) -> None:
    staged = path.with_name(f".{path.name}.partial")
    try:
        with open(staged, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        staged.replace(path)
    finally:
        if staged.exists():
            staged.unlink()
