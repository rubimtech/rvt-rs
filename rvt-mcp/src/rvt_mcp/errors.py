"""Error surface of the server.

Tools never return a half-built payload on failure. They raise
`fastmcp.exceptions.ToolError`, which the protocol reports as a failed call with
the message intact, so a client can tell a policy refusal (`path_not_allowed`)
from an unreadable file (`invalid_file`) without parsing prose.
"""

from __future__ import annotations

from typing import NoReturn

from fastmcp.exceptions import ToolError

__all__ = ["ToolError", "fail", "wrap"]


def fail(code: str, message: str, *, hint: str | None = None) -> NoReturn:
    """Raise a tool error whose first token is a stable machine-readable code."""
    text = f"{code}: {message}"
    if hint:
        text = f"{text}\nHint: {hint}"
    raise ToolError(text)


def wrap(code: str, exc: BaseException, *, hint: str | None = None) -> NoReturn:
    """Report an exception raised by the `rvt` bindings or a CLI."""
    fail(code, str(exc).strip() or exc.__class__.__name__, hint=hint)
