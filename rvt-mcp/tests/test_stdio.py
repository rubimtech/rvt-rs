"""The real transport: the server as a separate process, over stdio.

Everything else in the suite runs the server in-process, which cannot catch a
bad console entry point, a missing dependency at startup or a broken handshake.
This one starts `rvt-mcp` exactly as a desktop client would.
"""

from __future__ import annotations

import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


@pytest.fixture()
def stdio_client(root):
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "rvt_mcp"],
        env={
            "RVT_MCP_ROOTS": str(root),
            "RVT_MCP_OUTPUT_DIR": str(root),
            "RVT_MCP_TRANSPORT": "stdio",
        },
    )
    return Client(transport)


async def test_server_starts_and_lists_tools(stdio_client):
    async with stdio_client as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
    assert "rvt_open" in names
    assert "rvt_export_report" in names


async def test_server_answers_a_real_call(stdio_client, sample):
    async with stdio_client as client:
        result = await client.call_tool("rvt_open", {"path": str(sample)})
        assert result.data.ok is True
        assert result.data.handle
