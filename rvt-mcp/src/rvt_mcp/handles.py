"""Registry of open files.

Opening a project inflates and scans its partitions, which is the expensive
part of every call. A file opened once stays in memory and later tools address
it by handle; the registry is a small LRU so a fourth file closes the first.

`rvt.RevitFile` decodes lazily through `&mut self`, so each entry carries its
own lock: two tool calls on the same file serialise instead of racing, while
calls on different files still run in parallel (FastMCP runs sync tools in a
worker thread).
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters import bindings
from .config import get_settings
from .errors import fail
from .paths import resolve_input

__all__ = ["Entry", "HandleRegistry", "registry"]


@dataclass
class Entry:
    """One open file, with the lock its decoders need."""

    handle: str
    path: Path
    file: Any
    opened_at: float
    lock: threading.RLock = field(default_factory=threading.RLock)
    version: int | None = None
    large_model: bool = False

    def describe(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "path": str(self.path),
            "version": self.version,
            "large_model": self.large_model,
            "open_seconds": round(time.monotonic() - self.opened_at, 3),
        }


class HandleRegistry:
    """A bounded LRU of open files, safe to call from worker threads."""

    def __init__(self, capacity: int | None = None) -> None:
        self._capacity = capacity or get_settings().cache_capacity
        self._entries: OrderedDict[str, Entry] = OrderedDict()
        self._lock = threading.RLock()

    def open(
        self,
        raw_path: str | Path,
        *,
        limits: dict[str, Any] | None = None,
        large_model: bool = False,
    ) -> Entry:
        """Open a file, or return the entry already open for that path."""
        path = resolve_input(raw_path)
        with self._lock:
            for entry in self._entries.values():
                if entry.path == path and entry.large_model == large_model:
                    self._entries.move_to_end(entry.handle)
                    return entry
            rvt = bindings.require()
            try:
                file = rvt.RevitFile(str(path), **(limits or {}))
            except (ValueError, OSError) as exc:
                fail(
                    "invalid_file",
                    f"{path.name} is not a readable Revit file: {exc}",
                    hint="supported containers are .rvt, .rfa, .rte and .rft",
                )
            entry = Entry(
                handle=f"{path.stem}-{secrets.token_hex(3)}",
                path=path,
                file=file,
                opened_at=time.monotonic(),
                version=_safe_version(file),
                large_model=large_model,
            )
            self._entries[entry.handle] = entry
            self._evict()
            return entry

    def get(self, handle: str) -> Entry:
        """The entry behind a handle, or a refusal naming the open ones."""
        with self._lock:
            entry = self._entries.get(handle)
            if entry is None:
                known = ", ".join(self._entries) or "none"
                fail(
                    "unknown_handle",
                    f"no open file with handle {handle!r}",
                    hint=f"open handles: {known}",
                )
            self._entries.move_to_end(handle)
            return entry

    def close(self, handle: str) -> bool:
        with self._lock:
            return self._entries.pop(handle, None) is not None

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [entry.describe() for entry in self._entries.values()]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _evict(self) -> None:
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)


def _safe_version(file: Any) -> int | None:
    try:
        return file.version
    except Exception:  # noqa: BLE001 - metadata is optional, not fatal
        return None


registry = HandleRegistry()
