"""Session tools: open, close, list, and what the toolkit supports."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..adapters import cli
from ..config import get_settings
from ..envelope import Result, build
from ..errors import fail
from ..handles import registry
from ._common import open_entry

__all__ = ["register"]

PathArg = Annotated[
    str,
    Field(
        description="Absolute path to a .rvt/.rfa/.rte/.rft file, or a path relative to the first readable root."
    ),
]
HandleArg = Annotated[
    str,
    Field(
        description="Handle returned by rvt_open; reuses the parsed file instead of reopening it."
    ),
]
LargeModelArg = Annotated[
    bool,
    Field(
        description="Open with the large-model limits (2 GiB per stream, 8 GiB inflated). Costs several GB of RAM."
    ),
]


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="rvt_open",
        tags={"session"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_open(path: PathArg, large_model: LargeModelArg = False) -> Result:
        """Open a Revit file and keep it parsed for later calls.

        Returns a handle plus what the file is: Revit release, build, document
        GUID, stream inventory and a schema summary. Opening is the expensive
        step, so prefer passing this handle to the other tools over a path.

        Reads only; the file is never modified.
        """
        entry = open_entry(path, large_model)
        warnings = []
        with entry.lock:
            file = entry.file
            missing = list(file.missing_required_streams())
            unread = list(file.unread_streams())
            streams = list(file.stream_names())
            try:
                schema = dict(file.schema_summary())
            except (ValueError, OSError):
                schema = {}
            summary: dict[str, Any] = {
                "path": str(entry.path),
                "version": entry.version,
                "build": file.build,
                "document_guid": file.guid,
                "title": file.part_atom_title,
                "stream_count": len(streams),
                "streams": streams[:40],
                "schema": schema,
                "large_model": entry.large_model,
            }
        if missing:
            warnings.append(f"required streams missing: {', '.join(missing)}")
        if unread:
            warnings.append(
                f"{len(unread)} stream(s) were not read because a resource limit was hit"
            )
        return build(
            "rvt_open", handle=entry.handle, summary=summary, warnings=warnings
        )

    @mcp.tool(
        name="rvt_close",
        tags={"session"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    )
    def rvt_close(handle: HandleArg) -> Result:
        """Forget an open file, freeing the memory its decoded partitions hold."""
        closed = registry.close(handle)
        if not closed:
            fail("unknown_handle", f"no open file with handle {handle!r}")
        return build("rvt_close", summary={"handle": handle, "closed": True})

    @mcp.tool(
        name="rvt_list_open",
        tags={"session"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_list_open() -> Result:
        """List the files currently held open, least recently used last."""
        entries = registry.snapshot()
        return build("rvt_list_open", items=entries, summary={"open": len(entries)})

    @mcp.tool(
        name="rvt_capabilities",
        tags={"session"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_capabilities(
        revit_version: Annotated[
            int | None,
            Field(
                description="Revit release to report on, e.g. 2024. Omit for the whole manifest."
            ),
        ] = None,
        full: Annotated[
            bool,
            Field(
                description="Return the complete support matrix instead of the summary."
            ),
        ] = False,
    ) -> Result:
        """What this toolkit can and cannot do, per Revit release.

        Use it before promising an export: element and geometry coverage depends
        on the release (2023-2025 is the validated range, 2015-2022 and
        2026-2027 are experimental), and a capability that is not `supported`
        still produces a valid but empty or approximated result.
        """
        settings = get_settings()
        args = ["-f", "json"]
        if full:
            args.append("--all")
        if cli.available("rvt-capabilities"):
            payload = cli.run_json("rvt-capabilities", args)
            summary: dict[str, Any] = {"source": "rvt-capabilities", "matrix": payload}
        else:
            repo = settings.repo_path
            matrix = repo / "docs" / "support-matrix.json" if repo is not None else None
            if matrix is None or not matrix.is_file():
                fail(
                    "capabilities_unavailable",
                    "neither the rvt-capabilities CLI nor docs/support-matrix.json was found",
                    hint="set RVT_MCP_REPO_ROOT to the repository, or build the CLIs",
                )
            summary = {
                "source": str(matrix),
                "matrix": json.loads(matrix.read_text(encoding="utf-8")),
            }
        if revit_version is not None:
            summary["revit_version"] = revit_version
            summary["release"] = _release_entry(summary["matrix"], revit_version)
        return build("rvt_capabilities", summary=summary)


def _release_entry(matrix: Any, version: int) -> Any:
    """The manifest's record for one release, when it carries one per release."""
    if not isinstance(matrix, dict):
        return None
    for key in ("releases", "release_support", "support"):
        section = matrix.get(key)
        if isinstance(section, dict):
            for candidate in (str(version), f"r{version}", f"revit-{version}"):
                if candidate in section:
                    return section[candidate]
        if isinstance(section, list):
            for row in section:
                if isinstance(row, dict) and row.get("version") in (
                    version,
                    str(version),
                ):
                    return row
    return None
