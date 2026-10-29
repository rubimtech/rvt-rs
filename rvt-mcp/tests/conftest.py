"""Shared fixtures: a sandboxed root with one real Revit container in it.

Every test runs against a temporary directory that is the server's only readable
root, which is also how the path policy gets exercised rather than mocked.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "families" / "empty.rfa"
PROJECT_FIXTURE = (
    REPO_ROOT / "corpus" / "tier1" / "architectural-2024" / "architectural-2024.rvt"
)


@pytest.fixture(scope="session", autouse=True)
def _environment(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("rvt-root")
    shutil.copy2(FIXTURE, root / "empty.rfa")
    if PROJECT_FIXTURE.is_file():
        shutil.copy2(PROJECT_FIXTURE, root / "project-2024.rvt")
    os.environ["RVT_MCP_ROOTS"] = str(root)
    os.environ["RVT_MCP_OUTPUT_DIR"] = str(root)
    os.environ["RVT_MCP_REPO_ROOT"] = str(REPO_ROOT)
    os.environ.pop("RVT_MCP_ALLOW_WRITE", None)
    return root


@pytest.fixture()
def root(_environment: Path) -> Path:
    from rvt_mcp.config import get_settings

    get_settings.cache_clear()
    return _environment


@pytest.fixture()
def sample(root: Path) -> Path:
    return root / "empty.rfa"


@pytest.fixture()
def project(root: Path) -> Path:
    path = root / "project-2024.rvt"
    if not path.is_file():
        pytest.skip("the synthetic 2024 project fixture is not in this checkout")
    return path


@pytest.fixture()
def server(root: Path):
    from rvt_mcp.config import get_settings
    from rvt_mcp.handles import registry
    from rvt_mcp.server import build_server

    get_settings.cache_clear()
    registry.clear()
    return build_server()


@pytest.fixture()
async def client(server):
    from fastmcp import Client

    async with Client(server) as connected:
        yield connected
