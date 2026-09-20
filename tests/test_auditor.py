from __future__ import annotations

from clients.auditor import AuditStore, audit_network, event_set_digest
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
            "topic": ["auditor-test"],
            "text": text,
            "refs": [],
        },
        SEED,
    )


def publish(base_url, value):
    return request_json(base_url + "/oac/events", method="POST", value=value)[0]


def test_auditor_reports_divergence_then_convergence(tmp_path):
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    with running_node(first_path) as (_, first_url):
        with running_node(second_path) as (_, second_url):
            genesis = event("canonical root", 1789874000)
            first_only = event("first only", 1789874001)
            second_only = event("second only", 1789874002)
            for node in (first_url, second_url):
                assert publish(node, genesis) == 201
            assert publish(first_url, first_only) == 201
            assert publish(second_url, second_only) == 201

            store = AuditStore(tmp_path / "auditor.sqlite3")
            try:
                divergent = audit_network(
                    [first_url, second_url],
                    store,
                    expected_genesis=genesis["id"],
                    observed_at=1789874100,
                )
                assert divergent.status == "divergent"
                by_node = {result.node: result for result in divergent.nodes}
                assert by_node[first_url].missing_from_union == [second_only["id"]]
                assert by_node[second_url].missing_from_union == [first_only["id"]]

                assert publish(first_url, second_only) == 201
                assert publish(second_url, first_only) == 201
                converged = audit_network(
                    [first_url, second_url],
                    store,
                    expected_genesis=genesis["id"],
                    observed_at=1789874200,
                )
                assert converged.status == "converged"
                assert {result.event_count for result in converged.nodes} == {3}
                assert {result.set_sha256 for result in converged.nodes} == {
                    event_set_digest({
                        genesis["id"],
                        first_only["id"],
                        second_only["id"],
                    })
                }
            finally:
                store.close()


def test_auditor_preserves_last_non_regressing_history(tmp_path):
    store = AuditStore(tmp_path / "auditor.sqlite3")
    first = "00" * 32
    second = "11" * 32
    try:
        assert store.observe(
            "https://node.example", {first, second}, event_set_digest({first, second}), 1
        ) == []
        assert store.observe(
            "https://node.example", {first}, event_set_digest({first}), 2
        ) == [second]
        assert store.trusted_ids("https://node.example") == {first, second}
    finally:
        store.close()


def test_auditor_degrades_when_a_node_lacks_the_expected_genesis(tmp_path):
    with running_node(tmp_path / "node") as (_, base_url):
        expected = event("expected root", 1789874300)
        assert publish(base_url, event("unrelated", 1789874301)) == 201

        store = AuditStore(tmp_path / "auditor.sqlite3")
        try:
            report = audit_network(
                [base_url], store, expected_genesis=expected["id"]
            )
            assert report.status == "degraded"
            assert report.nodes[0].event_count == 0
            assert report.nodes[0].error
        finally:
            store.close()
