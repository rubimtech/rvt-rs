"""Helpers shared by the tool modules."""

from __future__ import annotations

import contextlib
from typing import Any, Iterator

from ..config import get_settings
from ..errors import fail
from ..handles import Entry, registry

__all__ = [
    "FEET_TO_METRES",
    "METRES_TO_FEET",
    "entry_for",
    "guard",
    "limits_for",
    "open_entry",
    "units_for",
]

FEET_TO_METRES = 0.3048
METRES_TO_FEET = 1.0 / 0.3048

# The CLIs' `--large-model` preset: 2 GiB per stream, 8 GiB inflated.
_LARGE_STREAM_BYTES = 2 * 1024**3
_LARGE_INFLATE_BYTES = 8 * 1024**3


def limits_for(large_model: bool | None = None) -> dict[str, Any]:
    """The `RevitFile` limits a tool opens with."""
    settings = get_settings()
    large = settings.default_large_model if large_model is None else large_model
    limits: dict[str, Any] = {}
    if large:
        limits["max_stream_bytes"] = _LARGE_STREAM_BYTES
        limits["max_inflate_bytes"] = _LARGE_INFLATE_BYTES
    if settings.max_stream_bytes is not None:
        limits["max_stream_bytes"] = settings.max_stream_bytes
    if settings.max_inflate_bytes is not None:
        limits["max_inflate_bytes"] = settings.max_inflate_bytes
    return limits


def open_entry(path: str, large_model: bool | None = None) -> Entry:
    settings = get_settings()
    large = settings.default_large_model if large_model is None else large_model
    return registry.open(path, limits=limits_for(large), large_model=large)


def entry_for(handle: str | None, path: str | None) -> Entry:
    """Resolve `handle` or `path` — exactly one of them — to an open entry."""
    if handle and path:
        fail(
            "ambiguous_target",
            "pass either `handle` or `path`, not both",
            hint="a handle keeps the parsed file in memory; a path reopens it",
        )
    if handle:
        return registry.get(handle)
    if path:
        return open_entry(path)
    fail(
        "missing_target",
        "no file given",
        hint="pass `handle` from rvt_open, or `path` to a .rvt/.rfa/.rte/.rft file",
    )


def units_for(metric: bool) -> tuple[str, float]:
    """The unit label and the factor that converts feet into it."""
    return ("metres", FEET_TO_METRES) if metric else ("feet", 1.0)


@contextlib.contextmanager
def guard(code: str, hint: str | None = None) -> Iterator[None]:
    """Turn a binding failure into a tool error with a stable code.

    The bindings raise `ValueError` for a file they cannot decode and `OSError`
    for one they cannot read; a caller needs those two distinguished from a bug
    in this server, and needs to know which operation failed.
    """
    try:
        yield
    except (ValueError, OSError) as exc:
        fail(code, str(exc).strip() or exc.__class__.__name__, hint=hint)
