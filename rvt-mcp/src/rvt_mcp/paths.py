"""Path policy: what the server may read, and where it may write.

A model can ask for any string, so every path crosses this module before it
reaches the filesystem. Reads are confined to `RVT_MCP_ROOTS`; writes are
confined to `RVT_MCP_OUTPUT_DIR` (or the first root); and an export never
overwrites its own input.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .config import get_settings
from .errors import fail

__all__ = [
    "REVIT_SUFFIXES",
    "resolve_input",
    "resolve_output",
    "sha256_file",
    "sha256_bytes",
]

REVIT_SUFFIXES = frozenset({".rvt", ".rfa", ".rte", ".rft"})


def _settings():
    return get_settings()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _confined(path: Path, roots: list[Path]) -> bool:
    return any(_is_within(path, root) for root in roots)


def resolve_input(raw: str | os.PathLike[str]) -> Path:
    """Resolve a path a tool was asked to read, or refuse it.

    The check runs on the resolved (symlink-free) path, so `..` and a symlink
    pointing outside the allowlist are both rejected.
    """
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = _settings().root_paths[0] / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        fail("file_not_found", f"no such file: {raw}")
    if not resolved.is_file():
        fail("not_a_file", f"not a regular file: {resolved}")
    roots = _settings().root_paths
    if not _confined(resolved, roots):
        fail(
            "path_not_allowed",
            f"{resolved} is outside the readable roots",
            hint="add its directory to RVT_MCP_ROOTS",
        )
    return resolved


def resolve_output(
    raw: str | os.PathLike[str] | None,
    *,
    default_name: str,
    source: Path | None = None,
) -> Path:
    """Resolve where a tool writes an artifact, or refuse it.

    `source` is the file the artifact is derived from: exporting onto it would
    destroy the input, so that is refused even when the directory is allowed.
    """
    settings = _settings()
    root = settings.output_path
    if raw is None or str(raw) == "":
        candidate = root / default_name
    else:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.suffix == "" and Path(default_name).suffix:
            candidate = candidate.with_suffix(Path(default_name).suffix)

    parent = candidate.parent.resolve()
    if not _confined(parent, [root, *settings.root_paths]):
        fail(
            "output_not_allowed",
            f"{parent} is outside the writable directory",
            hint="write under RVT_MCP_OUTPUT_DIR or one of RVT_MCP_ROOTS",
        )
    if source is not None and candidate.resolve() == source.resolve():
        fail(
            "output_overwrites_input",
            f"{candidate} is the input file",
            hint="pass a different output path",
        )
    parent.mkdir(parents=True, exist_ok=True)
    return candidate


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
