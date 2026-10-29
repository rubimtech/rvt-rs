"""The CLI-backed tools.

They shell out to the `rvt-*` binaries, so they are skipped when the checkout has
not built them. Each test asserts the shape of the answer, not its numbers: the
point is that the adapter wires arguments correctly and reports failures with a
code rather than a traceback.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from _helpers import open_sample, payload

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "target" / "release"


def _have(name: str) -> bool:
    return (
        (BIN_DIR / f"{name}.exe").is_file()
        or (BIN_DIR / name).is_file()
        or shutil.which(name) is not None
    )


requires_bins = pytest.mark.skipif(
    not _have("rvt-diff"), reason="the rvt-* CLIs are not built in this checkout"
)


@requires_bins
async def test_diff_reports_stream_level_changes(client, root, sample):
    other = root / "changed.rfa"
    data = bytearray(sample.read_bytes())
    data[-1] ^= 0xFF
    other.write_bytes(bytes(data))
    result = payload(
        await client.call_tool("rvt_diff", {"paths": [str(sample), str(other)]})
    )
    assert result["summary"]["files"]
    assert isinstance(result["summary"]["report"], str)


async def test_diff_requires_two_files(client, sample):
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_diff", {"paths": [str(sample)]})
    assert "too_few_files" in str(error.value)


@requires_bins
async def test_history_reads_the_upgrade_timeline(client, sample):
    handle = await open_sample(client, sample)
    result = payload(await client.call_tool("rvt_history", {"handle": handle}))
    assert result["summary"]["source"] == "rvt-history"


@requires_bins
async def test_inventory_returns_one_row_per_file(client, sample):
    result = payload(await client.call_tool("rvt_inventory", {"paths": [str(sample)]}))
    assert result["summary"]["files"] >= 1


@requires_bins
async def test_capabilities_comes_from_the_cli(client):
    result = payload(await client.call_tool("rvt_capabilities", {}))
    assert result["summary"]["source"] == "rvt-capabilities"
    assert result["summary"]["matrix"]


@requires_bins
async def test_corpus_doctor_triages_a_folder(client, root):
    result = payload(
        await client.call_tool("rvt_corpus_doctor", {"paths": [str(root)]})
    )
    assert "buckets" in result["summary"]


async def test_corpus_needs_three_files(client, root, sample):
    other = root / "second.rfa"
    other.write_bytes(sample.read_bytes())
    with pytest.raises(Exception) as error:
        await client.call_tool("rvt_corpus", {"paths": [str(sample), str(other)]})
    assert "too_few_files" in str(error.value)


@requires_bins
async def test_ifc_compare_reports_deltas(client, sample, root):
    from rvt_mcp.handles import registry

    handle = await open_sample(client, sample)
    exported = payload(
        await client.call_tool("rvt_export_ifc", {"handle": handle, "out": "model.ifc"})
    )
    result = payload(
        await client.call_tool(
            "rvt_ifc_compare",
            {
                "left": exported["artifact"]["path"],
                "right": exported["artifact"]["path"],
            },
        )
    )
    assert result["summary"]["differences"] == {}
    assert registry.get(handle)


@requires_bins
async def test_export_data_history_writes_json(client, sample):
    handle = await open_sample(client, sample)
    result = payload(
        await client.call_tool(
            "rvt_export_data",
            {"handle": handle, "what": "history", "out": "history.json"},
        )
    )
    payload_json = json.loads(
        Path(result["artifact"]["path"]).read_text(encoding="utf-8")
    )
    assert payload_json is not None
