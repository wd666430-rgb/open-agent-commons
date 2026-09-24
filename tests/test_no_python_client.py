"""Optional interoperability check for the dependency-free JavaScript CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from clients.independent_client import OACClient, verify_event


ROOT = Path(__file__).resolve().parents[1]
NODE_BIN = os.environ.get("OAC_NODE_BIN") or shutil.which("node")


@pytest.mark.skipif(not NODE_BIN, reason="Node.js is not installed")
def test_javascript_client_sign_publish_read(node, tmp_path):
    _, base_url = node

    def run(*args):
        return subprocess.run(
            [NODE_BIN, str(ROOT / "clients" / "oac_js.mjs"), *args],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=True,
            timeout=20,
        )

    identity = tmp_path / "identity.json"
    event_path = tmp_path / "event.json"
    key_result = json.loads(run("keygen", "--out", str(identity)).stdout)
    assert identity.stat().st_mode & 0o777 == 0o600
    assert key_result["identity"].startswith("ed25519:")

    signed = json.loads(
        run(
            "sign", "--identity", str(identity), "--out", str(event_path),
            "--type", "contribution", "--topic", "interop",
            "--text", "No Python client / 独立测试 🙂",
        ).stdout
    )
    event = json.loads(event_path.read_text())
    assert event["id"] == signed["id"]
    verify_event(event)
    assert json.loads(run("verify", str(event_path)).stdout)["status"] == "verified"

    first = json.loads(run("publish", base_url, str(event_path)).stdout)
    assert first == {"http_status": 201, "status": "accepted", "id": event["id"], "read_back": "verified"}
    again = json.loads(run("publish", base_url, str(event_path)).stdout)
    assert again["status"] == "known"
    assert OACClient(base_url).read(event["id"]) == event
    page = json.loads(run("list", base_url).stdout)
    assert any(item["id"] == event["id"] for item in page["events"])
