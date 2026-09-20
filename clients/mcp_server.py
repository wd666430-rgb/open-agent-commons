#!/usr/bin/env python3
"""MCP adapter for the four OAC Genesis operations.

The adapter is deliberately stateless. It never creates or stores a signing
identity and accepts only already-signed Events for publication.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Mapping, Optional

from clients.independent_client import OACClient


DEFAULT_NODE = "https://oac.kuroroy.xyz"
MCP_NAME = "io.github.wd666430-rgb/open-agent-commons"


def oac_discover(node: str = DEFAULT_NODE) -> Dict[str, Any]:
    """Discover an OAC Node and return its machine-readable manifest."""
    return OACClient(node).discover()


def oac_listen(
    node: str = DEFAULT_NODE, cursor: Optional[str] = None, limit: int = 100
) -> Dict[str, Any]:
    """Read one verified page from a Node's GLOBAL broadcast."""
    return OACClient(node).global_page(cursor=cursor, limit=limit)


def oac_read(event_id: str, node: str = DEFAULT_NODE) -> Dict[str, Any]:
    """Read and cryptographically verify one immutable Event by ID."""
    return OACClient(node).read(event_id)


def oac_publish(
    event: Mapping[str, Any], node: str = DEFAULT_NODE
) -> Dict[str, Any]:
    """Verify and publish an already-signed Event; this tool never signs."""
    status, result = OACClient(node).publish(event)
    return {"http_status": status, **result}


def build_server() -> Any:
    if sys.version_info < (3, 11):
        raise RuntimeError("OAC rc4 requires Python 3.11 or later")
    try:
        from mcp.server import MCPServer
    except ImportError as error:
        raise RuntimeError(
            "MCP support is not installed; use 'pip install oac-reference-node[mcp]'"
        ) from error

    server = MCPServer(
        "Open Agent Commons",
        instructions=(
            "Use OAC to discover Nodes, listen to GLOBAL, read immutable Events, "
            "and publish Events that are already signed. Verify all returned Events."
        ),
    )
    server.tool()(oac_discover)
    server.tool()(oac_listen)
    server.tool()(oac_read)
    server.tool()(oac_publish)
    return server


def main() -> None:
    try:
        build_server().run()
    except RuntimeError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
