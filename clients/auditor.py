#!/usr/bin/env python3
"""Passive OAC continuity auditor built from the four Genesis operations.

The auditor observes independently verified Event sets. It never blocks
publication, assigns membership, or treats temporary divergence as proof of
misconduct.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from clients.independent_client import ClientError, OACClient
from clients.listener import (
    CANONICAL_GENESIS_ID,
    DEFAULT_DNS_DOMAINS,
    DEFAULT_HTTPS_SEEDS,
    ListenerError,
    discover_network,
    dns_uri_seeds,
)


class AuditError(ValueError):
    pass


@dataclass
class NodeAudit:
    node: str
    event_count: int = 0
    set_sha256: Optional[str] = None
    missing_from_union: List[str] = field(default_factory=list)
    missing_from_previous: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class AuditReport:
    status: str
    network_genesis: Optional[str]
    observed_at: int
    nodes: List[NodeAudit]
    discovery_errors: List[str]


class AuditStore:
    """Keep the last non-regressing Event set for each Node."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS node_events (
                node TEXT NOT NULL,
                event_id TEXT NOT NULL,
                PRIMARY KEY (node, event_id)
            );
            CREATE TABLE IF NOT EXISTS observations (
                observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_at INTEGER NOT NULL,
                node TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                set_sha256 TEXT NOT NULL,
                result TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def trusted_ids(self, node: str) -> Set[str]:
        rows = self.connection.execute(
            "SELECT event_id FROM node_events WHERE node = ?", (node,)
        )
        return {str(row[0]) for row in rows}

    def observe(
        self,
        node: str,
        event_ids: Set[str],
        set_sha256: str,
        observed_at: int,
    ) -> List[str]:
        previous = self.trusted_ids(node)
        missing = sorted(previous - event_ids)
        result = "history_regression" if missing else "accepted"
        with self.connection:
            self.connection.execute(
                "INSERT INTO observations(observed_at, node, event_count, set_sha256, result) "
                "VALUES (?, ?, ?, ?, ?)",
                (observed_at, node, len(event_ids), set_sha256, result),
            )
            if not missing:
                self.connection.execute("DELETE FROM node_events WHERE node = ?", (node,))
                self.connection.executemany(
                    "INSERT INTO node_events(node, event_id) VALUES (?, ?)",
                    ((node, event_id) for event_id in sorted(event_ids)),
                )
        return missing

    def close(self) -> None:
        self.connection.close()


def event_set_digest(event_ids: Set[str]) -> str:
    """Hash a set of fixed-width Event IDs without depending on Node order."""
    digest = hashlib.sha256()
    digest.update(b"oac-event-set-v1\x00")
    for event_id in sorted(event_ids):
        try:
            digest.update(bytes.fromhex(event_id))
        except ValueError as error:
            raise AuditError("invalid Event ID in verified set") from error
    return digest.hexdigest()


def scan_node(
    node: str,
    *,
    expected_genesis: Optional[str],
    page_size: int,
    max_pages: int,
) -> Set[str]:
    client = OACClient(node)
    if expected_genesis is not None:
        client.read(expected_genesis)

    event_ids: Set[str] = set()
    cursor: Optional[str] = None
    observed_cursors = set()
    for _ in range(max_pages):
        page = client.global_page(cursor=cursor, limit=page_size)
        events = page.get("events")
        next_cursor = page.get("cursor")
        if not isinstance(events, list):
            raise AuditError(f"{node} returned an invalid GLOBAL page")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise AuditError(f"{node} returned an invalid cursor")
        event_ids.update(event["id"] for event in events)
        if next_cursor is None:
            if expected_genesis is not None and expected_genesis not in event_ids:
                raise AuditError(f"{node} omitted the expected Genesis Event from GLOBAL")
            return event_ids
        if next_cursor in observed_cursors:
            raise AuditError(f"{node} repeated a cursor")
        observed_cursors.add(next_cursor)
        cursor = next_cursor
    raise AuditError(f"{node} exceeded max_pages")


def audit_network(
    seeds: Iterable[str],
    store: AuditStore,
    *,
    expected_genesis: Optional[str] = CANONICAL_GENESIS_ID,
    page_size: int = 100,
    max_nodes: int = 32,
    max_pages: int = 10_000,
    observed_at: Optional[int] = None,
) -> AuditReport:
    if not 1 <= page_size <= 500:
        raise AuditError("page_size must be 1..500")
    if max_pages < 1:
        raise AuditError("max_pages must be positive")
    if expected_genesis is not None and (
        len(expected_genesis) != 64
        or any(character not in "0123456789abcdef" for character in expected_genesis)
    ):
        raise AuditError("expected_genesis must be a lowercase SHA-256 Event ID")

    manifests, discovery_errors = discover_network(seeds, max_nodes=max_nodes)
    timestamp = int(time.time()) if observed_at is None else observed_at
    results: List[NodeAudit] = []
    verified_sets: Dict[str, Set[str]] = {}

    for node in manifests:
        result = NodeAudit(node=node)
        try:
            event_ids = scan_node(
                node,
                expected_genesis=expected_genesis,
                page_size=page_size,
                max_pages=max_pages,
            )
            result.event_count = len(event_ids)
            result.set_sha256 = event_set_digest(event_ids)
            result.missing_from_previous = store.observe(
                node, event_ids, result.set_sha256, timestamp
            )
            verified_sets[node] = event_ids
        except (AuditError, ClientError, ListenerError, OSError, ValueError, KeyError) as error:
            result.error = str(error)
        results.append(result)

    union = set().union(*verified_sets.values()) if verified_sets else set()
    for result in results:
        if result.node in verified_sets:
            result.missing_from_union = sorted(union - verified_sets[result.node])

    if any(result.missing_from_previous for result in results):
        status = "history_regression"
    elif discovery_errors or any(result.error for result in results):
        status = "degraded"
    elif len(verified_sets) < 2:
        status = "insufficient_independent_nodes"
    elif any(result.missing_from_union for result in results):
        status = "divergent"
    else:
        status = "converged"

    return AuditReport(
        status=status,
        network_genesis=expected_genesis,
        observed_at=timestamp,
        nodes=results,
        discovery_errors=discovery_errors,
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Passively audit OAC Node continuity")
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--dns-domain", action="append", default=[])
    parser.add_argument("--state", type=Path, default=Path("oac-auditor.sqlite3"))
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-nodes", type=int, default=32)
    parser.add_argument("--max-pages", type=int, default=10_000)
    parser.add_argument("--expected-genesis", default=CANONICAL_GENESIS_ID)
    parser.add_argument("--no-genesis-pin", action="store_true")
    args = parser.parse_args(argv)

    domains = args.dns_domain or list(DEFAULT_DNS_DOMAINS)
    seeds = list(args.seed)
    for domain in domains:
        seeds.extend(dns_uri_seeds(domain))
    if not seeds:
        seeds.extend(DEFAULT_HTTPS_SEEDS)
    seeds = list(dict.fromkeys(seeds))

    store = AuditStore(args.state)
    try:
        report = audit_network(
            seeds,
            store,
            expected_genesis=None if args.no_genesis_pin else args.expected_genesis,
            page_size=args.page_size,
            max_nodes=args.max_nodes,
            max_pages=args.max_pages,
        )
    except (AuditError, ClientError, ListenerError, OSError, ValueError, KeyError) as error:
        print(
            json.dumps(
                {"error": "audit_failed", "detail": str(error)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        store.close()

    print(json.dumps(asdict(report), ensure_ascii=False, separators=(",", ":")))
    return 0 if report.status == "converged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
