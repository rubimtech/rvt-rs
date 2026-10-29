"""Subprocess adapter for the shipped `rvt-*` CLIs.

The bindings cover the fast paths; a handful of tools need a CLI because that is
where the feature lives (`rvt-diff`, `rvt-corpus`, `rvt-history`, `rvt-write`,
`rvt-ifc-compare`, `rvt-info`'s inventory mode). Keeping them behind one runner
means the failure modes — binary missing, non-zero exit, unparsable JSON — are
handled in one place.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..config import get_settings
from ..errors import fail

__all__ = ["CliResult", "available", "run", "run_json"]

_EXE = ".exe" if __import__("sys").platform == "win32" else ""


@dataclass(frozen=True)
class CliResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    def json(self) -> Any:
        text = self.stdout.strip()
        if not text:
            fail("cli_empty_output", f"{self.argv[0]} printed nothing on stdout")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            fail(
                "cli_bad_json",
                f"{self.argv[0]} did not print JSON: {exc}",
                hint="run the same command by hand to see its output",
            )


def _binary(name: str) -> Path:
    settings = get_settings()
    bin_dir = settings.bin_path
    if bin_dir is not None:
        candidate = bin_dir / f"{name}{_EXE}"
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    if found:
        return Path(found)
    fail(
        "cli_missing",
        f"the `{name}` binary was not found",
        hint=(
            "build the CLIs with `cargo build --release`, then point "
            "RVT_MCP_BIN_DIR (or RVT_MCP_REPO_ROOT) at them"
        ),
    )


def available(name: str) -> bool:
    """Whether a CLI can be run, without raising when it cannot."""
    try:
        _binary(name)
    except Exception:  # noqa: BLE001 - a probe must never raise
        return False
    return True


def run(name: str, args: Sequence[str], *, timeout: float | None = None) -> CliResult:
    """Run one CLI and return its exit status and captured streams."""
    settings = get_settings()
    argv = [str(_binary(name)), *map(str, args)]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or settings.cli_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        fail(
            "cli_timeout",
            f"{name} did not finish within {timeout or settings.cli_timeout_seconds:.0f}s",
            hint="raise RVT_MCP_CLI_TIMEOUT_SECONDS, or narrow the request",
        )
    except OSError as exc:
        fail("cli_failed", f"{name} could not be started: {exc}")
    return CliResult(
        argv=argv,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_json(
    name: str,
    args: Sequence[str],
    *,
    timeout: float | None = None,
    ok_codes: tuple[int, ...] = (0,),
) -> Any:
    """Run a CLI that prints JSON, failing with its stderr when it does not."""
    result = run(name, args, timeout=timeout)
    if result.returncode not in ok_codes:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else f"exit status {result.returncode}"
        fail(
            "cli_error",
            f"{name} failed: {message}",
            hint=f"exit status {result.returncode}",
        )
    return result.json()
