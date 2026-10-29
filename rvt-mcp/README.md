# rvt-mcp

An MCP server for reading Autodesk Revit files (`.rvt`, `.rfa`, `.rte`, `.rft`)
without Revit: metadata, elements, schedules, geometry, and IFC4 / glTF / plan
SVG export.

The server is a protocol layer only. Parsing, element decoding and every writer
live in the Rust `rvt` crate, reached in-process through the `rvt` Python wheel
(the fast path) or through the shipped `rvt-*` CLIs (the path that carries the
saved-mesh, property-set, diff and corpus features).

## Install

```bash
python -m venv .venv
.venv/Scripts/activate            # POSIX: source .venv/bin/activate
pip install -e rvt-mcp

# the Rust half: either the wheel from PyPI
pip install rvt
# or, from this repository
pip install maturin
maturin build --release --manifest-path rvt-py/Cargo.toml -o dist
pip install dist/rvt-*.whl

# optional, for the tools that shell out
cargo build --release
```

## Run

```bash
rvt-mcp                                  # stdio, what a desktop client expects
RVT_MCP_TRANSPORT=http rvt-mcp           # network transport
```

Client configuration (Claude Desktop, Cursor, VS Code, Kilo):

```json
{
  "mcpServers": {
    "rvt": {
      "command": "rvt-mcp",
      "env": {
        "RVT_MCP_ROOTS": "/path/to/revit/files",
        "RVT_MCP_REPO_ROOT": "/path/to/rvt-rs"
      }
    }
  }
}
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `RVT_MCP_ROOTS` | cwd | Directories the server may read from, separated by the platform path separator. Everything else is refused. |
| `RVT_MCP_OUTPUT_DIR` | first root | Where artifacts are written. |
| `RVT_MCP_BIN_DIR` | `$RVT_MCP_REPO_ROOT/target/release` | Where the `rvt-*` binaries are. |
| `RVT_MCP_REPO_ROOT` | — | Repository root, for the CLIs and the JSON schema contracts. |
| `RVT_MCP_ALLOW_WRITE` | `false` | Registers `rvt_write_streams`, the only tool that writes a Revit file. |
| `RVT_MCP_CACHE_CAPACITY` | `3` | How many parsed files stay in memory. |
| `RVT_MCP_MAX_RESPONSE_BYTES` | `65536` | Response budget; previews shrink to fit. |
| `RVT_MCP_PREVIEW_ITEMS` | `20` | Default preview size. |
| `RVT_MCP_CLI_TIMEOUT_SECONDS` | `900` | Per-CLI timeout. |
| `RVT_MCP_DEFAULT_LARGE_MODEL` | `false` | Open files with the large-model limits by default. |

## Tools

**Session** — `rvt_open`, `rvt_close`, `rvt_list_open`, `rvt_capabilities`

**Metadata** — `rvt_metadata`, `rvt_inspect`, `rvt_schema`, `rvt_history`,
`rvt_elem_table`, `rvt_document`, `rvt_streams`, `rvt_stream_read`, `rvt_preview`

**Elements** — `rvt_counts`, `rvt_elements`, `rvt_element`, `rvt_schedule`,
`rvt_inventory`, `rvt_export_data`

**Geometry** — `rvt_geometry` (location / boundary / solid / mesh),
`rvt_export_obj`

**Export** — `rvt_export_glb`, `rvt_export_ifc`, `rvt_export_svg`,
`rvt_export_report`

**Comparison** — `rvt_diff`, `rvt_ifc_compare`, `rvt_corpus_doctor`,
`rvt_corpus`

**Write** (opt-in) — `rvt_write_streams`

### Resources

`rvt://open`, `rvt://file/{handle}/metadata`, `/summary`, `/streams`,
`/schema/{class}`, `/elements/{id}`, `/preview.png`, `rvt://capabilities`,
`rvt://contracts/{name}`.

### Prompts

`inspect_revit_file`, `export_model_bundle`, `compare_revisions`.

## Conventions

- **A handle, not a path.** `rvt_open` parses once and returns a handle; every
  other tool accepts `handle` or `path`, never both. Opening is the expensive
  step, so reusing the handle is the difference between milliseconds and tens of
  seconds on a real project.
- **Artifacts, not payloads.** An export returns `{path, format, bytes, sha256}`.
  A list returns a capped preview with `total` and `truncated`. The response
  shrinks itself to `RVT_MCP_MAX_RESPONSE_BYTES`.
- **Stable error codes.** Failures raise a tool error whose first token is
  machine-readable: `path_not_allowed`, `unknown_handle`, `invalid_file`,
  `element_not_found`, `bad_mode`, `cli_missing`, `export_failed`, and so on.
- **Honest results.** A file that decodes to zero elements still exports a valid
  scaffold; the tools say so in `warnings` rather than letting a caller mistake
  it for a model.

## Tests

```bash
cd rvt-mcp
pytest            # in-memory FastMCP client; needs the `rvt` wheel installed
```

The suite runs against `tests/fixtures/empty.rfa` copied into a temporary root,
so the path policy is exercised for real instead of being mocked. Tests for the
CLI-backed tools skip when the binaries are absent.
