"""Console entry point.

`rvt-mcp` runs the server on stdio, which is what a desktop MCP client expects.
Set `RVT_MCP_TRANSPORT=http` for a network transport (the client then needs the
URL FastMCP prints).
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    from .server import build_server

    transport = os.environ.get("RVT_MCP_TRANSPORT", "stdio").strip() or "stdio"
    server = build_server()
    if transport == "stdio":
        server.run(transport="stdio", show_banner=False)
    elif transport in {"http", "streamable-http"}:
        server.run(transport="http", show_banner=False)
    else:
        print(f"rvt-mcp: unknown RVT_MCP_TRANSPORT {transport!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
