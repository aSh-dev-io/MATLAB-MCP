"""Configuration for Stage 2 Phase 2A.

Every numeric tolerance and threshold used anywhere in Stage 2 lives here, and
every one carries a ``justification`` string. This is deliberate: the project
rule is that a threshold may only be introduced if it is either (a) taken from
the datasheet, (b) derived from the Stage 1 model equations, or (c) declared
explicitly as an analysis convention of this pipeline.

Nothing here is a degradation coefficient or a health threshold. Phase 2A does
not invent those; see ``docs/PHASE2A_REPORT.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Repository layout, resolved relative to this file so the pipeline is
# relocatable: src/ganstage2/config.py -> stage2/
STAGE2_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = STAGE2_ROOT.parent
STAGE1_ROOT = PROJECT_ROOT


@dataclass(frozen=True)
class Tolerance:
    """A single numeric tolerance with a recorded justification."""

    value: float
    justification: str

    def __repr__(self) -> str:  # pragma: no cover - display only
        return f"Tolerance({self.value!r}, {self.justification!r})"


@dataclass(frozen=True)
class AnalysisConvention:
    """An analysis choice that is *not* a datasheet value.

    Kept separate from :class:`Tolerance` so the report can separate
    "the data violates physics" from "this pipeline made a defensible choice".
    """

    value: float
    justification: str


@dataclass(frozen=True)
class Stage2Config:
    """Inputs, outputs and analysis conventions for Phase 2A."""

    # ---- paths -------------------------------------------------------------
    stage1_root: Path = STAGE1_ROOT
    output_dir: Path = field(default_factory=lambda: STAGE2_ROOT / "output")

    @property
    def mat_path(self) -> Path:
        return self.stage1_root / "results" / "stage1_output.mat"

    @property
    def csv_path(self) -> Path:
        return self.stage1_root / "results" / "stage1_output.csv"

    @property
    def json_path(self) -> Path:
        return self.stage1_root / "results" / "stage1_summary.json"

    @property
    def mapping_path(self) -> Path:
        return self.stage1_root / "DATASET_MAPPING.md"

    @property
    def dataset_path(self) -> Path:
        return self.output_dir / "stage2_dataset.csv"

    @property
    def manifest_path(self) -> Path:
        return self.output_dir / "stage2_manifest.json"

    @property
    def quality_path(self) -> Path:
        return self.output_dir / "stage2_quality_report.json"

    @property
    def report_path(self) -> Path:
        return self.output_dir / "PHASE2A_REPORT.md"

    # ---- Phase 2B outputs --------------------------------------------------
    # Kept in the same output directory as Phase 2A rather than a parallel
    # ``outputs/`` tree: there is one Stage 2 dataset and one set of provenance
    # rules, so splitting the artefacts across two directories would invite a
    # consumer to read Phase 2B against a stale Phase 2A copy.

    @property
    def stress_dataset_path(self) -> Path:
        return self.output_dir / "stress_dataset.csv"

    @property
    def stress_trajectories_path(self) -> Path:
        return self.output_dir / "stress_trajectories.csv"

    @property
    def stress_report_path(self) -> Path:
        return self.output_dir / "stress_analysis_report.md"

    @property
    def stress_json_path(self) -> Path:
        return self.output_dir / "stress_analysis.json"

    # ---- Phase 2C outputs ---------------------------------------------------
    # Exposure indicators, not health indicators. The filename says "exposure"
    # so no downstream consumer can read a health claim into the artefact.

    @property
    def indicators_path(self) -> Path:
        return self.output_dir / "exposure_indicators.csv"

    @property
    def indicators_json_path(self) -> Path:
        return self.output_dir / "exposure_indicators.json"

    @property
    def trajectory_indicators_path(self) -> Path:
        return self.output_dir / "exposure_by_trajectory.csv"

    @property
    def indicators_report_path(self) -> Path:
        return self.output_dir / "PHASE2C_REPORT.md"

    # ---- schema ------------------------------------------------------------
    # Canonical column order and units, taken verbatim from the Stage 1 CSV
    # header. profile is categorical; every other column is numeric.
    schema: tuple[tuple[str, str], ...] = (
        ("profile", "categorical"),
        ("t_s", "s"),
        ("vgs_V", "V"),
        ("vds_V", "V"),
        ("tcase_C", "degC"),
        ("id_A", "A"),
        ("ig_A", "A"),
        ("is_A", "A"),
        ("ron_stage1_ohm", "Ohm"),
        ("pcond_W", "W"),
        ("psw_W", "W"),
        ("ploss_W", "W"),
        ("tj_C", "degC"),
        ("qg_C", "C"),
        ("qgd_C", "C"),
        ("ciss_F", "F"),
        ("coss_F", "F"),
        ("crss_F", "F"),
    )

    #: Stage 1 MAT field name -> canonical column name.
    mat_field_map: dict[str, str] = field(
        default_factory=lambda: {
            "time": "t_s",
            "Vgs": "vgs_V",
            "Vds": "vds_V",
            "ID": "id_A",
            "IG": "ig_A",
            "IS": "is_A",
            "RON": "ron_stage1_ohm",
            "Pcond": "pcond_W",
            "Psw": "psw_W",
            "Ploss": "ploss_W",
            "Tj": "tj_C",
            "Tcase": "tcase_C",
            "Qg": "qg_C",
            "Qgd": "qgd_C",
            "Ciss": "ciss_F",
            "Coss": "coss_F",
            "Crss": "crss_F",
        }
    )

    #: Stage 1 CSV header name -> canonical column name. The CSV keeps the
    #: MATLAB identifiers, so it needs its own map; without this the CSV/MAT
    #: cross-check would silently compare only the one column whose name
    #: happens to agree in both.
    csv_field_map: dict[str, str] = field(
        default_factory=lambda: {
            "profile": "profile",
            "t_s": "t_s",
            "Vgs_V": "vgs_V",
            "Vds_V": "vds_V",
            "Tcase_C": "tcase_C",
            "ID_A": "id_A",
            "IG_A": "ig_A",
            "IS_A": "is_A",
            "RON_ohm": "ron_stage1_ohm",
            "Pcond_W": "pcond_W",
            "Psw_W": "psw_W",
            "Ploss_W": "ploss_W",
            "Tj_C": "tj_C",
            "Qg_C": "qg_C",
            "Qgd_C": "qgd_C",
            "Ciss_F": "ciss_F",
            "Coss_F": "coss_F",
            "Crss_F": "crss_F",
        }
    )

    #: What each Stage 1 profile is *for*. Used to separate datasheet
    #: characterisation sweeps from application-representative operation, which
    #: is the distinction requirement 1 depends on.
    profile_roles: dict[str, str] = field(
        default_factory=lambda: {
            "output": "dc_output_sweep",
            "transfer": "dc_transfer_sweep",
            "capacitance": "cv_characterisation",
            "charge": "gate_charge_characterisation",
            "switching": "switching_transient",
            "thermal": "dc_thermal_sweep",
        }
    )

    # ---- numerical tolerances ---------------------------------------------
    #: Charge balance ID + IG + IS = 0 is an identity, so this is a
    #: floating-point accumulation allowance only.
    kcl_atol: Tolerance = Tolerance(
        1e-9,
        "Node current balance ID+IG+IS=0 is an algebraic identity in the Stage 1 "
        "model; the tolerance covers float64 round-off over Vgs/ID magnitudes up "
        "to ~2e3 A, not model error.",
    )

    #: Ploss = Pcond + Psw is likewise an identity by construction.
    power_balance_atol: Tolerance = Tolerance(
        1e-9,
        "Ploss is defined as Pcond+Psw in the Stage 1 terminal script, so any "
        "residual is float64 round-off only.",
    )

    #: Relative allowance when comparing CSV against MAT.
    csv_mat_rtol: Tolerance = Tolerance(
        1e-9,
        "The CSV and MAT hold the same arrays, but MATLAB writes CSV as text "
        "with roughly 10 significant digits, so agreement is bounded by that "
        "formatting rather than being exact. Observed worst case is ~2.7e-10 "
        "relative, on gate-ramp voltages such as 1.0526315789473684 written as "
        "1.052631579. Anything larger would indicate a real misalignment.",
    )

    #: RON values closer to zero than this cannot be a real resistance.
    ron_positive_floor_ohm: Tolerance = Tolerance(
        1e-9,
        "A conduction resistance is strictly positive. A non-positive value is "
        "an artefact of Vds/ID with Vds=0, not a measurement of zero ohms.",
    )

    # ---- analysis conventions (explicitly NOT datasheet values) -----------
    #: How many times leakage the channel current must exceed before the
    #: sample is called "conducting". Anchored on IDSS, which is printed.
    conduction_leakage_multiple: AnalysisConvention = AnalysisConvention(
        100.0,
        "A sample counts as conducting when |ID| >= 100 x I_leak. 100x is an "
        "analysis convention, chosen so channel current dominates the "
        "dataset-anchored leakage model (IDSS = 4 uA at 25 degC) by two "
        "decades. It is a classification choice, not a physical constant.",
    )

    #: Vds must exceed this for Vds/ID to be a meaningful resistance.
    vds_positive_floor_V: AnalysisConvention = AnalysisConvention(
        1e-6,
        "Numerical floor only. At Vds = 0 the ratio Vds/ID is identically zero "
        "regardless of the device's true resistance.",
    )

    #: Rounding used to build the like-for-like operating-point key.
    operating_point_decimals: AnalysisConvention = AnalysisConvention(
        3,
        "Biases are snapped to 1e-3 V / 1e-3 degC so that repeated samples at "
        "nominally identical conditions group into one comparison bucket. "
        "Sampling noise is far below this.",
    )

    def as_dict(self) -> dict[str, Any]:
        """Serialisable view, for embedding in the run manifest."""
        d = asdict(self)
        d["stage1_root"] = str(self.stage1_root)
        d["output_dir"] = str(self.output_dir)
        d["schema"] = [list(pair) for pair in self.schema]
        return d
