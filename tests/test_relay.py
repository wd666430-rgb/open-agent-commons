from __future__ import annotations

from clients.independent_client import OACClient
from clients.relay import relay_once, relay_pair
from oac_node.protocol import sign_event

from conftest import request_json, running_node


SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
AUTHOR = "ed25519:A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"


def event(text, timestamp, refs=None):
    return sign_event(
        {
            "v": "0.1",
            "type": "signal",
            "author": AUTHOR,
            "time": timestamp,
            "topic": ["relay-test"],
            "text": text,
            "refs": refs or [],
        },
        SEED,
    )


def publish(base_url, value):
    return request_json(base_url + "/oac/events", method="POST", value=value)[0]


def test_one_way_relay_is_verified_and_idempotent(tmp_path):
    source_path = tmp_path / "source"
    destination_path = tmp_path / "destination"
    source_path.mkdir()
    destination_path.mkdir()
    with running_node(source_path) as (_, source):
        with running_node(destination_path) as (_, destination):
            first = event("first", 1789872000)
            second = event("second", 1789872001, [first["id"]])
            assert publish(source, first) == 201
            assert publish(source, second) == 201

            initial = relay_once(source, destination, page_size=1)
            assert (initial.scanned, initial.accepted, initial.known) == (2, 2, 0)
            repeated = relay_once(source, destination, page_size=1)
            assert (repeated.scanned, repeated.accepted, repeated.known) == (2, 0, 2)
            assert OACClient(destination).read(second["id"])["refs"] == [first["id"]]


def test_bidirectional_relay_converges_two_nodes(tmp_path):
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    with running_node(first_path) as (_, first_url):
        with running_node(second_path) as (_, second_url):
            first = event("from first", 1789872100)
            second = event("from second", 1789872101, [first["id"]])
            assert publish(first_url, first) == 201
            assert publish(second_url, second) == 201

            result = relay_pair(first_url, second_url, page_size=1)
            assert result["first_to_second"].accepted == 1
            assert result["second_to_first"].accepted == 1
            expected = {first["id"], second["id"]}
            for url in (first_url, second_url):
                observed = {item["id"] for item in OACClient(url).global_page()["events"]}
                assert observed == expected
