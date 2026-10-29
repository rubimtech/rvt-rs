"""Geometry and export tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _helpers import open_sample, payload


async def test_geometry_location_lists_elements(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool("rvt_geometry", {"handle": handle, "detail": "location"})
    )
    assert result["summary"]["detail"] == "location"
    assert result["summary"]["unit"] == "metres"


async def test_geometry_boundary_and_solid_agree_on_unit(client, sample):
    handle = await open_sample(client, sample)
    for detail in ("boundary", "solid"):
        result = payload(
            await client.call_tool("rvt_geometry", {"handle": handle, "detail": detail})
        )
        assert result["summary"]["unit"] == "metres"


async def test_geometry_writes_a_file_when_asked(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_geometry",
            {"handle": handle, "detail": "location", "out": "geometry.json"},
        )
    )
    artifact = result["artifact"]
    assert artifact["format"] == "json"
    assert Path(artifact["path"]).is_file()


async def test_geometry_rejects_unknown_detail(client, sample):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_geometry", {"handle": handle, "detail": "voxels"})
    assert "bad_detail" in str(error.value)


async def test_export_glb_writes_a_binary_gltf(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_export_glb", {"handle": handle}))
    artifact = result["artifact"]
    assert artifact["format"] == "glb"
    data = Path(artifact["path"]).read_bytes()
    assert data[:4] == b"glTF"


async def test_export_glb_with_diagnostics_writes_the_sidecar(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_export_glb", {"handle": handle, "diagnostics": True}
        )
    )
    sidecar = Path(result["artifact"]["path"]).with_suffix(".diagnostics.json")
    assert sidecar.is_file()
    json.loads(sidecar.read_text(encoding="utf-8"))


async def test_export_ifc_writes_step(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_export_ifc", {"handle": handle}))
    text = Path(result["artifact"]["path"]).read_text(encoding="utf-8")
    assert text.startswith("ISO-10303-21")
    assert "IFCPROJECT" in text


async def test_export_ifc_rejects_unknown_mode(client, sample):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_export_ifc", {"handle": handle, "mode": "perfect"})
    assert "bad_mode" in str(error.value)


async def test_export_svg_writes_svg(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_export_svg", {"handle": handle, "width": 400, "height": 300}
        )
    )
    text = Path(result["artifact"]["path"]).read_text(encoding="utf-8")
    assert text.lstrip().startswith("<svg")


async def test_export_report_bundles_artifacts(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_export_report", {"handle": handle}))
    directory = Path(result["summary"]["directory"])
    assert (directory / "manifest.json").is_file()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"].endswith("empty.rfa")
    assert manifest["artifacts"]


async def test_export_obj_without_meshes_explains_why(client, sample):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_export_obj", {"handle": handle})
    assert "no_geometry" in str(error.value)
