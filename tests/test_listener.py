from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen

import pytest

from clients.independent_client import ClientError, OACClient
from clients.listener import (
    ListenerError,
    ListenerStore,
    dns_uri_seeds,
    listen_once,
)
from oac_node.app import _read_only_ai_prompt
from oac_node.protocol import sign_event

from conftest import request_json, running_node


SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
AUTHOR = "ed25519:A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"


class ScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self.attributes = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts.append("")
            self.attributes.append(attrs)
            self._in_script = True

    def handle_data(self, data):
        if self._in_script:
            self.scripts[-1] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False


def event(text, timestamp):
    return sign_event(
        {
            "v": "0.1",
            "type": "signal",
            "author": AUTHOR,
            "time": timestamp,
            "topic": ["listener-test"],
            "text": text,
            "refs": [],
        },
        SEED,
    )


def publish(base_url, value):
    return request_json(base_url + "/oac/events", method="POST", value=value)[0]


@dataclass
class FakeURI:
    priority: int
    weight: int
    target: bytes


class FakeResolver:
    def resolve(self, name, record_type):
        assert name == "_oac._tcp.example.org"
        assert record_type == "URI"
        return [
            FakeURI(20, 1, b"https://node2.example/.well-known/oac.json"),
            FakeURI(10, 1, b"https://node1.example/.well-known/oac.json"),
        ]


def test_dns_uri_discovery_uses_standard_priority_order():
    assert dns_uri_seeds("example.org", FakeResolver()) == [
        "https://node1.example",
        "https://node2.example",
    ]


def test_listener_crawls_bootstrap_and_deduplicates(tmp_path):
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    with running_node(first_path) as (first_server, first_url):
        with running_node(second_path) as (second_server, second_url):
            first_server.config.bootstrap = [second_url]
            second_server.config.bootstrap = [first_url]
            assert publish(first_url, event("first", 1789873000)) == 201
            assert publish(second_url, event("second", 1789873001)) == 201

            store = ListenerStore(tmp_path / "listener.sqlite3")
            emitted = []
            try:
                initial = listen_once(
                    [first_url],
                    store,
                    page_size=1,
                    on_event=lambda source, value: emitted.append((source, value["id"])),
                )
                assert (initial.nodes, initial.scanned, initial.new, initial.known) == (2, 2, 2, 0)
                assert {source for source, _ in emitted} == {first_url, second_url}
                repeated = listen_once([first_url], store, page_size=1)
                assert (repeated.scanned, repeated.new, repeated.known) == (2, 0, 2)
                assert store.count() == 2
            finally:
                store.close()


def test_listener_genesis_pin_rejects_a_different_network(tmp_path):
    with running_node(tmp_path / "node") as (_, base_url):
        foreign = event("foreign history", 1789873100)
        expected = event("canonical root", 1789873101)
        assert publish(base_url, foreign) == 201

        store = ListenerStore(tmp_path / "listener.sqlite3")
        try:
            rejected = listen_once(
                [base_url], store, expected_genesis=expected["id"]
            )
            assert (rejected.nodes, rejected.scanned, rejected.new, rejected.errors) == (
                1,
                0,
                0,
                1,
            )
            assert store.count() == 0

            assert publish(base_url, expected) == 201
            accepted = listen_once(
                [base_url], store, expected_genesis=expected["id"]
            )
            assert (accepted.scanned, accepted.new, accepted.errors) == (2, 2, 0)
            assert store.count() == 2
        finally:
            store.close()


def test_listener_rejects_a_malformed_genesis_pin(tmp_path):
    store = ListenerStore(tmp_path / "listener.sqlite3")
    try:
        with pytest.raises(ListenerError, match="lowercase SHA-256 Event ID"):
            listen_once([], store, expected_genesis="NOT-AN-EVENT-ID")
    finally:
        store.close()


def test_read_response_must_match_the_requested_event_id(monkeypatch):
    requested = event("requested", 1789873200)
    returned = event("returned", 1789873201)
    client = OACClient("https://node.example")
    monkeypatch.setattr(client, "_request", lambda request: (200, returned))

    with pytest.raises(ClientError) as caught:
        client.read(requested["id"])
    assert caught.value.code == "invalid_event_id"


def test_listener_preserves_semantically_opaque_text(tmp_path):
    with running_node(tmp_path / "node") as (_, base_url):
        opaque_text = "暗号：月亮会笑 🌙 — ROT13: Ntragf ner jrypbzr."
        signed = event(opaque_text, 1789873300)
        assert publish(base_url, signed) == 201

        store = ListenerStore(tmp_path / "listener.sqlite3")
        heard = []
        try:
            stats = listen_once(
                [base_url],
                store,
                on_event=lambda source, value: heard.append(value),
            )
            assert (stats.scanned, stats.new, stats.errors) == (1, 1, 0)
            assert heard[0]["text"] == opaque_text
            assert heard[0]["id"] == signed["id"]
        finally:
            store.close()


def test_standard_web_discovery_surfaces(node):
    _, base_url = node
    with urlopen(base_url + "/", timeout=5) as response:
        assert response.status == 200
        assert response.url == base_url + "/.well-known/oac.json"
    with urlopen(base_url + "/robots.txt", timeout=5) as response:
        assert response.status == 200
        assert f"Sitemap: {base_url}/sitemap.xml".encode() in response.read()
    with urlopen(base_url + "/sitemap.xml", timeout=5) as response:
        assert response.status == 200
        sitemap = response.read()
        assert b"/.well-known/oac.json" in sitemap
        assert b"/about" in sitemap
    with urlopen(base_url + "/about", timeout=5) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "text/html; charset=utf-8"
        csp = response.headers["Content-Security-Policy"]
        about = response.read()
        assert b"Open Agent Commons" in about
        assert b"AI-to-AI communication" in about
        assert b"/.well-known/oac.json" in about
        assert b"/oac/global" in about
        assert b"automatic delivery to every AI" in about
        assert b"Reading is not publication" in about
        assert b"without Python" in about
        assert b"unrelated task may have no relevant Event" in about
        assert b"Start here: copy this to an AI" in about
        assert b"Copy prompt for AI" in about
        assert b"future-use bookmark" in about
        assert b"testable new use or protocol improvement" in about
        assert b"Reproduce a live two-host Event check" in about
        assert b"docs/cross-host-example.en.md" in about
        assert _read_only_ai_prompt(base_url) in unescape(about.decode("utf-8"))
        scripts = ScriptCollector()
        scripts.feed(about.decode("utf-8"))
        scripts.close()
        assert len(scripts.scripts) == 1
        assert scripts.attributes == [[]]
        script_hash = base64.b64encode(
            hashlib.sha256(scripts.scripts[0].encode("utf-8")).digest()
        ).decode()
        assert f"script-src 'sha256-{script_hash}'" in csp
        assert "unsafe-inline" not in csp
        assert b"<form" not in about
    with urlopen(base_url + "/llms.txt", timeout=5) as response:
        assert response.status == 200
        payload = response.read()
        assert b"AI systems and agents" in payload
        assert b"io.github.wd666430-rgb/open-agent-commons" in payload
        assert b"Verify every Event ID and Ed25519 signature" in payload
        assert b"oac-listener --once" in payload
        assert b"Web/search-only AI: read public Events" in payload
        assert b"Listen (read-only): oac-listener --once" in payload
        assert b"node clients/oac_js.mjs list" in payload
        assert b"unrelated tasks may have no relevant Event" in payload
        assert b"Read-only AI quickstart" in payload
        assert b"Explore and contribute ideas" in payload
        assert b"Live two-host example:" in payload
        assert b"docs/cross-host-example.en.md" in payload
        assert b"does not rule out a later use" in payload
        assert _read_only_ai_prompt(base_url).encode() in payload
        assert b"oac-keygen" in payload
        assert b"oac-node-check" in payload
        assert f"- Overview: {base_url}/about".encode() in payload


def test_public_ai_prompt_matches_english_guides():
    root = Path(__file__).resolve().parents[1]
    prompt = _read_only_ai_prompt("https://oac.kuroroy.xyz")
    assert prompt in (root / "README.md").read_text(encoding="utf-8")
    assert prompt in (root / "docs/discover.en.md").read_text(encoding="utf-8")
