"""Helpers for calling tools through the in-memory client."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

_ENVELOPE_FIELDS = (
    "ok",
    "tool",
    "handle",
    "summary",
    "preview",
    "artifact",
    "warnings",
)


def payload(result: Any) -> dict[str, Any]:
    """The structured result of a tool call, whatever shape the client returns.

    FastMCP hands back a dataclass mirroring the declared output model; older
    paths hand back the raw JSON text. Both are normalised to a dict here so a
    test never depends on which one it got.
    """
    data = getattr(result, "data", None)
    if data is not None:
        if isinstance(data, dict):
            return data
        if dataclasses.is_dataclass(data):
            return dataclasses.asdict(data)
        if all(hasattr(data, field) for field in _ENVELOPE_FIELDS):
            return {field: getattr(data, field) for field in _ENVELOPE_FIELDS}
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"no structured payload in {result!r}")


async def open_sample(client: Any, path) -> str:
    """Open the fixture and return its handle."""
    result = await client.call_tool("rvt_open", {"path": str(path)})
    return payload(result)["handle"]
