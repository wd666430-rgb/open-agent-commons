from __future__ import annotations

from dataclasses import dataclass
from urllib.request import urlopen

from clients.listener import ListenerStore, dns_uri_seeds, listen_once
from oac_node.protocol import sign_event

from conftest import request_json, running_node


SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
AUTHOR = "ed25519:A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"


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
        assert b"/.well-known/oac.json" in response.read()
    with urlopen(base_url + "/llms.txt", timeout=5) as response:
        assert response.status == 200
        assert b"Verify every Event ID and Ed25519 signature" in response.read()
