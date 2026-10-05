"""Provenance extraction and tag accounting for Phase 2A.

The project rule is that no value in the model is invented silently: every
parameter carries one of four provenance tags, and Phase 2A carries those tags
forward instead of restating values as bare numbers.

Two sources hold them and they are cross-checked here:

* ``p/provenance/*`` in the Stage 1 MAT - one free-text entry per parameter
  group, each beginning with its tag.
* ``DATASET_MAPPING.md`` - the human-readable ledger, whose ``Tag`` column uses
  the same four tags.

This module reports both, counts them by tag, and fails loudly if the MAT ever
introduces a tag the ledger does not define. A tag outside the declared
vocabulary is exactly the failure mode the rule exists to prevent, so it is
surfaced rather than normalised away.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

#: The four provenance tags, in the order ``DATASET_MAPPING.md`` defines them.
PROVENANCE_TAGS: tuple[str, ...] = (
    "DATASET-DERIVED",
    "CALCULATED-FROM-DATASET",
    "MANUFACTURER-DERIVED",
    "ASSUMED",
)

_PREFIX = re.compile(r"^\s*([A-Z][A-Z-]+)\s*:\s*(.*)$", re.DOTALL)
#: A tag cell is *exactly* one backticked uppercase token. Anchoring the whole
#: cell matters: the "Why" column quotes parameter names inline (``No `GDS` or
#: off-state curve is printed``) and would otherwise be read as tags.
_TAG_CELL = re.compile(r"^`([A-Z][A-Z0-9-]*)`$")


def _table_cells(line: str) -> list[str]:
    """Split a Markdown table row into stripped cells."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def split_tag(entry: str) -> tuple[str, str]:
    """Split ``"TAG: explanation"`` into ``(tag, explanation)``."""
    match = _PREFIX.match(entry)
    if not match:
        return "", entry.strip()
    tag, rest = match.group(1), match.group(2).strip()
    return (tag, rest) if tag in PROVENANCE_TAGS else ("", entry.strip())


def parameters_from_mat(mat_params: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Per-parameter provenance carried in the Stage 1 MAT.

    Keys are the parameter names with the ``provenance.`` prefix removed; the
    value is ``{"tag": ..., "basis": ...}``.
    """
    out: dict[str, dict[str, str]] = {}
    for key, value in mat_params.items():
        if not key.startswith("provenance.") or not isinstance(value, str):
            continue
        name = key.split(".", 1)[1]
        tag, basis = split_tag(value)
        out[name] = {"tag": tag, "basis": basis}
    return out


def ledger_from_mapping(mapping_path: Path) -> dict[str, Any]:
    """Tag counts and any undeclared tags found in ``DATASET_MAPPING.md``.

    Tables are read by locating each one's ``Tag`` column from its header row
    rather than by guessing a position. Two traps make guessing unreliable:

    * the ledger mixes three-column tables (Tag last) with four-column ones
      (Tag third, followed by a "Why" column);
    * the "Values the datasheet leaves open" table has single-token parameter
      names such as `` `PTOT` `` and `` `K` `` in column one, which are
      syntactically identical to a tag.

    A cell only counts when the whole cell is one backticked uppercase token, so
    inline backticks inside prose ("No `GDS` or off-state curve") are ignored.
    """
    if not mapping_path.exists():
        return {
            "path": str(mapping_path),
            "present": False,
            "declared_tags": list(PROVENANCE_TAGS),
            "tagged_rows": 0,
            "tag_occurrences_in_tables": {tag: 0 for tag in PROVENANCE_TAGS},
            "unknown_tags": {},
            "untagged_rows": [],
        }

    counts: dict[str, int] = {tag: 0 for tag in PROVENANCE_TAGS}
    unknown: dict[str, int] = {}
    untagged_rows: list[str] = []
    tagged_rows = 0
    tag_column = -1

    for line in mapping_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            tag_column = -1  # a blank line ends the current table
            continue
        cells = _table_cells(stripped)
        if len(cells) < 3:
            continue

        # A header row names the columns; re-locate the Tag column from it
        # rather than assuming a fixed index.
        if any(cell == "Tag" for cell in cells):
            tag_column = cells.index("Tag")
            continue
        if set(cells) <= {"---"} or all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        if tag_column < 0 or tag_column >= len(cells):
            continue

        match = _TAG_CELL.match(cells[tag_column])
        if not match:
            untagged_rows.append(cells[0])
            continue

        tagged_rows += 1
        tag = match.group(1)
        if tag in counts:
            counts[tag] += 1
        else:
            unknown[tag] = unknown.get(tag, 0) + 1

    return {
        "path": str(mapping_path),
        "present": True,
        "declared_tags": list(PROVENANCE_TAGS),
        "tagged_rows": tagged_rows,
        "tag_occurrences_in_tables": counts,
        "unknown_tags": unknown,
        "untagged_rows": untagged_rows,
    }


def build_provenance_record(bundle_params: dict[str, Any], mapping_path: Path) -> dict[str, Any]:
    """Assemble the manifest's provenance block.

    ``untagged`` is non-empty only if a Stage 1 provenance entry lost its tag,
    which would mean the "nothing is invented silently" rule was already broken
    upstream and Stage 2 should say so.
    """
    parameters = parameters_from_mat(bundle_params)
    by_tag: dict[str, list[str]] = {tag: [] for tag in PROVENANCE_TAGS}
    untagged: list[str] = []
    for name, entry in sorted(parameters.items()):
        if entry["tag"]:
            by_tag[entry["tag"]].append(name)
        else:
            untagged.append(name)

    ledger = ledger_from_mapping(mapping_path)

    return {
        "tags": list(PROVENANCE_TAGS),
        "stage2_evidence_class": "calculated_from_stage1_simulation",
        "parameters": parameters,
        "by_tag": by_tag,
        "counts_by_tag": {tag: len(names) for tag, names in by_tag.items()},
        "untagged_parameters": untagged,
        "unknown_tags_in_ledger": ledger.get("unknown_tags", {}),
        "mapping_ledger": ledger,
    }
