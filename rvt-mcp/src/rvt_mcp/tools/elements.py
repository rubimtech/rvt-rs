"""Element and tabular-data tools: counts, pages, schedules, inventories."""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..adapters import cli
from ..envelope import Result, artifact_for, build
from ..errors import fail
from ..paths import resolve_output
from ._common import entry_for, guard

__all__ = ["register"]

HandleArg = Annotated[
    str | None, Field(description="Handle from rvt_open. Pass this or `path`.")
]
PathArg = Annotated[str | None, Field(description="File path. Pass this or `handle`.")]


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="rvt_counts",
        tags={"elements"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_counts(
        handle: HandleArg = None,
        path: PathArg = None,
        min_confidence: Annotated[
            float,
            Field(
                description="Drop elements decoded below this confidence.",
                ge=0.0,
                le=1.0,
            ),
        ] = 0.0,
    ) -> Result:
        """How many building elements the file yields, by class.

        The cheapest answer to "is there anything in here": a total near zero
        means the walker found no validated elements and every export will be a
        scaffold.
        """
        entry = entry_for(handle, path)
        with guard(
            "counts_failed", "the element walk failed; try rvt_inspect"
        ), entry.lock:
            counts = dict(entry.file.element_counts())
        if min_confidence > 0.0:
            with guard(
                "counts_failed", "the element walk failed; try rvt_inspect"
            ), entry.lock:
                elements = list(entry.file.decoded_elements())
            kept = [item for item in elements if _confidence(item) >= min_confidence]
            counts = {"total": len(kept), "by_class": _tally(kept)}
        return build("rvt_counts", handle=entry.handle, summary=counts)

    @mcp.tool(
        name="rvt_elements",
        tags={"elements"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_elements(
        handle: HandleArg = None,
        path: PathArg = None,
        categories: Annotated[
            list[str] | None,
            Field(
                description="Revit class names to keep, e.g. ['Wall','Floor']. Omit for all."
            ),
        ] = None,
        element_ids: Annotated[
            list[int] | None, Field(description="ElementIds to keep. Omit for all.")
        ] = None,
        min_confidence: Annotated[
            float,
            Field(
                description="Drop elements decoded below this confidence.",
                ge=0.0,
                le=1.0,
            ),
        ] = 0.0,
        typed: Annotated[
            bool,
            Field(
                description="Include the typed view (Wall, Floor, Door, Window, Room, Level, Material)."
            ),
        ] = True,
        offset: Annotated[
            int, Field(description="Index of the first element to return.", ge=0)
        ] = 0,
        limit: Annotated[int, Field(description="Page size.", ge=1, le=500)] = 25,
        sort: Annotated[str, Field(description="id, class or confidence.")] = "id",
    ) -> Result:
        """A page of decoded building elements.

        Each element carries its ElementId, Revit class, byte range, decoded
        fields, parameters, provenance and — for the classes with a typed view —
        the typed projection. Paginate: a real project has thousands.
        """
        entry = entry_for(handle, path)
        with guard(
            "elements_failed", "the element walk failed; try rvt_inspect"
        ), entry.lock:
            elements = list(entry.file.decoded_elements())
        rows = _filter(elements, categories, element_ids, min_confidence)
        rows = _sort(rows, sort)
        page = rows[offset : offset + limit]
        if not typed:
            page = [
                {key: value for key, value in row.items() if key != "typed"}
                for row in page
            ]
        summary = {
            "path": str(entry.path),
            "matched": len(rows),
            "returned": len(page),
            "offset": offset,
            "next_offset": offset + len(page)
            if offset + len(page) < len(rows)
            else None,
            "by_class": _tally(rows),
        }
        return build(
            "rvt_elements",
            handle=entry.handle,
            summary=summary,
            items=page,
            preview_limit=limit,
        )

    @mcp.tool(
        name="rvt_element",
        tags={"elements"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_element(
        handle: HandleArg = None,
        path: PathArg = None,
        element_id: Annotated[int, Field(description="Revit ElementId.", ge=1)] = 0,
    ) -> Result:
        """One element in full: fields, parameters, provenance and typed view.

        Use it after `rvt_counts` or `rvt_elements` named an id worth a closer
        look — a wall's location line, a door's host, a room's level.
        """
        if not element_id:
            fail(
                "missing_element_id",
                "no element_id given",
                hint="call rvt_elements to list ids",
            )
        entry = entry_for(handle, path)
        with guard(
            "elements_failed", "the element walk failed; try rvt_inspect"
        ), entry.lock:
            elements = list(entry.file.decoded_elements())
        for row in elements:
            if row.get("id") == element_id:
                return build(
                    "rvt_element",
                    handle=entry.handle,
                    summary={"path": str(entry.path), "element": row},
                )
        fail(
            "element_not_found",
            f"no decoded element with id {element_id}",
            hint="the id may exist in the file but not be decoded; try rvt_elem_table",
        )

    @mcp.tool(
        name="rvt_schedule",
        tags={"elements"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_schedule(
        handle: HandleArg = None,
        path: PathArg = None,
        kind: Annotated[str, Field(description="elements or rooms.")] = "elements",
        metric: Annotated[
            bool, Field(description="Lengths in metres instead of feet.")
        ] = False,
        excel: Annotated[
            bool,
            Field(description="Prefix a UTF-8 BOM so Excel reads non-ASCII names."),
        ] = False,
        out: Annotated[
            str | None, Field(description="CSV path. Omit to write next to the input.")
        ] = None,
        inline: Annotated[
            bool,
            Field(
                description="Return the first rows in the response instead of only a path."
            ),
        ] = True,
    ) -> Result:
        """A spreadsheet-ready CSV of every element, or of every room.

        Columns are type, level, material, placement, size and host for
        elements; number, name and level for rooms. Unknowns are empty cells,
        never guesses.
        """
        entry = entry_for(handle, path)
        if kind not in {"elements", "rooms"}:
            fail(
                "bad_schedule_kind",
                f"unknown schedule kind {kind!r}",
                hint="use elements or rooms",
            )
        with guard(
            "schedule_failed", "the model could not be decoded for a schedule"
        ), entry.lock:
            text = entry.file.schedule_csv(kind, metric, excel)
        target = resolve_output(
            out,
            default_name=f"{entry.path.stem}.{kind}.csv",
            source=entry.path,
        )
        target.write_text(text, encoding="utf-8")
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
        summary = {
            "kind": kind,
            "unit": "metres" if metric else "feet",
            "rows": max(0, len(rows) - 1),
            "columns": rows[0] if rows else [],
        }
        preview = [dict(zip(rows[0], row)) for row in rows[1:]] if len(rows) > 1 else []
        return build(
            "rvt_schedule",
            handle=entry.handle,
            summary=summary,
            items=preview if inline else None,
            artifact=artifact_for(target, "csv"),
        )

    @mcp.tool(
        name="rvt_inventory",
        tags={"elements"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_inventory(
        paths: Annotated[
            list[str], Field(description="Files and/or directories to inventory.")
        ],
        recurse: Annotated[bool, Field(description="Search subdirectories.")] = True,
        redact: Annotated[
            bool, Field(description="Scrub usernames and internal paths.")
        ] = True,
    ) -> Result:
        """One row per Revit file under a set of paths: release, save time, worksharing.

        The folder-audit tool: it reads only metadata, so a thousand files cost
        a thousand header parses rather than a thousand full decodes.
        """
        args = ["-f", "json"]
        if not recurse:
            args.append("--no-recurse")
        if redact:
            args.append("--redact")
        args.extend(paths)
        payload = cli.run_json("rvt-info", args)
        rows = payload if isinstance(payload, list) else payload.get("rows", [payload])
        return build("rvt_inventory", summary={"files": len(rows)}, items=rows)

    @mcp.tool(
        name="rvt_export_data",
        tags={"elements", "export"},
        annotations={"readOnlyHint": False, "openWorldHint": False},
    )
    def rvt_export_data(
        handle: HandleArg = None,
        path: PathArg = None,
        what: Annotated[
            str,
            Field(
                description="elements, counts, metadata, schema, history or elem_table."
            ),
        ] = "elements",
        format: Annotated[str, Field(description="json, jsonl or csv.")] = "json",
        out: Annotated[
            str | None,
            Field(description="Output path. Omit to write next to the input."),
        ] = None,
        categories: Annotated[
            list[str] | None,
            Field(description="Revit class names to keep (elements only)."),
        ] = None,
        element_ids: Annotated[
            list[int] | None, Field(description="ElementIds to keep (elements only).")
        ] = None,
        min_confidence: Annotated[
            float,
            Field(
                description="Drop elements decoded below this confidence.",
                ge=0.0,
                le=1.0,
            ),
        ] = 0.0,
        metric: Annotated[
            bool, Field(description="Metres instead of feet (csv schedules).")
        ] = False,
    ) -> Result:
        """Write a data dump to a file and report its path, size and checksum.

        The bulk counterpart of the read tools: a full element list is tens of
        megabytes, so it goes to disk and only a summary comes back. `format`
        picks JSON (one array), JSON Lines (one element per line, streamable) or
        CSV (schedules only).
        """
        entry = entry_for(handle, path)
        with guard("export_failed", "check rvt_inspect for what the file yields"):
            text, default_name, payload_summary = _dump(
                entry, what, format, categories, element_ids, min_confidence
            )
        if what == "history" and metric:
            payload_summary["metric"] = True
        target = resolve_output(out, default_name=default_name, source=entry.path)
        target.write_text(text, encoding="utf-8")
        return build(
            "rvt_export_data",
            handle=entry.handle,
            summary=payload_summary,
            artifact=artifact_for(target, _extension(format)),
        )


def _dump(
    entry,
    what: str,
    fmt: str,
    categories: list[str] | None,
    element_ids: list[int] | None,
    min_confidence: float,
) -> tuple[str, str, dict[str, Any]]:
    """Serialise one kind of dump and name the file it belongs in."""
    if what == "elements":
        with entry.lock:
            elements = list(entry.file.decoded_elements())
        rows = _filter(elements, categories, element_ids, min_confidence)
        return (
            _serialise(rows, fmt),
            f"{entry.path.stem}.elements.{_extension(fmt)}",
            {"what": what, "elements": len(rows)},
        )
    if what == "counts":
        with entry.lock:
            counts = dict(entry.file.element_counts())
        return (
            _serialise([counts], fmt),
            f"{entry.path.stem}.counts.{_extension(fmt)}",
            {"what": what, "total": counts.get("total")},
        )
    if what == "metadata":
        with entry.lock:
            meta = entry.file.metadata(True)
        return (
            _serialise([meta], fmt),
            f"{entry.path.stem}.metadata.{_extension(fmt)}",
            {"what": what},
        )
    if what == "schema":
        with entry.lock:
            text = entry.file.schema_json()
        return text, f"{entry.path.stem}.schema.json", {"what": what}
    if what == "history":
        payload = cli.run_json(
            "rvt-history", ["-f", "json", str(entry.path), "--redact"]
        )
        return (
            json.dumps(payload, indent=2, ensure_ascii=False),
            f"{entry.path.stem}.history.json",
            {"what": what},
        )
    if what == "elem_table":
        with entry.lock:
            header = dict(entry.file.elem_table_header())
            records = list(entry.file.elem_table_records())
        return (
            _serialise([{"header": header, "records": records}], fmt),
            f"{entry.path.stem}.elem-table.{_extension(fmt)}",
            {"what": what, "records": len(records)},
        )
    fail(
        "bad_export_kind",
        f"unknown export kind {what!r}",
        hint="use elements, counts, metadata, schema, history or elem_table",
    )


def _confidence(element: dict[str, Any]) -> float:
    provenance = element.get("provenance") or {}
    value = provenance.get("confidence")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _tally(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        name = row.get("class_name") or "unknown"
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _filter(
    rows: list[dict[str, Any]],
    categories: list[str] | None,
    element_ids: list[int] | None,
    min_confidence: float,
) -> list[dict[str, Any]]:
    wanted = {name.lower() for name in categories or []}
    ids = set(element_ids or [])
    out = []
    for row in rows:
        if wanted and str(row.get("class_name", "")).lower() not in wanted:
            continue
        if ids and row.get("id") not in ids:
            continue
        if min_confidence > 0.0 and _confidence(row) < min_confidence:
            continue
        out.append(row)
    return out


def _sort(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    if key == "id":
        return sorted(rows, key=lambda row: row.get("id") or 0)
    if key == "class":
        return sorted(
            rows, key=lambda row: (str(row.get("class_name")), row.get("id") or 0)
        )
    if key == "confidence":
        return sorted(rows, key=_confidence, reverse=True)
    fail("bad_sort", f"unknown sort key {key!r}", hint="use id, class or confidence")


def _serialise(rows: list[dict[str, Any]], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False)
    if fmt == "jsonl":
        return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    if fmt == "csv":
        return _to_csv(rows)
    fail("bad_format", f"unknown format {fmt!r}", hint="use json, jsonl or csv")


def _extension(fmt: str) -> str:
    return {"json": "json", "jsonl": "jsonl", "csv": "csv"}.get(fmt, "json")


def _to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _cell(row.get(key)) for key in columns})
    return buffer.getvalue()


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value
