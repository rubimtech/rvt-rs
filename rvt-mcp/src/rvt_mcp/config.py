"""Runtime configuration, read once from the environment.

Every knob is an `RVT_MCP_*` variable, so a client configuration is a list of
environment entries and nothing else. The two that matter for safety are
`RVT_MCP_ROOTS` (the only directories the server will read Revit files from)
and `RVT_MCP_ALLOW_WRITE` (whether the stream-patching tool is exposed at all).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server settings; see the module docstring for the env names."""

    model_config = SettingsConfigDict(
        env_prefix="RVT_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    roots: str = Field(
        default="",
        description=(
            "Directories the server may read from, separated by the platform "
            "path separator. Empty means the current working directory."
        ),
    )
    output_dir: str = Field(
        default="",
        description="Where exported artifacts are written. Empty means the first root.",
    )
    bin_dir: str = Field(
        default="",
        description=(
            "Directory holding the rvt-* CLIs. Empty means $RVT_MCP_REPO_ROOT/target/release."
        ),
    )
    repo_root: str = Field(
        default="",
        description="Repository root, used to find the CLIs and the JSON schema contracts.",
    )

    allow_write: bool = Field(
        default=False,
        description="Expose `rvt_write_streams`, the only tool that modifies files.",
    )
    cache_capacity: int = Field(default=3, ge=1, le=32)
    max_response_bytes: int = Field(default=65_536, ge=4_096)
    preview_items: int = Field(default=20, ge=1, le=500)
    cli_timeout_seconds: float = Field(default=900.0, gt=0)
    default_large_model: bool = Field(
        default=False,
        description="Open files with the CLIs' --large-model presets.",
    )
    max_stream_bytes: int | None = None
    max_inflate_bytes: int | None = None

    @property
    def root_paths(self) -> list[Path]:
        """The resolved read allowlist. Never empty."""
        raw = self.roots or os.getcwd()
        return _split_paths(raw)

    @property
    def output_path(self) -> Path:
        """The directory artifacts are written to."""
        if self.output_dir:
            return Path(self.output_dir).expanduser().resolve()
        return self.root_paths[0]

    @property
    def bin_path(self) -> Path | None:
        """The directory holding the `rvt-*` binaries, if it exists."""
        if self.bin_dir:
            candidate = Path(self.bin_dir).expanduser().resolve()
            return candidate if candidate.is_dir() else None
        if self.repo_root:
            candidate = (
                Path(self.repo_root).expanduser().resolve() / "target" / "release"
            )
            return candidate if candidate.is_dir() else None
        return None

    @property
    def repo_path(self) -> Path | None:
        """The repository root, if it was configured."""
        return Path(self.repo_root).expanduser().resolve() if self.repo_root else None


def _split_paths(raw: str) -> list[Path]:
    parts = [part.strip() for part in raw.split(os.pathsep)]
    paths = [Path(part).expanduser().resolve() for part in parts if part]
    # A stale entry must not silently widen or narrow the allowlist.
    return [path for path in paths if path.exists()] or [Path.cwd().resolve()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings. Tests clear this cache after changing env."""
    return Settings()
