"""Element, schedule and bulk-export tools."""

from __future__ import annotations

import json

import pytest
from _helpers import open_sample, payload


async def test_counts_shape(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_counts", {"handle": handle}))
    assert "total" in result["summary"]
    assert "by_class" in result["summary"]


async def test_elements_pagination_contract(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_elements", {"handle": handle, "limit": 5, "offset": 0}
        )
    )
    summary = result["summary"]
    assert summary["returned"] <= 5
    assert summary["offset"] == 0
    assert summary["next_offset"] is None or summary["next_offset"] > 0


async def test_elements_filters_by_category(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_elements", {"handle": handle, "categories": ["Wall"]}
        )
    )
    assert all(row["class_name"] == "Wall" for row in result["preview"]["items"])


async def test_missing_element_is_a_tool_error(client, sample):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool(
            "rvt_element", {"handle": handle, "element_id": 999_999_999}
        )
    assert "element_not_found" in str(error.value)


async def test_schedule_writes_csv(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool("rvt_schedule", {"handle": handle, "kind": "elements"})
    )
    artifact = result["artifact"]
    assert artifact["format"] == "csv"
    assert artifact["bytes"] > 0
    assert artifact["sha256"]


async def test_schedule_rejects_unknown_kind(client, sample):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_schedule", {"handle": handle, "kind": "doors"})
    assert "bad_schedule_kind" in str(error.value)


async def test_export_data_writes_jsonl(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_export_data",
            {"handle": handle, "format": "jsonl", "out": "elements.jsonl"},
        )
    )
    assert result["artifact"]["format"] == "jsonl"


async def test_export_data_rejects_unknown_kind(client, sample):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool(
            "rvt_export_data", {"handle": handle, "what": "everything"}
        )
    assert "bad_export_kind" in str(error.value)


async def test_inventory_either_works_or_says_the_cli_is_missing(client, sample):
    """rvt_inventory shells out; a bare checkout must get a coded refusal, not a traceback."""
    try:
        result = payload(
            await client.call_tool("rvt_inventory", {"paths": [str(sample)]})
        )
    except Exception as error:  # noqa: BLE001 - the missing-CLI path is a valid outcome
        message = str(error.value)
        assert "cli_missing" in message or "cli_error" in message
    else:
        assert result["summary"]["files"] >= 1


async def test_elements_json_is_valid_for_an_empty_family(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_export_data",
            {"handle": handle, "what": "counts", "out": "counts.json"},
        )
    )
    path = result["artifact"]["path"]
    with open(path, encoding="utf-8") as stream:
        assert isinstance(json.load(stream), list)
