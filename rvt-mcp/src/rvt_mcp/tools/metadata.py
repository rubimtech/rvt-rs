"""Metadata and inspection tools: what a file is, and what is inside it."""

from __future__ import annotations

import base64
import json
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pydantic import Field

from ..adapters import cli
from ..envelope import Result, build
from ..errors import fail
from ._common import entry_for

__all__ = ["register"]

HandleArg = Annotated[
    str | None, Field(description="Handle from rvt_open. Pass this or `path`.")
]
PathArg = Annotated[str | None, Field(description="File path. Pass this or `handle`.")]
RedactArg = Annotated[
    bool,
    Field(
        description="Scrub usernames, Autodesk-internal paths and project-ID folders from the output."
    ),
]


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="rvt_metadata",
        tags={"metadata"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_metadata(
        handle: HandleArg = None, path: PathArg = None, redact: RedactArg = True
    ) -> Result:
        """Document identity: Revit release, build, last save, worksharing state, GUID.

        The first call to make on an unfamiliar file: it answers "which Revit
        version is this, who saved it, is it workshared, is it a backup copy"
        without decoding any element.
        """
        entry = entry_for(handle, path)
        with entry.lock:
            metadata = _json_or_none(entry.file, "metadata", redact=redact)
            basic = _json_text(entry.file.basic_file_info_json())
            part_atom = _json_text(entry.file.part_atom_json())
        summary = {
            "path": str(entry.path),
            "file": metadata,
            "basic_file_info": basic,
            "part_atom": part_atom,
        }
        return build("rvt_metadata", handle=entry.handle, summary=summary)

    @mcp.tool(
        name="rvt_inspect",
        tags={"metadata"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_inspect(
        handle: HandleArg = None, path: PathArg = None, redact: RedactArg = True
    ) -> Result:
        """File health and export readiness in one report.

        Composes the checks that decide whether an export is worth attempting:
        release, missing streams, schema quality, decoded element counts and the
        resource limits that were hit. Use it before `rvt_export_ifc` to know
        whether to expect real geometry or a scaffold.
        """
        entry = entry_for(handle, path)
        with entry.lock:
            file = entry.file
            summary: dict[str, Any] = {
                "path": str(entry.path),
                "version": entry.version,
                "build": file.build,
                "missing_required_streams": list(file.missing_required_streams()),
                "unread_streams": list(file.unread_streams()),
                "stream_count": len(file.stream_names()),
            }
            try:
                summary["schema"] = dict(file.schema_diagnostics())
            except (ValueError, OSError) as exc:
                summary["schema"] = {"error": str(exc)}
            try:
                summary["element_counts"] = dict(file.element_counts())
            except (ValueError, OSError) as exc:
                summary["element_counts"] = {"error": str(exc)}
            if redact:
                summary["redacted"] = True
        warnings = _readiness_warnings(summary)
        return build(
            "rvt_inspect", handle=entry.handle, summary=summary, warnings=warnings
        )

    @mcp.tool(
        name="rvt_schema",
        tags={"metadata"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_schema(
        handle: HandleArg = None,
        path: PathArg = None,
        grep: Annotated[
            str | None,
            Field(
                description="Only classes whose name contains this substring (case-sensitive)."
            ),
        ] = None,
        with_fields: Annotated[
            bool, Field(description="Only classes that declare at least one field.")
        ] = False,
        top: Annotated[
            int | None,
            Field(description="Keep the N classes with the most fields.", ge=1),
        ] = None,
        diagnostics: Annotated[
            bool,
            Field(
                description="Return the schema-quality counters instead of the class table."
            ),
        ] = False,
    ) -> Result:
        """The class schema embedded in the file (4,000+ classes on a 2024 project).

        Filter it: the full table is megabytes. `grep` narrows by class name,
        `top` ranks by field count, and `diagnostics` answers "is this schema
        complete" with counters instead of rows.
        """
        entry = entry_for(handle, path)
        try:
            with entry.lock:
                if diagnostics:
                    return build(
                        "rvt_schema",
                        handle=entry.handle,
                        summary=dict(entry.file.schema_diagnostics()),
                    )
                table = json.loads(entry.file.schema_json())
                summary = dict(entry.file.schema_summary())
        except (ValueError, OSError) as exc:
            fail(
                "schema_unavailable",
                f"the embedded schema could not be read: {exc}",
                hint="the file may be a synthetic or truncated container",
            )
        classes = table.get("classes", [])
        if grep:
            classes = [row for row in classes if grep in row.get("name", "")]
        if with_fields:
            classes = [row for row in classes if row.get("fields")]
        if top:
            classes = sorted(
                classes, key=lambda row: len(row.get("fields", [])), reverse=True
            )[:top]
        summary.update(
            {
                "class_count": len(table.get("classes", [])),
                "matched_classes": len(classes),
                "scanned_bytes": table.get("scanned_bytes"),
                "total_bytes": table.get("total_bytes"),
                "scan_truncated": table.get("scan_truncated"),
                "skipped_records": table.get("skipped_records"),
            }
        )
        return build("rvt_schema", handle=entry.handle, summary=summary, items=classes)

    @mcp.tool(
        name="rvt_history",
        tags={"metadata"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_history(
        handle: HandleArg = None,
        path: PathArg = None,
        partitions: Annotated[
            bool,
            Field(
                description="Also scan the version-specific partition stream for category, OmniClass and Uniformat strings."
            ),
        ] = False,
        redact: RedactArg = True,
    ) -> Result:
        """Which Revit releases have opened this file, and the strings they left.

        The upgrade timeline shows the file's age; `partitions=True` adds the
        bulk UTF-16 strings (categories, classification codes, unit identifiers)
        from the version-specific partition.
        """
        entry = entry_for(handle, path)
        args = ["-f", "json", str(entry.path)]
        if partitions:
            args.append("--partitions")
        if redact:
            args.append("--redact")
        payload = cli.run_json("rvt-history", args)
        return build(
            "rvt_history",
            handle=entry.handle,
            summary={"source": "rvt-history", "history": payload},
        )

    @mcp.tool(
        name="rvt_elem_table",
        tags={"metadata"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_elem_table(
        handle: HandleArg = None,
        path: PathArg = None,
        limit: Annotated[
            int, Field(description="How many records to return.", ge=1, le=10_000)
        ] = 50,
    ) -> Result:
        """The Global/ElemTable: declared element ids and their record layout.

        Answers "how many elements does the file claim to have, and at which
        offset is each record" — the starting point when a decode misses
        elements that the file says are there.
        """
        entry = entry_for(handle, path)
        try:
            with entry.lock:
                header = dict(entry.file.elem_table_header())
                records = list(entry.file.elem_table_records())
                declared = list(entry.file.declared_element_ids())[:limit]
        except (ValueError, OSError) as exc:
            fail(
                "elem_table_unavailable",
                f"the element table could not be read: {exc}",
                hint="the stream may be synthetic or truncated; try rvt_streams",
            )
        summary = {
            **header,
            "declared_element_ids": declared,
        }
        return build(
            "rvt_elem_table",
            handle=entry.handle,
            summary=summary,
            items=records,
            preview_limit=limit,
        )

    @mcp.tool(
        name="rvt_document",
        tags={"metadata"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_document(handle: HandleArg = None, path: PathArg = None) -> Result:
        """The ADocument instance fields, as the walker reads them.

        A low-level view of the document object: useful when a file opens but
        the element walk finds nothing, to see whether the document record
        itself was recognised.
        """
        entry = entry_for(handle, path)
        try:
            with entry.lock:
                document = entry.file.read_adocument()
        except (ValueError, OSError) as exc:
            fail(
                "adocument_unavailable",
                f"the document record could not be read: {exc}",
                hint="the file may be a synthetic or truncated container",
            )
        if document is None:
            fail(
                "adocument_not_found",
                "no ADocument record was found in this file",
                hint="try rvt_streams and rvt_stream_read on the partition stream",
            )
        return build(
            "rvt_document",
            handle=entry.handle,
            summary={"path": str(entry.path), "adocument": document},
        )

    @mcp.tool(
        name="rvt_streams",
        tags={"metadata"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_streams(handle: HandleArg = None, path: PathArg = None) -> Result:
        """The container's stream inventory, and which ones were not read.

        `unread_streams` is the honest half: a stream listed there was skipped
        because of a resource limit, so any export is missing its contents.
        """
        entry = entry_for(handle, path)
        with entry.lock:
            names = list(entry.file.stream_names())
            unread = list(entry.file.unread_streams())
            missing = list(entry.file.missing_required_streams())
        summary = {
            "path": str(entry.path),
            "stream_count": len(names),
            "unread_count": len(unread),
            "missing_required": missing,
        }
        return build(
            "rvt_streams",
            handle=entry.handle,
            summary=summary,
            items=[{"name": name} for name in names],
            warnings=[f"{len(unread)} stream(s) were not read"] if unread else [],
        )

    @mcp.tool(
        name="rvt_stream_read",
        tags={"metadata"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_stream_read(
        handle: HandleArg = None,
        path: PathArg = None,
        name: Annotated[
            str,
            Field(
                description="Stream name exactly as rvt_streams reports it, e.g. 'BasicFileInfo'."
            ),
        ] = "",
        encoding: Annotated[
            str, Field(description="hex, text, utf16 or base64.")
        ] = "hex",
        offset: Annotated[
            int, Field(description="Byte offset into the stream.", ge=0)
        ] = 0,
        length: Annotated[
            int,
            Field(
                description="Bytes to read (capped by the response budget).",
                ge=1,
                le=1_048_576,
            ),
        ] = 4096,
    ) -> Result:
        """Read a window of one stream, as hex, text, UTF-16LE text or base64.

        The stream is returned from its start; the window is applied here, so
        paging through a large partition costs one read per page rather than
        one per byte range.
        """
        if not name:
            fail(
                "missing_stream_name",
                "no stream name given",
                hint="call rvt_streams for the names",
            )
        entry = entry_for(handle, path)
        with entry.lock:
            data = bytes(entry.file.read_stream(name))
        window = data[offset : offset + length]
        summary = {
            "stream": name,
            "stream_bytes": len(data),
            "offset": offset,
            "returned_bytes": len(window),
            "truncated": offset + length < len(data),
        }
        if encoding == "hex":
            summary["data"] = window.hex()
        elif encoding == "base64":
            summary["data"] = base64.b64encode(window).decode("ascii")
        elif encoding == "text":
            summary["data"] = window.decode("utf-8", errors="replace")
        elif encoding == "utf16":
            summary["data"] = window.decode("utf-16-le", errors="replace")
        else:
            fail(
                "bad_encoding",
                f"unknown encoding {encoding!r}",
                hint="use hex, text, utf16 or base64",
            )
        return build("rvt_stream_read", handle=entry.handle, summary=summary)

    @mcp.tool(
        name="rvt_preview",
        tags={"metadata"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_preview(handle: HandleArg = None, path: PathArg = None) -> Image:
        """The PNG thumbnail Revit embedded in the file.

        A visual sanity check that costs nothing: it is the image the file's own
        file dialog shows.
        """
        entry = entry_for(handle, path)
        with entry.lock:
            png = bytes(entry.file.preview_png())
        if not png:
            fail("no_preview", "this file carries no preview image")
        return Image(data=png, format="png")


def _json_text(value: str | None) -> Any:
    return json.loads(value) if value else None


def _json_or_none(entry_file: Any, method: str, **kwargs: Any) -> Any:
    try:
        return getattr(entry_file, method)(**kwargs)
    except (ValueError, OSError):
        return None


def _readiness_warnings(summary: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if summary.get("missing_required_streams"):
        warnings.append(
            "required streams are missing; the file is truncated or not a Revit container"
        )
    unread = summary.get("unread_streams") or []
    if unread:
        warnings.append(
            f"{len(unread)} stream(s) hit a resource limit; reopen with large_model=true"
        )
    counts = summary.get("element_counts") or {}
    if isinstance(counts, dict) and counts.get("total", 0) == 0:
        warnings.append("no building elements decoded: expect a scaffold-only export")
    version = summary.get("version")
    if isinstance(version, int) and not 2023 <= version <= 2025:
        warnings.append(
            f"Revit {version} is outside the validated 2023-2025 range; element geometry may be missing"
        )
    return warnings
