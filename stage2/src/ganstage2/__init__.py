"""Stage 2 of the GaN HEMT digital twin: physics-informed degradation analysis.

Phase 2A (this implementation) covers ingestion, data-quality validation,
physics-consistency screening, and assembly of a structured dataset for
Phase 2B. It deliberately implements no degradation model, health score, health
state or remaining-useful-life estimate, because the Stage 1 output contains no
aging data that could support one.
"""

from .config import Stage2Config
from .dataset import Stage2Artifacts, build_dataset, write_artifacts
from .ingestion import Stage1Bundle, load_stage1
from .provenance import PROVENANCE_TAGS, build_provenance_record
from .quality import QualityReport, run_quality_checks

__all__ = [
    "Stage2Config",
    "Stage1Bundle",
    "Stage2Artifacts",
    "load_stage1",
    "run_quality_checks",
    "build_dataset",
    "write_artifacts",
    "QualityReport",
    "PROVENANCE_TAGS",
    "build_provenance_record",
]

__version__ = "0.3.0"
