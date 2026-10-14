from __future__ import annotations

import json
from urllib.request import Request, urlopen

from conftest import request_json, running_node
from oac_node.__main__ import parser


def test_cli_accepts_existing_local_log_argument():
    assert parser().parse_args(["--attribution-log", "access.jsonl"]).attribution_log == "access.jsonl"


def test_optional_access_log_preserves_discovery_and_scrubs_referrer(tmp_path):
    log = tmp_path / "access.jsonl"
    with running_node(tmp_path, attribution_log=str(log)) as (_, base_url):
        request = Request(
            base_url + "/.well-known/oac.json",
            headers={"Referer": "https://user:secret@chatgpt.com/private?token=hidden"},
        )
        with urlopen(request, timeout=5) as response:
            manifest = json.load(response)
            assert response.headers["Connection"] == "close"
        assert set(manifest) == {"oac", "release", "spec", "global", "events", "bootstrap"}
    row = json.loads(log.read_text().splitlines()[0])
    assert row["endpoint"] == "/.well-known/oac.json"
    assert row["referrer"] == "https://chatgpt.com"
    assert row["status"] == 200
    assert "ip" not in row
    assert "secret" not in log.read_text()
    assert "hidden" not in log.read_text()


def test_optional_access_log_rotates_and_does_not_affect_response(tmp_path):
    log = tmp_path / "access.jsonl"
    with log.open("wb") as handle:
        handle.truncate(64 * 1024 * 1024)
    with running_node(tmp_path, attribution_log=str(log)) as (_, base_url):
        status, manifest = request_json(base_url + "/.well-known/oac.json")
    assert status == 200
    assert manifest["oac"] == "0.1"
    assert (tmp_path / "access.jsonl.1").exists()
    assert json.loads(log.read_text().splitlines()[0])["status"] == 200
