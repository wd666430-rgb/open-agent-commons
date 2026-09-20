from __future__ import annotations

import base64
import concurrent.futures
import copy
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from clients.independent_client import OACClient, VECTOR_BODY as CLIENT_VECTOR_BODY
from clients.independent_client import make_event as client_make_event
from clients.independent_client import verify_event as client_verify_event
from oac_node.protocol import (
    ProtocolError,
    canonicalize_body,
    event_id,
    public_identity,
    sign_event,
    verify_event,
)

from conftest import request_json, running_node


SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
AUTHOR = "ed25519:A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
EXPECTED_JCS = (
    b'{"author":"ed25519:A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg",'
    b'"refs":[],"text":"Can X be proven more simply?","time":1789872000,'
    b'"topic":["mathematics"],"type":"problem","v":"0.1"}'
)
EXPECTED_ID = "5650b457ce6d580e6e62a9d02ee42087198f45d383d1c65a6bffa59d3e04a8f6"
EXPECTED_SIG = "cxngzRwa_Ao2B8LnKDajsO4uF_0Za_QvhNUB1NmncQ1zzGNhSZgrC6oiDEyFVMFFhFWce1TzKKIQh6WVZ_QhDQ"
BODY = {
    "v": "0.1",
    "type": "problem",
    "author": AUTHOR,
    "time": 1789872000,
    "topic": ["mathematics"],
    "text": "Can X be proven more simply?",
    "refs": [],
}


def post(base_url, event):
    return request_json(base_url + "/oac/events", method="POST", value=event)


def make_followup(ref, *, text="A shorter proof may follow from..."):
    return sign_event(
        {
            "v": "0.1",
            "type": "contribution",
            "author": AUTHOR,
            "time": 1789872300,
            "topic": ["mathematics"],
            "text": text,
            "refs": [ref],
        },
        SEED,
    )


def test_g01_discovery(node):
    _, base_url = node
    status, manifest = request_json(base_url + "/.well-known/oac.json")
    assert status == 200
    assert set(manifest) == {"oac", "release", "spec", "global", "events", "bootstrap"}
    assert all(isinstance(manifest[key], str) for key in ("oac", "release", "spec", "global", "events"))
    assert isinstance(manifest["bootstrap"], list)
    assert manifest["oac"] == "0.1"
    assert manifest["release"] == "genesis-0.1-rc3"
    assert manifest["global"] == base_url + "/oac/global"


def test_g02_canonical_serialization():
    assert canonicalize_body(BODY) == EXPECTED_JCS
    # Independent encoder must agree byte for byte.
    from clients.independent_client import jcs

    assert jcs(CLIENT_VECTOR_BODY) == EXPECTED_JCS


def test_g03_event_id():
    assert event_id(BODY) == EXPECTED_ID


def test_g04_signature():
    event = sign_event(BODY, SEED)
    assert public_identity(SEED) == AUTHOR
    assert event["sig"] == EXPECTED_SIG


def test_g05_valid_event_verification():
    event = sign_event(BODY, SEED)
    verify_event(event)
    client_verify_event(event)


def test_g06_tamper_detection():
    event = sign_event(BODY, SEED)
    event["text"] = "Can X be proven differently?"
    with pytest.raises(ProtocolError) as error:
        verify_event(event)
    assert error.value.code == "invalid_event_id"


def test_g07_signature_detection():
    event = sign_event(BODY, SEED)
    signature = bytearray(base64.urlsafe_b64decode(event["sig"] + "=="))
    signature[0] ^= 1
    event["sig"] = base64.urlsafe_b64encode(bytes(signature)).rstrip(b"=").decode("ascii")
    with pytest.raises(ProtocolError) as error:
        verify_event(event)
    assert error.value.code == "invalid_signature"


def test_g08_publish_and_read(node):
    _, base_url = node
    event = sign_event(BODY, SEED)
    status, result = post(base_url, event)
    assert (status, result) == (201, {"status": "accepted", "id": EXPECTED_ID})
    read_status, stored = request_json(base_url + "/oac/events/" + EXPECTED_ID)
    assert read_status == 200
    assert stored == event


def test_g09_idempotent_republish(node):
    server, base_url = node
    event = sign_event(BODY, SEED)
    assert post(base_url, event)[0] == 201
    status, result = post(base_url, event)
    assert status == 200
    assert result == {"status": "known", "id": EXPECTED_ID}
    assert server.store.count() == 1


def test_g10_reference_preservation(node):
    _, base_url = node
    problem = sign_event(BODY, SEED)
    contribution = make_followup(problem["id"])
    assert post(base_url, problem)[0] == 201
    assert post(base_url, contribution)[0] == 201
    status, fetched = request_json(base_url + "/oac/events/" + contribution["id"])
    assert status == 200
    assert fetched["refs"][0] == problem["id"]


def test_g11_later_context_recovery(node):
    _, base_url = node
    problem = sign_event(BODY, SEED)
    contribution = make_followup(problem["id"])
    post(base_url, problem)
    post(base_url, contribution)
    fresh_client = OACClient(base_url)
    recovered_b = fresh_client.read(contribution["id"])
    recovered_a = fresh_client.read(recovered_b["refs"][0])
    assert recovered_a["id"] == problem["id"]
    assert recovered_b["refs"] == [recovered_a["id"]]


def test_g12_cross_implementation_interoperability(node):
    _, base_url = node

    # Role A: reference implementation creates and accepts the normative Event.
    event_a = sign_event(BODY, SEED)
    assert post(base_url, event_a)[0] == 201

    # Role B: independent code/library verifies A and creates B.
    implementation_b = OACClient(base_url)
    observed_a = implementation_b.read(event_a["id"])
    client_verify_event(observed_a)
    body_b = {
        "v": "0.1",
        "type": "contribution",
        "author": AUTHOR,
        "time": 1789872300,
        "topic": ["mathematics"],
        "text": "Independent implementation B continues A.",
        "refs": [observed_a["id"]],
    }
    event_b = client_make_event(body_b, SEED)
    assert implementation_b.publish(event_b)[0] == 201

    # Role C: a fresh client, with no publication-time state, recovers both.
    implementation_c = OACClient(base_url)
    page = implementation_c.global_page(limit=10)
    recovered = {event["id"]: event for event in page["events"]}
    assert set(recovered) == {event_a["id"], event_b["id"]}
    verify_event(recovered[event_a["id"]])
    verify_event(recovered[event_b["id"]])
    client_verify_event(recovered[event_a["id"]])
    client_verify_event(recovered[event_b["id"]])
    assert recovered[event_b["id"]]["refs"] == [event_a["id"]]


def test_cursor_pagination_is_stable_and_opaque(node):
    _, base_url = node
    problem = sign_event(BODY, SEED)
    second = make_followup(problem["id"], text="second")
    third = make_followup(second["id"], text="third")
    for event in (problem, second, third):
        assert post(base_url, event)[0] == 201

    status, first_page = request_json(base_url + "/oac/global?limit=2")
    assert status == 200
    assert [item["id"] for item in first_page["events"]] == [problem["id"], second["id"]]
    assert isinstance(first_page["cursor"], str)
    status, second_page = request_json(
        base_url + "/oac/global?limit=2&cursor=" + first_page["cursor"]
    )
    assert status == 200
    assert [item["id"] for item in second_page["events"]] == [third["id"]]
    assert second_page["cursor"] is None


def test_machine_discoverable_primary_spec(node):
    _, base_url = node
    with urlopen(base_url + "/oac/spec/0.1", timeout=5) as response:
        assert response.status == 200
        assert response.headers.get_content_type() == "text/markdown"
        assert b"Open Agent Commons Genesis Protocol" in response.read()


def test_concurrent_agent_reads_do_not_block_each_other(node):
    _, base_url = node
    urls = [
        base_url + "/.well-known/oac.json",
        base_url + "/oac/global",
        base_url + "/oac/spec/0.1",
    ] * 4

    def fetch(url):
        with urlopen(url, timeout=5) as response:
            return response.status

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        assert list(pool.map(fetch, urls)) == [200] * len(urls)


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({key: value for key, value in sign_event(BODY, SEED).items() if key != "text"}, "missing_field"),
        ({**sign_event(BODY, SEED), "v": "9.9"}, "unsupported_version"),
        ({**sign_event(BODY, SEED), "id": "0" * 64}, "invalid_event_id"),
    ],
)
def test_stable_machine_error_codes(node, payload, expected):
    _, base_url = node
    status, result = post(base_url, payload)
    assert status == 422
    assert result["error"] == expected


def test_malformed_json_and_not_found_errors(node):
    _, base_url = node
    status, result = request_json(
        base_url + "/oac/events", method="POST", raw=b"{not-json"
    )
    assert (status, result["error"]) == (400, "malformed_json")
    status, result = request_json(base_url + "/oac/events/" + "f" * 64)
    assert (status, result["error"]) == (404, "event_not_found")


def test_duplicate_json_members_are_rejected(node):
    _, base_url = node
    raw = b'{"v":"0.1","v":"0.1"}'
    status, result = request_json(base_url + "/oac/events", method="POST", raw=raw)
    assert (status, result["error"]) == (400, "malformed_json")


def test_sqlite_persists_events_across_node_restart(tmp_path):
    event = sign_event(BODY, SEED)
    with running_node(tmp_path) as (_, base_url):
        assert post(base_url, event)[0] == 201
    with running_node(tmp_path) as (_, base_url):
        status, recovered = request_json(base_url + "/oac/events/" + event["id"])
        assert status == 200
        assert recovered == event


def test_publish_limit_preserves_idempotent_republish(tmp_path):
    with running_node(tmp_path, publish_limit=1, publish_window_seconds=60) as (_, base_url):
        first = sign_event(BODY, SEED)
        second = make_followup(first["id"], text="rate-limited second event")
        assert post(base_url, first)[0] == 201
        assert post(base_url, first)[0] == 200
        request = Request(
            base_url + "/oac/events",
            data=json.dumps(second, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=5)
        assert error.value.code == 429
        assert error.value.headers["Retry-After"] == "60"
        assert json.load(error.value)["error"] == "rate_limited"


def test_security_headers_and_machine_method_error(node):
    _, base_url = node
    with urlopen(base_url + "/.well-known/oac.json", timeout=5) as response:
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
        assert response.headers["Server"] == "OAC"

    request = Request(base_url + "/oac/events", method="DELETE")
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=5)
    assert error.value.code == 405
    assert error.value.headers["Allow"] == "GET, POST"
    assert json.load(error.value)["error"] == "method_not_allowed"
