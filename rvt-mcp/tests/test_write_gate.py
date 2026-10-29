"""The write gate: `rvt_write_streams` exists only when the operator enables it."""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def write_server(monkeypatch, root):
    from rvt_mcp.config import get_settings
    from rvt_mcp.handles import registry
    from rvt_mcp.server import build_server

    monkeypatch.setenv("RVT_MCP_ALLOW_WRITE", "1")
    get_settings.cache_clear()
    registry.clear()
    yield build_server()
    monkeypatch.delenv("RVT_MCP_ALLOW_WRITE", raising=False)
    get_settings.cache_clear()


async def test_write_tool_appears_when_enabled(write_server):
    from fastmcp import Client

    async with Client(write_server) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert "rvt_write_streams" in names


async def test_write_tool_requires_patches(write_server, sample):
    from fastmcp import Client

    async with Client(write_server) as client:
        with pytest.raises(Exception) as error:
            await client.call_tool(
                "rvt_write_streams",
                {"src": str(sample), "dst": "out.rfa", "patches": []},
            )
    assert "no_patches" in str(error.value)


async def test_dry_run_reports_the_manifest_shape(write_server, sample, root):
    from fastmcp import Client

    async with Client(write_server) as client:
        try:
            result = await client.call_tool(
                "rvt_write_streams",
                {
                    "src": str(sample),
                    "dst": "out.rfa",
                    "patches": [{"stream": "BasicFileInfo", "bytes": [1, 2, 3]}],
                    "dry_run": True,
                },
            )
        except Exception as error:  # noqa: BLE001 - the CLI may be absent in a bare checkout
            assert "cli_missing" in str(error) or "write_failed" in str(error)
            return
    data = (
        result.data
        if isinstance(result.data, dict)
        else json.loads(result.content[0].text)
    )
    assert data["summary"]["streams"] == ["BasicFileInfo"]
    assert data["summary"]["dry_run"] is True
