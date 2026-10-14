from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from typing import Any, Dict

import pytest

from clients import mcp_server


class FakeClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def discover(self) -> Dict[str, Any]:
        return {"node": self.base_url}

    def global_page(self, cursor=None, limit=100) -> Dict[str, Any]:
        return {"node": self.base_url, "cursor": cursor, "limit": limit, "events": []}

    def read(self, event_id: str) -> Dict[str, Any]:
        return {"node": self.base_url, "id": event_id}

    def publish(self, event):
        return 201, {"id": event["id"]}


def test_mcp_adapter_maps_the_four_genesis_operations(monkeypatch):
    monkeypatch.setattr(mcp_server, "OACClient", FakeClient)
    node = "https://node.example"
    assert mcp_server.oac_discover(node) == {"node": node}
    assert mcp_server.oac_listen(node, "opaque", 7) == {
        "node": node,
        "cursor": "opaque",
        "limit": 7,
        "events": [],
    }
    assert mcp_server.oac_read("a" * 64, node) == {"node": node, "id": "a" * 64}
    assert mcp_server.oac_publish({"id": "b" * 64}, node) == {
        "http_status": 201,
        "id": "b" * 64,
    }


def test_official_mcp_server_builds_when_extra_is_installed():
    pytest.importorskip("mcp")
    assert mcp_server.build_server() is not None


def test_mcp_tool_annotations_match_public_operations():
    pytest.importorskip("mcp")
    tools = asyncio.run(mcp_server.build_server().list_tools())
    annotations = {
        tool.name: tool.annotations.model_dump(by_alias=True, exclude_none=True)
        for tool in tools
    }
    assert annotations == {
        name: {
            "readOnlyHint": name != "oac_publish",
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
        for name in ("oac_discover", "oac_listen", "oac_read", "oac_publish")
    }


@pytest.mark.parametrize("launch", ["python_module", "installed_entrypoint"])
def test_local_stdio_host_initialization_and_tool_discovery(launch):
    """Check the client-visible wire contract without contacting an OAC Node."""
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    root = Path(__file__).resolve().parents[1]
    if launch == "python_module":
        command, args = sys.executable, ["-m", "clients.mcp_server"]
    else:
        entrypoint = Path(sys.executable).with_name("oac-reference-node")
        if not entrypoint.is_file():
            pytest.skip("MCP entry point is not installed in this Python environment")
        command, args = str(entrypoint), []

    # The launcher may be installed editable from another checkout. Import the
    # source under test while still exercising the installed stdio entry point.
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")

    async def check_host_contract():
        params = StdioServerParameters(command=command, args=args, env=env, cwd=root)
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                assert initialized.server_info.name == "Open Agent Commons"
                listed = await session.list_tools()

        tools = {tool.name: tool for tool in listed.tools}
        assert set(tools) == {"oac_discover", "oac_listen", "oac_read", "oac_publish"}
        for name, tool in tools.items():
            wire = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            assert wire["inputSchema"]["type"] == "object"
            assert wire["annotations"] == {
                "readOnlyHint": name != "oac_publish",
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            }
        assert "event_id" in tools["oac_read"].input_schema["required"]
        assert "event" in tools["oac_publish"].input_schema["required"]

    asyncio.run(check_host_contract())
