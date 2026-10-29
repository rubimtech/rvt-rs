"""Tool registration.

Each module owns one domain and exposes a `register(mcp)` function; the server
imports them in a fixed order so the tool list is stable across runs.
"""

from __future__ import annotations

from . import compare, elements, export, geometry, metadata, session, write

__all__ = ["register_all"]


def register_all(mcp) -> None:
    for module in (session, metadata, elements, geometry, export, compare, write):
        module.register(mcp)
