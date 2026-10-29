"""MCP resources: the model's facts as readable documents, not tool calls.

A resource is the right shape for "show me the metadata of this file" and
"what does the inspect contract look like": the client can read it into context
without a tool round-trip, and the URI names the thing rather than describing an
action.
"""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

from .adapters import cli
from .config import get_settings
from .errors import fail
from .handles import registry

__all__ = ["register"]


def register(mcp: FastMCP) -> None:
    @mcp.resource("rvt://open", name="Open files", mime_type="application/json")
    def open_files() -> str:
        """The files currently held open, with their handles."""
        return json.dumps(registry.snapshot(), indent=2, ensure_ascii=False)

    @mcp.resource(
        "rvt://file/{handle}/metadata",
        name="File metadata",
        mime_type="application/json",
    )
    def file_metadata(handle: str) -> str:
        """Document identity of an open file: release, build, last save, GUID."""
        entry = registry.get(handle)
        with entry.lock:
            return json.dumps(entry.file.metadata(True), indent=2, ensure_ascii=False)

    @mcp.resource(
        "rvt://file/{handle}/summary", name="File summary", mime_type="application/json"
    )
    def file_summary(handle: str) -> str:
        """Stream inventory, schema summary and element counts of an open file."""
        entry = registry.get(handle)
        with entry.lock:
            summary: dict[str, Any] = {
                "path": str(entry.path),
                "version": entry.version,
                "build": entry.file.build,
                "guid": entry.file.guid,
                "title": entry.file.part_atom_title,
                "streams": list(entry.file.stream_names()),
                "missing_required_streams": list(entry.file.missing_required_streams()),
                "unread_streams": list(entry.file.unread_streams()),
                "schema": dict(entry.file.schema_summary()),
                "element_counts": dict(entry.file.element_counts()),
            }
        return json.dumps(summary, indent=2, ensure_ascii=False)

    @mcp.resource(
        "rvt://file/{handle}/streams",
        name="Stream inventory",
        mime_type="application/json",
    )
    def file_streams(handle: str) -> str:
        """Every stream in the container, and the ones a limit kept from being read."""
        entry = registry.get(handle)
        with entry.lock:
            payload = {
                "streams": list(entry.file.stream_names()),
                "unread": list(entry.file.unread_streams()),
                "missing_required": list(entry.file.missing_required_streams()),
            }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @mcp.resource(
        "rvt://file/{handle}/schema/{class_name}",
        name="Class schema",
        mime_type="application/json",
    )
    def class_schema(handle: str, class_name: str) -> str:
        """One class's fields from the embedded schema."""
        entry = registry.get(handle)
        with entry.lock:
            table = json.loads(entry.file.schema_json())
        for row in table.get("classes", []):
            if row.get("name") == class_name:
                return json.dumps(row, indent=2, ensure_ascii=False)
        fail(
            "class_not_found",
            f"no class named {class_name!r} in this file's schema",
            hint="read rvt://file/<handle>/summary, or call rvt_schema with a grep term",
        )

    @mcp.resource(
        "rvt://file/{handle}/elements/{element_id}",
        name="Element",
        mime_type="application/json",
    )
    def element(handle: str, element_id: str) -> str:
        """One decoded element by ElementId."""
        entry = registry.get(handle)
        try:
            wanted = int(element_id)
        except ValueError:
            fail("bad_element_id", f"{element_id!r} is not an ElementId")
        with entry.lock:
            rows = list(entry.file.decoded_elements())
        for row in rows:
            if row.get("id") == wanted:
                return json.dumps(row, indent=2, ensure_ascii=False)
        fail("element_not_found", f"no decoded element with id {wanted}")

    @mcp.resource(
        "rvt://file/{handle}/preview.png", name="Preview", mime_type="image/png"
    )
    def preview(handle: str) -> Image:
        """The embedded thumbnail."""
        entry = registry.get(handle)
        with entry.lock:
            png = bytes(entry.file.preview_png())
        if not png:
            fail("no_preview", "this file carries no preview image")
        return Image(data=png, format="png")

    @mcp.resource(
        "rvt://capabilities", name="Support matrix", mime_type="application/json"
    )
    def capabilities() -> str:
        """What the toolkit supports, per Revit release."""
        if cli.available("rvt-capabilities"):
            return json.dumps(
                cli.run_json("rvt-capabilities", ["-f", "json", "--all"]),
                indent=2,
                ensure_ascii=False,
            )
        repo = get_settings().repo_path
        matrix = repo / "docs" / "support-matrix.json" if repo is not None else None
        if matrix is not None and matrix.is_file():
            return matrix.read_text(encoding="utf-8")
        fail(
            "capabilities_unavailable",
            "no rvt-capabilities CLI and no docs/support-matrix.json",
        )

    @mcp.resource(
        "rvt://contracts/{name}", name="JSON contract", mime_type="application/json"
    )
    def contract(name: str) -> str:
        """A published JSON schema contract (`docs/schemas/<name>.schema.json`)."""
        repo = get_settings().repo_path
        if repo is None:
            fail("contracts_unavailable", "RVT_MCP_REPO_ROOT is not set")
        path = (
            repo
            / "docs"
            / "schemas"
            / f"{name.removesuffix('.schema.json')}.schema.json"
        )
        if not path.is_file():
            fail(
                "contract_not_found",
                f"no contract named {name!r}",
                hint=f"look in {repo / 'docs' / 'schemas'}",
            )
        return path.read_text(encoding="utf-8")
