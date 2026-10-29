"""Metadata, inspection and stream tools."""

from __future__ import annotations

import pytest
from _helpers import open_sample, payload


async def test_metadata_returns_identity(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_metadata", {"handle": handle}))
    summary = result["summary"]
    assert summary["path"].endswith("empty.rfa")
    assert summary["basic_file_info"] is not None


async def test_inspect_reports_readiness(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_inspect", {"handle": handle}))
    summary = result["summary"]
    assert "missing_required_streams" in summary
    assert "element_counts" in summary
    assert isinstance(result["warnings"], list)


async def test_streams_lists_the_container(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_streams", {"handle": handle}))
    names = [row["name"] for row in result["preview"]["items"]]
    assert "BasicFileInfo" in names
    assert result["summary"]["stream_count"] == len(names)


async def test_stream_read_decodes_utf16(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_stream_read",
            {
                "handle": handle,
                "name": "BasicFileInfo",
                "encoding": "utf16",
                "length": 256,
            },
        )
    )
    summary = result["summary"]
    assert summary["stream_bytes"] > 0
    assert summary["returned_bytes"] > 0
    assert isinstance(summary["data"], str)


async def test_stream_read_refuses_an_unknown_encoding(client, sample):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool(
            "rvt_stream_read",
            {"handle": handle, "name": "BasicFileInfo", "encoding": "ebcdic"},
        )
    assert "bad_encoding" in str(error.value)


async def test_schema_grep_narrows_the_table(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool("rvt_schema", {"handle": handle, "grep": "Wall"})
    )
    rows = result["preview"]["items"]
    assert all("Wall" in row["name"] for row in rows)
    assert result["summary"]["matched_classes"] <= result["summary"]["class_count"]


async def test_schema_diagnostics_is_a_counter_set(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool("rvt_schema", {"handle": handle, "diagnostics": True})
    )
    assert "class_count" in result["summary"]


async def test_elem_table_header_and_records(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool("rvt_elem_table", {"handle": handle, "limit": 5})
    )
    assert "record_count" in result["summary"]
    assert len(result["summary"]["declared_element_ids"]) <= 5


async def test_preview_is_an_image(client, sample):
    handle = await open_sample(client, sample)
    result = await client.call_tool("rvt_preview", {"handle": handle})
    content = result.content[0]
    assert content.type == "image"
    assert content.mime_type == "image/png"
