"""Opening, reusing and closing a file."""

from __future__ import annotations

from _helpers import open_sample, payload


async def test_open_reports_what_the_file_is(client, sample):
    result = payload(await client.call_tool("rvt_open", {"path": str(sample)}))
    assert result["ok"] is True
    assert result["handle"]
    summary = result["summary"]
    assert summary["stream_count"] > 0
    assert "BasicFileInfo" in summary["streams"]


async def test_open_is_idempotent_for_the_same_path(client, sample):
    first = await open_sample(client, sample)
    second = await open_sample(client, sample)
    assert first == second


async def test_list_open_shows_the_handle(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_list_open", {}))
    assert [row["handle"] for row in result["preview"]["items"]] == [handle]


async def test_close_removes_the_handle(client, sample):
    handle = await open_sample(client, sample)
    closed = payload(await client.call_tool("rvt_close", {"handle": handle}))
    assert closed["summary"]["closed"] is True
    listing = payload(await client.call_tool("rvt_list_open", {}))
    assert listing["summary"]["open"] == 0


async def test_second_open_evicts_the_oldest(client, root, sample):
    other = root / "copy.rfa"
    other.write_bytes(sample.read_bytes())
    first = await open_sample(client, sample)
    second = await open_sample(client, other)
    assert first != second
    listing = payload(await client.call_tool("rvt_list_open", {}))
    handles = [row["handle"] for row in listing["preview"]["items"]]
    assert second in handles
    assert len(handles) <= 3
