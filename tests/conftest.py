from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from oac_node.app import NodeConfig, create_server


@contextmanager
def running_node(tmp_path, **config_overrides):
    config_values = {
        "database": str(tmp_path / "events.sqlite3"),
        "spec_url": "https://spec.example/oac/0.1",
        "spec_path": str(Path(__file__).resolve().parents[1] / "docs" / "spec.en.md"),
    }
    config_values.update(config_overrides)
    server = create_server(
        "127.0.0.1",
        0,
        NodeConfig(**config_values),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield server, f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture
def node(tmp_path):
    with running_node(tmp_path) as value:
        yield value


def request_json(url, *, method="GET", value=None, raw=None, content_type="application/json"):
    data = raw
    if value is not None:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(url, data=data, method=method)
    if data is not None and content_type is not None:
        request.add_header("Content-Type", content_type)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)
