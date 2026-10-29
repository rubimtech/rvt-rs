"""The in-process `rvt` extension.

This is the only module that imports the compiled bindings, so a missing or
mismatched wheel produces one actionable message instead of an `ImportError`
from the middle of a tool.
"""

from __future__ import annotations

from typing import Any

from ..errors import fail

__all__ = ["require"]

try:  # pragma: no cover - exercised by the import-guard test
    import rvt as _rvt
except ImportError:  # pragma: no cover
    _rvt = None


def require() -> Any:
    """The `rvt` module, or a refusal that names the fix."""
    if _rvt is None:
        fail(
            "rvt_bindings_missing",
            "the `rvt` Python wheel is not installed",
            hint=(
                "pip install rvt, or build it from the repository with "
                "`maturin build --release --manifest-path rvt-py/Cargo.toml`"
            ),
        )
    return _rvt
