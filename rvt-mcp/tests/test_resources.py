"""Resources: the same facts, read as documents instead of called as tools."""

from __future__ import annotations

import json

from _helpers import open_sample


async def test_open_resource_lists_handles(client, sample):
    handle = await open_sample(client, sample)
    contents = await client.read_resource("rvt://open")
    rows = json.loads(contents[0].text)
    assert [row["handle"] for row in rows] == [handle]


async def test_metadata_resource(client, sample):
    handle = await open_sample(client, sample)
    contents = await client.read_resource(f"rvt://file/{handle}/metadata")
    metadata = json.loads(contents[0].text)
    assert "revit_version" in metadata


async def test_summary_resource(client, sample):
    handle = await open_sample(client, sample)
    contents = await client.read_resource(f"rvt://file/{handle}/summary")
    summary = json.loads(contents[0].text)
    assert summary["streams"]
    assert "element_counts" in summary


async def test_streams_resource(client, sample):
    handle = await open_sample(client, sample)
    contents = await client.read_resource(f"rvt://file/{handle}/streams")
    payload = json.loads(contents[0].text)
    assert "BasicFileInfo" in payload["streams"]


async def test_unknown_class_is_a_clear_failure(client, sample):
    handle = await open_sample(client, sample)
    try:
        await client.read_resource(f"rvt://file/{handle}/schema/NotAClass")
    except Exception as error:  # noqa: BLE001 - the client raises per transport
        assert "class_not_found" in str(error)
    else:
        raise AssertionError("reading an unknown class should fail")


async def test_contract_resource_reads_the_published_schema(client):
    contents = await client.read_resource("rvt://contracts/inspect")
    schema = json.loads(contents[0].text)
    assert schema["$id"].endswith("inspect.schema.json")
