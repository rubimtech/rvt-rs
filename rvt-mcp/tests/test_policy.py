"""Path policy and error surface."""

from __future__ import annotations

import pytest
from _helpers import open_sample, payload


async def test_read_outside_the_roots_is_refused(client, tmp_path):
    outside = tmp_path / "outside.rfa"
    outside.write_bytes(b"not a revit file")
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_open", {"path": str(outside)})
    assert "path_not_allowed" in str(error.value)


async def test_missing_file_names_the_path(client, root):
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_open", {"path": str(root / "nope.rfa")})
    assert "file_not_found" in str(error.value)


async def test_unknown_handle_lists_the_open_ones(client, sample):
    await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_metadata", {"handle": "not-a-handle"})
    message = str(error.value)
    assert "unknown_handle" in message
    assert "open handles" in message


async def test_handle_and_path_together_is_ambiguous(client, sample):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_metadata", {"handle": handle, "path": str(sample)})
    assert "ambiguous_target" in str(error.value)


async def test_no_target_is_refused(client):
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_metadata", {})
    assert "missing_target" in str(error.value)


async def test_export_outside_the_output_root_is_refused(client, sample, tmp_path):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool(
            "rvt_export_glb", {"handle": handle, "out": str(tmp_path / "evil.glb")}
        )
    assert "output_not_allowed" in str(error.value)


async def test_export_onto_the_input_is_refused(client, sample):
    handle = await open_sample(client, sample)
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_export_glb", {"handle": handle, "out": str(sample)})
    assert "output_overwrites_input" in str(error.value)


async def test_non_revit_input_is_reported_as_invalid(client, root):
    junk = root / "junk.rvt"
    junk.write_bytes(b"\x00" * 4096)
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_open", {"path": str(junk)})
    assert "invalid_file" in str(error.value)


async def test_relative_output_lands_in_the_output_root(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_export_svg", {"handle": handle, "out": "plans/level-1.svg"}
        )
    )
    assert result["artifact"]["path"].endswith("plans\\level-1.svg") or result[
        "artifact"
    ]["path"].endswith("plans/level-1.svg")
