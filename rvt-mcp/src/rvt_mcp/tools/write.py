"""The one tool that writes a Revit file.

It is registered only when `RVT_MCP_ALLOW_WRITE=1`: patching streams rewrites a
container, and an accidental call would be a data-loss incident rather than a
bad answer. `dry_run` validates the manifest without touching the source, so the
safe half of the tool is always available once it is enabled.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..adapters import cli
from ..config import get_settings
from ..envelope import Result, artifact_for, build
from ..errors import fail
from ..paths import resolve_input, resolve_output

__all__ = ["register"]


def register(mcp: FastMCP) -> None:
    if not get_settings().allow_write:
        return

    @mcp.tool(
        name="rvt_write_streams",
        tags={"write"},
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": False,
        },
    )
    def rvt_write_streams(
        src: Annotated[str, Field(description="Source Revit file. Never modified.")],
        dst: Annotated[str, Field(description="Destination file; written atomically.")],
        patches: Annotated[
            list[dict[str, Any]],
            Field(description="Entries of {stream, bytes_base64 | bytes | hex}."),
        ],
        dry_run: Annotated[
            bool,
            Field(description="Validate the manifest and the streams without writing."),
        ] = True,
    ) -> Result:
        """Replace named OLE streams and write a new Revit file.

        A stream-level write path: the rest of the container is copied
        byte-for-byte, so a patched file stays loadable where the patch is
        well-formed. Every other tool here is read-only; this one is the
        exception and is off unless the operator enabled it.
        """
        if not patches:
            fail(
                "no_patches",
                "no patch entries given",
                hint="each entry names a stream and its new bytes",
            )
        source = resolve_input(src)
        target = resolve_output(
            dst, default_name=f"{source.stem}.patched{source.suffix}", source=source
        )
        manifest = _manifest(patches)
        with tempfile.TemporaryDirectory(prefix="rvt-mcp-") as tmp:
            manifest_path = Path(tmp) / "patches.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            args = ["--src", str(source), "--patches", str(manifest_path), "--verify"]
            if dry_run:
                args.append("--dry-run")
            else:
                args.extend(["--dst", str(target)])
            result = cli.run("rvt-write", args)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            fail(
                "write_failed",
                detail[-1] if detail else f"exit status {result.returncode}",
            )
        summary: dict[str, Any] = {
            "source": str(source),
            "streams": [entry["stream"] for entry in manifest],
            "dry_run": dry_run,
            "report": result.stdout.strip(),
        }
        artifact = None if dry_run else artifact_for(target, "rvt")
        return build("rvt_write_streams", summary=summary, artifact=artifact)


def _manifest(patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise the accepted byte spellings into the CLI's manifest shape."""
    entries: list[dict[str, Any]] = []
    for patch in patches:
        stream = patch.get("stream")
        if not stream:
            fail("bad_patch", "every patch needs a `stream` name")
        entry: dict[str, Any] = {"stream": stream}
        if "bytes_base64" in patch:
            entry["bytes_base64"] = patch["bytes_base64"]
        elif "hex" in patch:
            entry["bytes"] = list(bytes.fromhex(str(patch["hex"])))
        elif "bytes" in patch:
            entry["bytes"] = list(patch["bytes"])
        else:
            fail(
                "bad_patch",
                f"patch for {stream!r} carries no bytes",
                hint="use bytes_base64, hex or bytes",
            )
        entries.append(entry)
    return entries
