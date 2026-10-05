"""Read-only reader for MATLAB v7.3 (HDF5) files.

Stage 1 writes ``stage1_output.mat`` with ``-v7.3``, so it is an HDF5 file
rather than the older MAT-binary format. The two structures that matter here:

* MATLAB numeric arrays are stored transposed and column-major, so a 1xN
  MATLAB row lands in HDF5 with shape ``(1, N)``. Every signal in the Stage 1
  export is one-dimensional, so :func:`as_series` ravels it back.
* MATLAB ``char`` rows are ``uint16`` code points; ``string``/``cell`` values
  are ``object`` arrays holding HDF5 references, sometimes nested inside
  another ``object`` array.

Nothing in this module writes to disk; Stage 1 artefacts are read-only inputs.
"""

from __future__ import annotations

from typing import Any

import h5py
import numpy as np

_MAX_REF_DEPTH = 8


_HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
_MATLAB_MARKER = b"MATLAB 7.3 MAT-file"
#: MATLAB v7.3 prefixes the HDF5 stream with a text user block whose size is not
#: fixed across releases (128 bytes here is not guaranteed; this export uses
#: 512). Scan a window instead of assuming a layout.
_USER_BLOCK_SCAN_BYTES = 8192


def is_v73(path: str) -> bool:
    """True when *path* is a MAT v7.3 (HDF5) file.

    MATLAB writes an ASCII ``MATLAB 7.3 MAT-file`` user block ahead of the HDF5
    stream, and the block size varies between releases, so the HDF5 signature is
    searched for within a window rather than at a fixed offset.
    """
    with open(path, "rb") as fh:
        head = fh.read(_USER_BLOCK_SCAN_BYTES)
    return _HDF5_SIGNATURE in head


def _attr(node: Any, name: str) -> bytes | None:
    """Read an h5py attribute as bytes, or ``None`` if it is absent."""
    attrs = getattr(node, "attrs", None)
    if attrs is None or name not in attrs:
        return None
    value = attrs[name]
    return value.tobytes() if isinstance(value, (bytes, np.bytes_)) else str(value).encode()


def is_logical(node: Any) -> bool:
    """True when *node* is a MATLAB ``logical``.

    MATLAB stores a logical scalar as a ``uint8`` tagged ``MATLAB_class =
    'logical'``, so dtype alone is ambiguous: a plain ``uint8`` and a logical are
    the same underlying type. Decoding one as text yields ``"\\x01"``, which
    silently defeats every ``isinstance(value, bool)`` test downstream.
    """
    return _attr(node, "MATLAB_class") == b"logical"


def decode_text(dataset: h5py.Dataset | np.ndarray) -> str:
    """Decode a MATLAB ``char`` row or ``string`` scalar into ``str``.

    MATLAB stores characters as unsigned integers, so the dtype is the only
    reliable way to tell text apart from a number: a genuine numeric scalar in
    this file is ``float64``, never ``uint16``.
    """
    arr = np.asarray(dataset)
    if arr.dtype.kind in "ui":
        return "".join(chr(int(c)) for c in arr.ravel())
    if arr.dtype.kind == "f":
        return str(arr.ravel()[0])
    return str(arr.ravel()[0])


def _resolve(node: Any, handle: h5py.File, depth: int = 0) -> Any:
    """Follow one level of object-array reference indirection."""
    if depth > _MAX_REF_DEPTH:
        raise RecursionError("MATLAB reference chain too deep to decode")
    if isinstance(node, h5py.Reference):
        return handle[node]
    if isinstance(node, np.ndarray) and node.dtype == object and node.size:
        return _resolve(node.ravel()[0], handle, depth + 1)
    return node


def decode_value(dataset: h5py.Dataset, handle: h5py.File) -> Any:
    """Decode a dataset into a plain Python value.

    Returns ``str`` for character data, ``float`` for scalars, ``bool`` for
    MATLAB logicals, and ``list`` for numeric vectors. Object arrays are
    resolved recursively so that a cell of strings decodes to a list of strings.

    Two MATLAB conventions need the ``MATLAB_class`` attribute rather than the
    dtype: ``logical`` is a tagged ``uint8`` and must not become the string
    ``"\\x01"``, and an empty ``char`` is stored as a two-null placeholder that
    must decode to ``""`` rather than ``"\\x00\\x00"``.
    """
    arr = np.asarray(dataset)

    if arr.dtype == object:
        out = []
        for item in arr.ravel():
            target = _resolve(item, handle)
            if isinstance(target, h5py.Dataset):
                out.append(decode_value(target, handle))
            elif isinstance(target, h5py.Group):
                out.append(flatten_group(target))
            else:
                out.append(target)
        if len(out) == 1:
            return out[0]
        return out

    if is_logical(dataset):
        flat = arr.ravel()
        return bool(int(flat[0])) if flat.size == 1 else [bool(int(v)) for v in flat]

    if _attr(dataset, "MATLAB_class") == b"char" and "MATLAB_empty" in getattr(dataset, "attrs", {}):
        return ""

    if arr.dtype.kind in "ui":
        return decode_text(arr)
    if arr.dtype.kind == "b":
        return arr.ravel()[0].item() if arr.size == 1 else arr.ravel().tolist()
    if arr.dtype.kind in "fi":
        flat = arr.ravel()
        return float(flat[0]) if flat.size == 1 else flat.tolist()
    return arr.tolist()


def as_series(dataset: h5py.Dataset) -> np.ndarray:
    """Return a one-dimensional float64 view of a MATLAB array."""
    arr = np.asarray(dataset)
    return np.ascontiguousarray(arr.ravel(), dtype=np.float64)


def flatten_group(group: h5py.Group, prefix: str = "", handle: h5py.File | None = None) -> dict[str, Any]:
    """Flatten a nested MATLAB struct into dotted keys.

    ``p/dc/rds_on_typ_ohm`` becomes ``"dc.rds_on_typ_ohm"``. Dotted keys keep
    the result flat and trivially addressable without inventing a nested
    schema that MATLAB's on-disk layout does not guarantee.
    """
    handle = handle if handle is not None else group.file
    out: dict[str, Any] = {}
    for key in group:
        node = group[key]
        full = f"{prefix}{key}"
        if isinstance(node, h5py.Group):
            out.update(flatten_group(node, f"{full}.", handle))
        else:
            out[full] = decode_value(node, handle)
    return out


def nested_section(flat: dict[str, Any], section: str) -> dict[str, Any]:
    """Re-nest one section of a flattened struct, the inverse of flattening.

    ``report.dataset_defects.qg_detail`` in a flat dict becomes
    ``{"qg_detail": ...}`` under ``section="dataset_defects"``. Without this a
    plain ``.get("dataset_defects")`` returns ``{}``, which reads exactly like
    "the file recorded no defects" when in fact the keys were only renamed.
    """
    prefix = f"{section}."
    out: dict[str, Any] = {}
    for key, value in flat.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix) :].split(".")
        node = out
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return out
