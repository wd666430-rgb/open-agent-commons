from __future__ import annotations

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
