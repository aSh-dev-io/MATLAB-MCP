"""Structural data-quality checks on the ingested Stage 1 artefacts.

These complement :mod:`ganstage2.physics`. Where physics asks "is this sample
interpretable", quality asks "is the file itself trustworthy and complete".
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd

from .config import Stage2Config
from .ingestion import Stage1Bundle
from .matv73 import nested_section


@dataclass
class Check:
    check_id: str
    category: str
    name: str
    status: str  # PASS | FAIL | WARN | INFO | BLOCKED
    severity: str  # BLOCKER | HIGH | MEDIUM | LOW | INFO
    detail: str
    affected: int = 0
    evidence_class: str = "calculated_from_stage1_output"

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualityReport:
    checks: list[Check]

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.checks:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    @property
    def blockers(self) -> list[Check]:
        return [c for c in self.checks if c.severity == "BLOCKER"]

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status in ("FAIL", "BLOCKED")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "total": len(self.checks),
                **{k.lower(): v for k, v in sorted(self.counts.items())},
            },
            "checks": [c.to_dict() for c in self.checks],
        }

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([c.to_dict() for c in self.checks])


def run_quality_checks(bundle: Stage1Bundle, cfg: Stage2Config) -> QualityReport:
    df = bundle.frame
    expected_cols = [c for c, _ in cfg.schema]
    checks: list[Check] = []

    # Q01 required files
    present = {k: bool(v) for k, v in bundle.sources.items()}
    checks.append(
        Check(
            "Q01",
            "structure",
            "Stage 1 artefacts present",
            "PASS" if all(present[k] for k in ("mat", "csv", "json")) else "FAIL",
            "HIGH",
            ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in present.items()),
        )
    )

    # Q02 canonical schema
    missing = [c for c in expected_cols if c not in df.columns]
    checks.append(
        Check(
            "Q02",
            "structure",
            "Canonical schema complete",
            "PASS" if not missing else "FAIL",
            "HIGH",
            f"{len(expected_cols) - len(missing)}/{len(expected_cols)} columns present"
            + (f"; missing {missing}" if missing else ""),
            affected=len(missing),
        )
    )

    # Q03 profile set
    found = set(df["profile"].unique())
    expected = set(cfg.profile_roles)
    checks.append(
        Check(
            "Q03",
            "structure",
            "Profile set matches the declared inventory",
            "PASS" if found == expected else "FAIL",
            "HIGH",
            f"found {sorted(found)}; expected {sorted(expected)}",
            affected=len(found ^ expected),
        )
    )

    # Q04 CSV defect (the headline ingestion finding)
    parse = bundle.csv_parse
    if parse is not None:
        checks.append(
            Check(
                "Q04",
                "ingestion",
                "Stage 1 CSV is well formed",
                "FAIL" if parse.is_defective else "PASS",
                "HIGH",
                parse.defect
                or f"{parse.rows_read} rows parsed cleanly with "
                f"{parse.header_field_count} declared columns.",
                affected=parse.rows_read if parse.is_defective else 0,
                evidence_class="calculated_from_stage1_output",
            )
        )

        # Q05 repaired CSV agrees with the authoritative MAT
        if bundle.csv_frame is not None:
            csv_df = bundle.csv_frame
            numeric = [c for c, u in cfg.schema if u != "categorical" and c in csv_df.columns]
            # Align on (profile, sample ordinal) rather than row order or t_s:
            # the MAT is read in alphabetical profile order while the CSV follows
            # the Stage 1 run order, and MATLAB's CSV writer truncates t_s
            # precision to ~1e-21, so raw time values are not a reliable key.
            # The within-profile ordinal is exact in both.
            left = csv_df.assign(_k=csv_df.groupby("profile").cumcount())
            right = df.assign(_k=df.groupby("profile").cumcount())
            keys = ["profile", "_k"]
            left = left.set_index(keys).sort_index()
            right = right.set_index(keys).sort_index()
            if len(left) == len(right) and left.index.equals(right.index):
                worst, worst_col = 0.0, ""
                for col in numeric:
                    a = left[col].to_numpy(float)
                    b = right[col].to_numpy(float)
                    with np.errstate(invalid="ignore"):
                        denom = np.where(np.abs(b) > 0, np.abs(b), 1.0)
                        rel = np.nanmax(np.abs(a - b) / denom)
                    if np.isfinite(rel) and rel > worst:
                        worst, worst_col = float(rel), col
                checks.append(
                    Check(
                        "Q05",
                        "ingestion",
                        "Repaired CSV matches the MAT sample for sample",
                        "PASS" if worst <= cfg.csv_mat_rtol.value else "FAIL",
                        "HIGH",
                        f"{len(left)} samples compared across {len(numeric)} numeric signals, "
                        f"joined on (profile, sample ordinal); max relative difference {worst:.3e}"
                        + (f" (column {worst_col})" if worst_col else "")
                        + ". Confirms the in-memory repair is exact and the MAT is usable "
                        "as the authoritative source.",
                    )
                )
            else:
                checks.append(
                    Check(
                        "Q05",
                        "ingestion",
                        "Repaired CSV matches the MAT sample for sample",
                        "FAIL",
                        "HIGH",
                        f"row count {len(csv_df)} vs MAT {len(df)}, or the "
                        "(profile, sample ordinal) keys do not correspond",
                    )
                )

    # Q06 finiteness
    numeric_cols = [c for c, u in cfg.schema if u != "categorical"]
    inf_mask = np.zeros(len(df), dtype=bool)
    for col in numeric_cols:
        values = df[col].to_numpy(float)
        inf_mask |= np.isinf(values)
    checks.append(
        Check(
            "Q06",
            "completeness",
            "No infinite values",
            "PASS" if not inf_mask.any() else "FAIL",
            "HIGH",
            f"{int(inf_mask.sum())} samples contain +/-inf",
            affected=int(inf_mask.sum()),
        )
    )

    # Q07 NaN inventory, reported per column rather than silently dropped
    nan_report = {c: int(df[c].isna().sum()) for c in numeric_cols if df[c].isna().any()}
    checks.append(
        Check(
            "Q07",
            "completeness",
            "Missing-value inventory",
            "WARN" if nan_report else "PASS",
            "MEDIUM",
            (
                "; ".join(f"{c}: {v}" for c, v in nan_report.items())
                + ". All are confined to ron_stage1_ohm, where Stage 1 itself writes NaN "
                "for ID <= 0.1 A. No other signal has gaps."
            )
            if set(nan_report) <= {"ron_stage1_ohm"}
            else ("; ".join(f"{c}: {v}" for c, v in nan_report.items()) or "no missing values"),
            affected=sum(nan_report.values()),
        )
    )

    # Q08 time base per profile
    bad_time = []
    for name, block in df.groupby("profile"):
        t = block["t_s"].to_numpy(float)
        if len(t) > 1:
            dt = np.diff(t)
            if not np.all(dt > 0):
                bad_time.append(f"{name}: non-monotonic")
    checks.append(
        Check(
            "Q08",
            "structure",
            "Simulation time strictly increasing within each profile",
            "PASS" if not bad_time else "FAIL",
            "MEDIUM",
            f"{df['profile'].nunique()} profiles checked"
            + ("; " + "; ".join(bad_time) if bad_time else ""),
            affected=len(bad_time),
        )
    )

    # Q09 sampling interval matches the solver setting
    dts = np.concatenate(
        [np.diff(block["t_s"].to_numpy(float)) for _, block in df.groupby("profile") if len(block) > 1]
    )
    dt_med = float(np.median(dts)) if dts.size else float("nan")
    dt_spread = float(np.ptp(dts)) if dts.size else float("nan")
    declared = bundle.param("solver.sample_time_s")
    dt_ok = np.isfinite(dt_med) and (
        declared is None or abs(dt_med - float(declared)) <= 1e-15 + 1e-6 * float(declared)
    )
    checks.append(
        Check(
            "Q09",
            "structure",
            "Sampling interval uniform and equal to the solver step",
            "PASS" if dt_ok else "WARN",
            "LOW",
            f"median dt = {dt_med:.6e} s, spread = {dt_spread:.3e} s; "
            f"solver declares {declared} s",
            evidence_class="calculated_from_stage1_output",
        )
    )

    # Q10 duplicate rows within a profile
    dupes = int(df.duplicated(subset=["profile", "t_s"]).sum())
    checks.append(
        Check(
            "Q10",
            "structure",
            "No duplicate (profile, time) samples",
            "PASS" if dupes == 0 else "WARN",
            "LOW",
            f"{dupes} duplicate keys",
            affected=dupes,
        )
    )

    # Q11 JSON summary agrees with the MAT on profile inventory
    json_profiles = bundle.summary_json.get("profiles")
    json_names = (
        sorted(p.get("name") for p in json_profiles)
        if isinstance(json_profiles, list)
        else sorted(json_profiles or {})
    )
    checks.append(
        Check(
            "Q11",
            "consistency",
            "Summary JSON profile inventory matches the MAT",
            "PASS" if json_names == sorted(found) else "FAIL",
            "MEDIUM",
            f"json={json_names}, mat={sorted(found)}",
        )
    )

    # Q12 JSON sample counts match the MAT
    if isinstance(json_profiles, list):
        mismatches = []
        for entry in json_profiles:
            name = entry.get("name")
            declared_n = entry.get("samples")
            actual_n = int((df["profile"] == name).sum())
            if declared_n is not None and int(declared_n) != actual_n:
                mismatches.append(f"{name}: json {declared_n} vs mat {actual_n}")
        checks.append(
            Check(
                "Q12",
                "consistency",
                "Summary JSON sample counts match the MAT",
                "PASS" if not mismatches else "FAIL",
                "MEDIUM",
                "all profile counts agree" if not mismatches else "; ".join(mismatches),
                affected=len(mismatches),
            )
        )

    # Q13 Stage 1 dataset defects carried forward, not silently dropped
    # The MAT report group is flattened by flatten_group(), so the defect flags
    # arrive as dotted keys ("dataset_defects.curves_absent") and are re-nested
    # before use. They are MATLAB logicals stored as tagged uint8; decoding them
    # as text would yield "\x01" and make every flag look false.
    defects = nested_section(bundle.mat_report, "dataset_defects")
    carried = sorted(k for k, v in defects.items() if isinstance(v, bool) and v)
    checks.append(
        Check(
            "Q13",
            "provenance",
            "Stage 1 dataset defects propagated into Stage 2",
            "INFO" if carried else "PASS",
            "INFO",
            f"Stage 1 recorded {len(carried)} dataset defects: {carried}. These are "
            "dataset properties, not ingestion failures, and remain open in Stage 2.",
            affected=len(carried),
        )
    )

    # Q14 every Stage 1 signal is synthetic model output
    label = bundle.mat_meta.get("model_prediction_label", "")
    checks.append(
        Check(
            "Q14",
            "provenance",
            "Evidence class recorded as unvalidated model output",
            "PASS" if "NOT VALIDATED" in str(label) else "WARN",
            "INFO",
            f"Stage 1 label: {label!r}. No experimental validation data exists anywhere "
            "in the inputs, so no Stage 2 output may be described as measured or "
            "experimentally validated.",
        )
    )

    # Q15 no aging axis present
    checks.append(
        Check(
            "Q15",
            "provenance",
            "Aging axis present in the source data",
            "BLOCKED",
            "BLOCKER",
            "There is no aging time, no repeated measurement of the same device and no "
            "second device instance. t_s is simulation time within a single sweep. "
            "Permanent degradation cannot be separated from operating-condition changes.",
            affected=len(df),
        )
    )

    return QualityReport(checks)
