"""Stage 1 artefact ingestion.

Design decision, and the most important one in Phase 2A:

**The ``.mat`` is the authoritative source; the ``.csv`` is cross-checked
against it.**

The Stage 1 CSV writer terminates every data row with a trailing delimiter, so
each data line carries one more field than the header declares. pandas does not
raise on this: it treats the first field as the DataFrame index and shifts all
remaining columns one position left. The result looks plausible and is
completely wrong — ``profile`` becomes numeric, every signal is mislabelled, and
``Crss`` becomes all-NaN. Nothing in the file signals the corruption to a caller
who does not check field counts.

So this module never hands a naive ``read_csv`` result to the rest of the
pipeline. It parses field-count-explicitly, records the defect, repairs it in
memory, and then proves the repair by comparing every numeric cell against the
MAT. Stage 1 files are opened read-only and are never rewritten.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd

from .config import Stage2Config
from .matv73 import as_series, decode_text, flatten_group, is_v73


class IngestionError(RuntimeError):
    """Raised when a Stage 1 artefact cannot be read at all."""


@dataclass
class CsvParseReport:
    """What actually happened while reading the Stage 1 CSV."""

    path: str
    header: list[str]
    header_field_count: int
    rows_read: int
    rows_repaired_trailing_delimiter: int
    rows_dropped_malformed: int
    is_defective: bool
    defect: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "header": self.header,
            "header_field_count": self.header_field_count,
            "rows_read": self.rows_read,
            "rows_repaired_trailing_delimiter": self.rows_repaired_trailing_delimiter,
            "rows_dropped_malformed": self.rows_dropped_malformed,
            "is_defective": self.is_defective,
            "defect": self.defect,
            "notes": self.notes,
        }


def read_csv_field_count_explicit(
    path: Path, cfg: Stage2Config
) -> tuple[pd.DataFrame, CsvParseReport]:
    """Read *path* without ever letting pandas guess the column layout.

    Every record is tokenised with :mod:`csv` and checked against the header
    width. A row with exactly one surplus trailing empty field is the known
    Stage 1 writer defect and is repaired in memory. Anything else is dropped
    and reported rather than silently misaligned.
    """
    with open(path, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as exc:  # pragma: no cover - empty file
            raise IngestionError(f"{path} is empty") from exc

        width = len(header)
        rows: list[list[str]] = []
        repaired = 0
        dropped = 0

        for record in reader:
            if not record or (len(record) == 1 and not record[0].strip()):
                continue

            if len(record) == width + 1 and record[-1].strip() == "":
                # Known Stage 1 defect: writer emits "<values>," per row.
                record = record[:-1]
                repaired += 1
            elif len(record) != width:
                dropped += 1
                continue

            # Guard the specific corruption mode this defect causes: a record
            # whose first field is not a known profile name.
            if record[0] not in cfg.profile_roles:
                dropped += 1
                continue

            rows.append(record)

    report = CsvParseReport(
        path=str(path),
        header=header,
        header_field_count=width,
        rows_read=len(rows),
        rows_repaired_trailing_delimiter=repaired,
        rows_dropped_malformed=dropped,
        is_defective=repaired > 0,
        defect=(
            "Every data row carries a trailing delimiter, so each record has "
            f"{width + 1} fields against a {width}-column header. A default "
            "pandas read_csv silently promotes field 0 to the index and shifts "
            "all signals one column left, mislabelling every signal and "
            "nulling Crss_F. Repaired in memory by dropping the surplus empty "
            "trailing field; the Stage 1 file is left unmodified."
        )
        if repaired
        else None,
    )

    if header[: len(cfg.schema)] != [c for c, _ in cfg.schema]:
        report.notes.append(
            "CSV header uses the Stage 1 MATLAB identifiers rather than the canonical "
            f"schema; got {header}"
        )

    unmapped = [h for h in header[:width] if h not in cfg.csv_field_map]
    if unmapped:
        report.notes.append(f"CSV columns with no canonical mapping, dropped: {unmapped}")

    frame = pd.DataFrame(rows, columns=header[:width])
    frame = frame.rename(columns=cfg.csv_field_map)

    for column, unit in cfg.schema:
        if unit == "categorical":
            if column in frame.columns:
                frame[column] = frame[column].astype("string")
        elif column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return frame[[c for c, _ in cfg.schema if c in frame.columns]].reset_index(drop=True), report


def load_mat_signals(path: Path, cfg: Stage2Config) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load every profile from the Stage 1 v7.3 MAT into one tidy frame."""
    if not is_v73(str(path)):
        raise IngestionError(
            f"{path} is not a MAT v7.3 (HDF5) file; Stage 2 needs -v7.3 export"
        )

    frames: list[pd.DataFrame] = []
    with h5py.File(path, "r") as handle:
        data = handle["data"]
        for name in sorted(data.keys()):
            group = data[name]
            # len() on a (1, N) HDF5 dataset gives 1, so ravel to get the sample count.
            n_samples = as_series(group["time"]).size
            block: dict[str, Any] = {"profile": pd.Series([name] * n_samples, dtype="string")}
            for field_name, column in cfg.mat_field_map.items():
                if field_name not in group:
                    raise IngestionError(f"profile {name!r} is missing field {field_name!r}")
                values = as_series(group[field_name])
                if values.size != n_samples:
                    raise IngestionError(
                        f"profile {name!r} field {field_name!r} has {values.size} samples, "
                        f"expected {n_samples}"
                    )
                block[column] = values
            frames.append(pd.DataFrame(block))

        params = flatten_group(handle["p"])
        meta = flatten_group(handle["meta"])
        report_meta = flatten_group(handle["report"])

    frame = pd.concat(frames, ignore_index=True)
    frame = frame[[c for c, _ in cfg.schema]]
    return frame, {"params": params, "meta": meta, "report": report_meta}


def load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class Stage1Bundle:
    """Everything Phase 2A needs from Stage 1, plus the defects found on the way."""

    frame: pd.DataFrame
    mat_params: dict[str, Any]
    mat_meta: dict[str, Any]
    mat_report: dict[str, Any]
    summary_json: dict[str, Any]
    csv_frame: pd.DataFrame | None
    csv_parse: CsvParseReport | None
    sources: dict[str, str]

    def param(self, key: str, default: Any = None) -> Any:
        return self.mat_params.get(key, default)


def load_stage1(cfg: Stage2Config) -> Stage1Bundle:
    """Load all three Stage 1 artefacts.

    The MAT must load. The CSV and JSON are loaded when present; a missing CSV
    degrades the cross-check rather than failing the run, because the MAT alone
    is sufficient to build the dataset.
    """
    missing = [p for p in (cfg.mat_path,) if not p.exists()]
    if missing:
        raise IngestionError(f"missing required Stage 1 artefact(s): {missing}")

    frame, mat_aux = load_mat_signals(cfg.mat_path, cfg)

    csv_frame = None
    csv_parse = None
    if cfg.csv_path.exists():
        csv_frame, csv_parse = read_csv_field_count_explicit(cfg.csv_path, cfg)

    summary_json: dict[str, Any] = {}
    if cfg.json_path.exists():
        summary_json = load_json(cfg.json_path)

    return Stage1Bundle(
        frame=frame,
        mat_params=mat_aux["params"],
        mat_meta=mat_aux["meta"],
        mat_report=mat_aux["report"],
        summary_json=summary_json,
        csv_frame=csv_frame,
        csv_parse=csv_parse,
        sources={
            "mat": str(cfg.mat_path),
            "csv": str(cfg.csv_path) if cfg.csv_path.exists() else "",
            "json": str(cfg.json_path) if cfg.json_path.exists() else "",
            "mapping": str(cfg.mapping_path) if cfg.mapping_path.exists() else "",
        },
    )
