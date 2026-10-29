"""MCP server exposing the `rvt` toolkit over the Model Context Protocol.

The package is a thin protocol layer: parsing, element decoding and every
writer live in the Rust `rvt` crate, reached either in-process through the
`rvt` Python wheel (the fast path) or through the shipped CLIs (the full-
featured path). Nothing here re-implements a file format.
"""

from __future__ import annotations

__all__ = ["__version__", "build_server", "mcp"]

__version__ = "0.1.0"


def __getattr__(name: str):
    # Importing the server at package import time would make `rvt_mcp.config`
    # unusable from a plain interpreter run; resolve it on first use instead.
    if name in {"build_server", "mcp"}:
        from . import server

        return getattr(server, name)
    raise AttributeError(name)
