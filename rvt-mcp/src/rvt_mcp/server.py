"""The FastMCP server: one object, every tool, resource and prompt attached."""

from __future__ import annotations

from fastmcp import FastMCP

from . import prompts, resources
from .tools import register_all

__all__ = ["build_server", "mcp"]

INSTRUCTIONS = """\
Read Autodesk Revit files (.rvt, .rfa, .rte, .rft) without Revit.

Start with rvt_open: it parses the file once and returns a handle the other
tools reuse. Then rvt_metadata and rvt_inspect say what the file is and what it
can yield before you export anything.

Two rules the tools enforce and the answers should respect:
- Element and geometry coverage depends on the Revit release (2023-2025 is
  validated; 2015-2022 and 2026-2027 are experimental). A file that decodes to
  zero elements still exports a valid but empty scaffold: say so instead of
  calling it a model.
- Exports go to files. A tool returns a path, a size and a checksum, never the
  contents, so a large model cannot flood the conversation.
"""


def build_server() -> FastMCP:
    """Build the server, registering every domain module."""
    server = FastMCP(
        name="rvt-mcp",
        instructions=INSTRUCTIONS,
        mask_error_details=False,
        strict_input_validation=True,
    )
    register_all(server)
    resources.register(server)
    prompts.register(server)
    return server


mcp = build_server()
