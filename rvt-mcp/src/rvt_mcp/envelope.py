"""The response envelope every tool returns.

Two rules keep a chat context usable:

* a tool never returns a file's contents, only a path, its size and a checksum;
* a list preview is capped, with the total and a `truncated` flag beside it, so
  "20 of 1,842" is visible instead of being silently lost.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import get_settings
from .paths import sha256_file

__all__ = ["Artifact", "Preview", "Result", "artifact_for", "build", "cap"]


class Artifact(BaseModel):
    """A file the server wrote, addressed by path rather than by content."""

    path: str
    format: str
    bytes: int
    sha256: str


class Preview(BaseModel):
    """The head of a list, with the size of the list it came from."""

    items: list[Any] = Field(default_factory=list)
    total: int = 0
    truncated: bool = False


class Result(BaseModel):
    """What a successful tool call returns."""

    ok: bool = True
    tool: str
    handle: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    preview: Preview | None = None
    artifact: Artifact | None = None
    warnings: list[str] = Field(default_factory=list)


def artifact_for(path: Path, fmt: str) -> Artifact:
    return Artifact(
        path=str(path),
        format=fmt,
        bytes=path.stat().st_size,
        sha256=sha256_file(path),
    )


def cap(items: list[Any], limit: int | None = None) -> Preview:
    """Take the configured number of leading items and keep the true count."""
    limit = limit if limit is not None else get_settings().preview_items
    return Preview(items=items[:limit], total=len(items), truncated=len(items) > limit)


def build(
    tool: str,
    *,
    handle: str | None = None,
    summary: dict[str, Any] | None = None,
    items: list[Any] | None = None,
    preview_limit: int | None = None,
    artifact: Artifact | None = None,
    warnings: list[str] | None = None,
) -> Result:
    """Assemble a result, shrinking the preview until it fits the byte budget.

    The cap is on the serialised payload, not on the item count: one element
    with a long parameter list can outweigh twenty small ones.
    """
    settings = get_settings()
    preview = cap(items, preview_limit) if items is not None else None
    result = Result(
        tool=tool,
        handle=handle,
        summary=summary or {},
        preview=preview,
        artifact=artifact,
        warnings=warnings or [],
    )
    while _size(result) > settings.max_response_bytes and result.preview is not None:
        items_left = result.preview.items
        if not items_left:
            result.preview = None
            break
        keep = max(0, len(items_left) // 2)
        result.preview = Preview(
            items=items_left[:keep],
            total=result.preview.total,
            truncated=True,
        )
    if _size(result) > settings.max_response_bytes:
        result.summary = {
            "note": "the summary was dropped: it exceeded the response budget",
            "artifact": result.artifact.path if result.artifact else None,
        }
    return result


def _size(result: Result) -> int:
    return len(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
    )
