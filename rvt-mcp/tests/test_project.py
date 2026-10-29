"""The same tools against a Revit 2024 project container rather than a family.

The repository's 2024 project is a synthetic, license-free container: it opens,
reports its release and exports, but its streams are placeholders, so the schema
and element-table readers refuse it. That refusal is part of the contract, so
both outcomes are asserted rather than skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

from _helpers import open_sample, payload


async def test_project_opens_with_its_release(client, project):
    result = payload(await client.call_tool("rvt_open", {"path": str(project)}))
    assert result["summary"]["version"] == 2024
    assert result["summary"]["stream_count"] > 0


async def test_project_glb_is_well_formed(client, project):
    handle = await open_sample(client, project)
    result = payload(await client.call_tool("rvt_export_glb", {"handle": handle}))
    data = Path(result["artifact"]["path"]).read_bytes()
    assert data[:4] == b"glTF"
    assert int.from_bytes(data[4:8], "little") == 2


async def test_project_report_manifest_lists_every_artifact(client, project):
    handle = await open_sample(client, project)
    result = payload(await client.call_tool("rvt_export_report", {"handle": handle}))
    directory = Path(result["summary"]["directory"])
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    formats = {item["format"] for item in manifest["artifacts"]}
    assert {"ifc", "glb", "svg", "json", "csv"} <= formats


async def test_project_inspect_never_pretends_success(client, project):
    handle = await open_sample(client, project)
    result = payload(await client.call_tool("rvt_inspect", {"handle": handle}))
    counts = result["summary"]["element_counts"]
    if counts.get("total", 0) == 0:
        assert any("scaffold" in warning for warning in result["warnings"])


async def test_project_schema_either_reads_or_says_why(client, project):
    handle = await open_sample(client, project)
    try:
        result = payload(
            await client.call_tool("rvt_schema", {"handle": handle, "top": 3})
        )
    except Exception as error:  # noqa: BLE001 - a refusal is a valid outcome here
        assert "schema_unavailable" in str(error)
    else:
        assert result["summary"]["class_count"] > 0


async def test_project_elem_table_either_reads_or_says_why(client, project):
    handle = await open_sample(client, project)
    try:
        result = payload(
            await client.call_tool("rvt_elem_table", {"handle": handle, "limit": 5})
        )
    except Exception as error:  # noqa: BLE001 - a refusal is a valid outcome here
        assert "elem_table_unavailable" in str(error)
    else:
        assert result["summary"]["record_count"] >= 0


async def test_family_schema_is_large_and_filterable(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_schema", {"handle": handle, "top": 3}))
    assert result["summary"]["class_count"] > 100
    assert len(result["preview"]["items"]) <= 3
    fields = [len(row["fields"]) for row in result["preview"]["items"]]
    assert fields == sorted(fields, reverse=True)


async def test_family_elem_table_declares_elements(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool("rvt_elem_table", {"handle": handle, "limit": 5})
    )
    assert result["summary"]["record_count"] > 0
    assert len(result["summary"]["declared_element_ids"]) <= 5
