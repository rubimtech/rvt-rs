"""Adapters between the server and the code that actually reads files.

`bindings` calls the in-process `rvt` extension; `cli` runs the shipped `rvt-*`
binaries; `glb` reads back the geometry the exporter wrote. Nothing in
`rvt_mcp.tools` imports `rvt` directly.
"""
