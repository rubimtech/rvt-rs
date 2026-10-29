"""The tool surface: names, schemas and the read-only contract."""

from __future__ import annotations

EXPECTED_TOOLS = {
    "rvt_open",
    "rvt_close",
    "rvt_list_open",
    "rvt_capabilities",
    "rvt_metadata",
    "rvt_inspect",
    "rvt_schema",
    "rvt_history",
    "rvt_elem_table",
    "rvt_document",
    "rvt_streams",
    "rvt_stream_read",
    "rvt_preview",
    "rvt_counts",
    "rvt_elements",
    "rvt_element",
    "rvt_schedule",
    "rvt_inventory",
    "rvt_export_data",
    "rvt_geometry",
    "rvt_export_obj",
    "rvt_export_glb",
    "rvt_export_ifc",
    "rvt_export_svg",
    "rvt_export_report",
    "rvt_diff",
    "rvt_ifc_compare",
    "rvt_corpus_doctor",
    "rvt_corpus",
}


async def test_every_tool_is_registered(client):
    tools = await client.list_tools()
    names = {tool.name for tool in tools}
    assert names >= EXPECTED_TOOLS, f"missing: {sorted(EXPECTED_TOOLS - names)}"


async def test_write_tool_is_absent_by_default(client):
    names = {tool.name for tool in await client.list_tools()}
    assert "rvt_write_streams" not in names


async def test_tools_declare_descriptions_and_schemas(client):
    for tool in await client.list_tools():
        assert tool.description, f"{tool.name} has no description"
        assert tool.input_schema, f"{tool.name} has no input schema"


async def test_read_only_tools_are_annotated(client):
    read_only = {
        "rvt_open",
        "rvt_metadata",
        "rvt_inspect",
        "rvt_counts",
        "rvt_elements",
        "rvt_geometry",
        "rvt_streams",
    }
    for tool in await client.list_tools():
        if tool.name in read_only:
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True


async def test_prompts_are_registered(client):
    prompts = {prompt.name for prompt in await client.list_prompts()}
    assert {"inspect_revit_file", "export_model_bundle", "compare_revisions"} <= prompts
