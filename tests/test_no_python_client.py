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


def run_javascript_client(tmp_path, *args, check=True):
    return subprocess.run(
        [NODE_BIN, str(ROOT / "clients" / "oac_js.mjs"), *args],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=check,
        timeout=20,
    )


def json_lines(value):
    return [json.loads(line) for line in value.splitlines() if line.strip()]


def canonical_genesis():
    return json.loads(
        (ROOT / "genesis-events" / "oac-genesis-v0.1-rc1.json").read_text()
    )


@pytest.mark.skipif(not NODE_BIN, reason="Node.js is not installed")
def test_javascript_client_sign_publish_read(node, tmp_path):
    _, base_url = node

    def run(*args):
        return run_javascript_client(tmp_path, *args)

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


@pytest.mark.skipif(not NODE_BIN, reason="Node.js is not installed")
def test_javascript_listener_persists_seen_events(node, tmp_path):
    _, base_url = node
    identity = tmp_path / "identity.json"
    state = tmp_path / "listener-state.json"
    genesis = canonical_genesis()

    assert OACClient(base_url).publish(genesis)[0] == 201
    run_javascript_client(tmp_path, "keygen", "--out", str(identity))

    def publish(text, filename):
        event_path = tmp_path / filename
        run_javascript_client(
            tmp_path,
            "sign", "--identity", str(identity), "--out", str(event_path),
            "--type", "signal", "--topic", "listener-test", "--text", text,
        )
        event = json.loads(event_path.read_text())
        run_javascript_client(tmp_path, "publish", base_url, str(event_path))
        return event

    first_event = publish("first listener Event", "first-event.json")
    first = run_javascript_client(
        tmp_path,
        "listen", base_url, "--state", str(state), "--once", "--interval", "60",
    )
    assert json_lines(first.stdout) == [
        {"kind": "oac_event", "source": base_url, "event": genesis},
        {"kind": "oac_event", "source": base_url, "event": first_event},
    ]
    assert json_lines(first.stderr) == [{
        "kind": "oac_listener_status",
        "source": base_url,
        "scanned": 2,
        "new": 2,
        "known": 0,
    }]
    assert state.is_file()
    if os.name != "nt":
        assert state.stat().st_mode & 0o777 == 0o600
    saved = json.loads(state.read_text())
    assert saved["format"] == "oac-js-listener-state-v1"
    assert set(saved["seen"]) == {genesis["id"], first_event["id"]}

    repeated = run_javascript_client(
        tmp_path, "listen", base_url, "--state", str(state), "--once",
    )
    assert repeated.stdout == ""
    assert json_lines(repeated.stderr) == [{
        "kind": "oac_listener_status",
        "source": base_url,
        "scanned": 2,
        "new": 0,
        "known": 2,
    }]

    second_event = publish("second listener Event", "second-event.json")
    updated = run_javascript_client(
        tmp_path, "listen", base_url, "--state", str(state), "--once",
    )
    assert json_lines(updated.stdout) == [
        {"kind": "oac_event", "source": base_url, "event": second_event},
    ]
    assert json_lines(updated.stderr) == [{
        "kind": "oac_listener_status",
        "source": base_url,
        "scanned": 3,
        "new": 1,
        "known": 2,
    }]


@pytest.mark.skipif(not NODE_BIN, reason="Node.js is not installed")
def test_javascript_listener_rejects_corrupt_state_without_overwriting(node, tmp_path):
    _, base_url = node
    state = tmp_path / "listener-state.json"
    corrupt = b"this is not JSON\n"
    state.write_bytes(corrupt)

    result = run_javascript_client(
        tmp_path,
        "listen", base_url, "--state", str(state),
        check=False,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert state.read_bytes() == corrupt
    errors = json_lines(result.stderr)
    assert len(errors) == 1
    assert errors[0]["error"] == "invalid_listener_state"
    assert "listener state" in errors[0]["detail"]


@pytest.mark.skipif(not NODE_BIN, reason="Node.js is not installed")
def test_javascript_listener_exits_if_state_cannot_be_saved(node, tmp_path):
    _, base_url = node
    genesis = canonical_genesis()
    assert OACClient(base_url).publish(genesis)[0] == 201
    state = tmp_path / "missing-parent" / "listener-state.json"

    result = run_javascript_client(
        tmp_path,
        "listen", base_url, "--state", str(state),
        check=False,
    )

    assert result.returncode != 0
    assert not state.exists()
    assert json_lines(result.stdout) == [
        {"kind": "oac_event", "source": base_url, "event": genesis},
    ]
    errors = json_lines(result.stderr)
    assert len(errors) == 1
    assert errors[0]["error"] == "invalid_listener_state"
    assert "cannot write listener state" in errors[0]["detail"]
