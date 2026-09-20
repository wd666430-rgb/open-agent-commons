from __future__ import annotations

import json
import stat
from pathlib import Path
from oac_node.participant import (
    CANONICAL_GENESIS,
    check_node,
    create_signed_event,
    generate_identity,
    keygen_main,
    load_identity,
    node_check_main,
    sign_main,
    verify_main,
)
from oac_node.protocol import verify_event

from conftest import request_json, running_node


def canonical_genesis():
    event = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "genesis-events"
            / "oac-genesis-v0.1-rc1.json"
        ).read_text(encoding="utf-8")
    )
    assert event["id"] == CANONICAL_GENESIS
    return event


def test_identity_sign_and_verify_round_trip(tmp_path):
    identity_path = tmp_path / "private" / "identity.json"
    identity = generate_identity(identity_path)
    assert identity.startswith("ed25519:")
    assert stat.S_IMODE(identity_path.stat().st_mode) == 0o600
    seed, loaded_identity = load_identity(identity_path)
    assert len(seed) == 32
    assert loaded_identity == identity

    event = create_signed_event(
        identity_path,
        event_type="contribution",
        timestamp=1789927000,
        topics=["onboarding", "中文"],
        text="Hello OAC — 你好。",
        refs=[CANONICAL_GENESIS],
    )
    verify_event(event)
    assert event["author"] == identity
    assert event["refs"] == [CANONICAL_GENESIS]


def test_onboarding_commands_are_machine_readable_and_refuse_overwrite(tmp_path, capsys):
    identity_path = tmp_path / "identity.json"
    event_path = tmp_path / "event.json"

    assert keygen_main([str(identity_path)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "created"
    assert keygen_main([str(identity_path)]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "identity_exists"

    assert sign_main(
        [
            "--identity",
            str(identity_path),
            "--output",
            str(event_path),
            "--type",
            "proposal",
            "--topic",
            "onboarding",
            "--text",
            "Make first participation easy.",
            "--ref",
            CANONICAL_GENESIS,
        ]
    ) == 0
    signed = json.loads(capsys.readouterr().out)
    assert signed["status"] == "signed"

    assert verify_main([str(event_path)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified == {
        "status": "valid",
        "id": signed["id"],
        "author": created["identity"],
    }


def test_node_check_confirms_history_bootstrap_and_idempotent_publish(tmp_path):
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    with running_node(first_path) as (first_server, first_url):
        with running_node(second_path) as (second_server, second_url):
            first_server.config.bootstrap = [second_url]
            second_server.config.bootstrap = [first_url]
            first_server.config.spec_url = first_url + "/oac/spec/0.1"
            second_server.config.spec_url = second_url + "/oac/spec/0.1"
            genesis = canonical_genesis()
            assert request_json(first_url + "/oac/events", method="POST", value=genesis)[0] == 201
            assert request_json(second_url + "/oac/events", method="POST", value=genesis)[0] == 201

            result = check_node(first_url, check_publish=True)
            assert result["status"] == "ready"
            assert result["event_count"] == 1
            assert result["reachable_bootstrap_count"] == 1
            assert result["publish_check"] == "known"


def test_node_check_reports_missing_genesis(tmp_path, capsys):
    with running_node(tmp_path / "node") as (_, base_url):
        assert node_check_main([base_url, "--standalone"]) == 1
        result = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
        assert result["status"] == "not_ready"
        assert result["error"] == "missing_genesis"
