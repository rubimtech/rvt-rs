"""Comparison tools: two files, two IFC exports, or a whole folder."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..adapters import cli
from ..envelope import Result, artifact_for, build
from ..errors import fail
from ..paths import resolve_input, resolve_output

__all__ = ["register"]

PathArg = Annotated[
    str,
    Field(description="Absolute path, or a path relative to the first readable root."),
]


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="rvt_diff",
        tags={"compare"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_diff(
        paths: Annotated[
            list[str],
            Field(description="Two or more Revit files to compare, oldest first."),
        ],
        decompress: Annotated[
            bool,
            Field(
                description="Inflate each stream before comparing, so a recompressed stream still matches."
            ),
        ] = True,
        preview_bytes: Annotated[
            int,
            Field(
                description="Bytes of context around each differing region.",
                ge=0,
                le=256,
            ),
        ] = 32,
    ) -> Result:
        """Byte-level difference between two versions of the same file.

        Answers "what actually changed between these two saves" at the stream
        level: which streams differ, where, and by how much. Inflating first
        (`decompress`) is what makes a recompressed but unchanged stream show as
        identical.
        """
        if len(paths) < 2:
            fail(
                "too_few_files",
                "rvt_diff needs at least two files",
                hint="pass the old file and the new one",
            )
        resolved = [str(resolve_input(item)) for item in paths]
        args: list[str] = ["--preview", str(preview_bytes)]
        if decompress:
            args.append("--decompress")
        args.extend(resolved)
        result = cli.run("rvt-diff", args)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            fail(
                "diff_failed",
                detail[-1] if detail else f"exit status {result.returncode}",
            )
        return build(
            "rvt_diff",
            summary={
                "files": resolved,
                "decompress": decompress,
                "report": result.stdout.strip(),
            },
        )

    @mcp.tool(
        name="rvt_ifc_compare",
        tags={"compare"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_ifc_compare(
        left: Annotated[
            str, Field(description="IFC to check, typically an rvt-rs export.")
        ],
        right: Annotated[
            str, Field(description="Reference IFC, typically Revit's own export.")
        ],
        out: Annotated[
            str | None, Field(description="Keep the full JSON report at this path.")
        ] = None,
    ) -> Result:
        """Compare two IFC files: entity counts, storeys, objects, materials, bounding boxes.

        The evidence tool for "did our export match Revit's": it reports the
        deltas rather than a verdict, so the remaining gaps are visible instead
        of being averaged away.
        """
        left_path = resolve_input(left)
        right_path = resolve_input(right)
        with tempfile.TemporaryDirectory(prefix="rvt-mcp-") as tmp:
            report_path = Path(tmp) / "compare.json"
            result = cli.run(
                "rvt-ifc-compare",
                [
                    str(left_path),
                    str(right_path),
                    "--json",
                    str(report_path),
                    "--quiet",
                ],
            )
            # Exit 2 means "the files differ", which is the normal answer here.
            if result.returncode not in (0, 2):
                detail = (result.stderr or result.stdout).strip().splitlines()
                fail(
                    "compare_failed",
                    detail[-1] if detail else f"exit status {result.returncode}",
                )
            if not report_path.is_file():
                fail(
                    "compare_failed",
                    "rvt-ifc-compare wrote no report",
                    hint="run it by hand to see why",
                )
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        artifact = None
        if out is not None:
            target = resolve_output(
                out, default_name="ifc-compare.json", source=left_path
            )
            target.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            artifact = artifact_for(target, "json")
        differences = _differences(payload)
        return build(
            "rvt_ifc_compare",
            summary={
                "left": str(left_path),
                "right": str(right_path),
                "differences": differences,
            },
            artifact=artifact,
            warnings=(
                [f"the files differ in {len(differences)} area(s)"]
                if differences
                else []
            ),
        )

    @mcp.tool(
        name="rvt_corpus_doctor",
        tags={"compare"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_corpus_doctor(
        paths: Annotated[
            list[str],
            Field(
                description="Files or directories to triage; directories are scanned recursively."
            ),
        ],
    ) -> Result:
        """Triage a folder of files into failure buckets.

        For a library that "mostly works": it says which files fail for the same
        reason, so one fix covers many files. Directories are always searched
        recursively.
        """
        payload = cli.run_json("rvt-corpus", ["doctor", "-f", "json", *paths])
        buckets = payload.get("buckets", {}) if isinstance(payload, dict) else {}
        rows = [
            {
                "bucket": name,
                "files": value.get("files", value)
                if isinstance(value, dict)
                else value,
            }
            for name, value in buckets.items()
        ]
        return build(
            "rvt_corpus_doctor",
            summary={
                "buckets": _bucket_summary(payload),
                "files_scanned": payload.get("files_scanned")
                if isinstance(payload, dict)
                else None,
            },
            items=rows,
        )

    @mcp.tool(
        name="rvt_corpus",
        tags={"compare"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def rvt_corpus(
        paths: Annotated[
            list[str],
            Field(
                description="Three or more files of the same logical content across releases."
            ),
        ],
        runs: Annotated[
            int, Field(description="Invariant runs to report per stream.", ge=1, le=50)
        ] = 5,
    ) -> Result:
        """Cross-version analysis: what stays constant across releases, and what moves.

        The research tool: with the same model saved by several Revit versions it
        isolates the bytes that are format-invariant, which is how a decoder is
        checked against more than one release.
        """
        if len(paths) < 3:
            fail(
                "too_few_files",
                "rvt_corpus needs at least three files",
                hint="pass one file per Revit release",
            )
        payload = cli.run_json(
            "rvt-corpus", ["-f", "json", "--runs", str(runs), *paths]
        )
        return build(
            "rvt_corpus", summary={"files": len(paths), "runs": runs, "report": payload}
        )


def _differences(payload: Any) -> dict[str, Any]:
    """The non-empty parts of a comparison report.

    The report separates "only in the left file" lists from numeric deltas; both
    are reported as they are, because a count that moved and a member that
    disappeared are different problems.
    """
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"left", "right", "left_label", "right_label", "notes"}:
            continue
        if not _is_empty(value):
            out[key] = value
    return out


def _is_empty(value: Any) -> bool:
    """A delta is empty when every number in it is zero, however deeply nested."""
    if isinstance(value, dict):
        return all(_is_empty(item) for item in value.values())
    if isinstance(value, list):
        return all(_is_empty(item) for item in value)
    return value in (0, 0.0, None, "", False)


def _bucket_summary(payload: Any) -> dict[str, int]:
    """Bucket name to the number of files in it, whatever the bucket shape."""
    if not isinstance(payload, dict):
        return {}
    buckets = payload.get("buckets") or payload.get("failures") or {}
    if not isinstance(buckets, dict):
        return {}
    summary: dict[str, int] = {}
    for name, value in buckets.items():
        if isinstance(value, dict):
            count = value.get("count")
            files = value.get("files")
            summary[str(name)] = (
                int(count) if isinstance(count, int) else len(files or [])
            )
        elif isinstance(value, list):
            summary[str(name)] = len(value)
        elif isinstance(value, int):
            summary[str(name)] = value
    return summary
