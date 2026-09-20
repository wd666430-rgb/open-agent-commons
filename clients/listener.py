#!/usr/bin/env python3
"""Persistent OAC listener with DNS and bootstrap discovery."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

import dns.exception
import dns.resolver

from clients.independent_client import ClientError, OACClient


DEFAULT_DNS_DOMAINS = ("kuroroy.xyz",)
DEFAULT_HTTPS_SEEDS = (
    "https://oac.kuroroy.xyz",
    "https://node2.kuroroy.xyz",
)
DISCOVERY_PATH = "/.well-known/oac.json"


class ListenerError(ValueError):
    pass


@dataclass
class ListenStats:
    nodes: int = 0
    scanned: int = 0
    new: int = 0
    known: int = 0
    errors: int = 0


class ListenerStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                first_seen INTEGER NOT NULL,
                event_json TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def add(self, event: Mapping[str, Any], source: str) -> bool:
        payload = json.dumps(dict(event), ensure_ascii=False, separators=(",", ":"))
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO events(event_id, source, first_seen, event_json) "
            "VALUES (?, ?, ?, ?)",
            (event["id"], source, int(time.time()), payload),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def close(self) -> None:
        self.connection.close()


def _base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ListenerError(f"invalid Node URL: {value}")
    if parsed.query or parsed.fragment:
        raise ListenerError(f"Node URL must not contain query or fragment: {value}")
    path = parsed.path.rstrip("/")
    if path and path != DISCOVERY_PATH:
        raise ListenerError(f"unsupported Node URL path: {value}")
    return f"{parsed.scheme}://{parsed.netloc}"


def dns_uri_seeds(domain: str, resolver: Optional[dns.resolver.Resolver] = None) -> List[str]:
    """Resolve RFC 7553 URI records at the provisional OAC service label."""
    resolver = resolver or dns.resolver.Resolver()
    name = f"_oac._tcp.{domain.rstrip('.')}"
    try:
        answers = resolver.resolve(name, "URI")
    except (dns.exception.DNSException, OSError):
        return []
    records: List[Tuple[int, int, str]] = []
    for answer in answers:
        target = answer.target
        if isinstance(target, bytes):
            target = target.decode("utf-8")
        records.append((int(answer.priority), -int(answer.weight), _base_url(str(target))))
    return [target for _, _, target in sorted(records)]


def _validate_manifest(manifest: Mapping[str, Any], node: str) -> None:
    required = {"oac", "release", "spec", "global", "events", "bootstrap"}
    if not isinstance(manifest, Mapping) or set(manifest) != required:
        raise ListenerError(f"{node} returned an invalid discovery manifest")
    if manifest["oac"] != "0.1":
        raise ListenerError(f"{node} does not support OAC 0.1")
    if not isinstance(manifest["bootstrap"], list) or any(
        not isinstance(value, str) for value in manifest["bootstrap"]
    ):
        raise ListenerError(f"{node} returned invalid bootstrap entries")


def discover_network(
    seeds: Iterable[str], *, max_nodes: int = 32
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    if max_nodes < 1:
        raise ListenerError("max_nodes must be positive")
    queue = deque(_base_url(seed) for seed in seeds)
    queued = set(queue)
    manifests: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    while queue and len(manifests) < max_nodes:
        node = queue.popleft()
        try:
            manifest = OACClient(node).discover()
            _validate_manifest(manifest, node)
        except (ClientError, ListenerError, OSError, ValueError, KeyError) as error:
            errors.append(f"{node}: {error}")
            continue
        manifests[node] = manifest
        for value in manifest["bootstrap"]:
            try:
                peer = _base_url(value)
            except ListenerError as error:
                errors.append(f"{node}: {error}")
                continue
            if peer not in queued and len(queued) < max_nodes:
                queued.add(peer)
                queue.append(peer)
    if not manifests:
        raise ListenerError("no OAC Node could be discovered")
    return manifests, errors


def listen_once(
    seeds: Iterable[str],
    store: ListenerStore,
    *,
    page_size: int = 100,
    max_nodes: int = 32,
    max_pages: int = 10_000,
    on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> ListenStats:
    if not 1 <= page_size <= 500:
        raise ListenerError("page_size must be 1..500")
    manifests, discovery_errors = discover_network(seeds, max_nodes=max_nodes)
    stats = ListenStats(nodes=len(manifests), errors=len(discovery_errors))
    for node in manifests:
        cursor: Optional[str] = None
        observed_cursors = set()
        try:
            for _ in range(max_pages):
                page = OACClient(node).global_page(cursor=cursor, limit=page_size)
                events = page.get("events")
                next_cursor = page.get("cursor")
                if not isinstance(events, list):
                    raise ListenerError(f"{node} returned an invalid GLOBAL page")
                if next_cursor is not None and not isinstance(next_cursor, str):
                    raise ListenerError(f"{node} returned an invalid cursor")
                for event in events:
                    stats.scanned += 1
                    if store.add(event, node):
                        stats.new += 1
                        if on_event is not None:
                            on_event(node, event)
                    else:
                        stats.known += 1
                if next_cursor is None:
                    break
                if next_cursor in observed_cursors:
                    raise ListenerError(f"{node} repeated a cursor")
                observed_cursors.add(next_cursor)
                cursor = next_cursor
            else:
                raise ListenerError(f"{node} exceeded max_pages")
        except (ClientError, ListenerError, OSError, ValueError, KeyError):
            stats.errors += 1
    return stats


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Discover and listen to OAC GLOBAL")
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--dns-domain", action="append", default=[])
    parser.add_argument("--state", type=Path, default=Path("oac-listener.sqlite3"))
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-nodes", type=int, default=32)
    parser.add_argument("--max-pages", type=int, default=10_000)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.interval <= 0 and not args.once:
        parser.error("--interval must be positive")

    domains = args.dns_domain or list(DEFAULT_DNS_DOMAINS)
    seeds = list(args.seed)
    for domain in domains:
        seeds.extend(dns_uri_seeds(domain))
    if not seeds:
        seeds.extend(DEFAULT_HTTPS_SEEDS)
    seeds = list(dict.fromkeys(seeds))

    store = ListenerStore(args.state)

    def emit(source: str, event: Dict[str, Any]) -> None:
        print(
            json.dumps(
                {"kind": "oac_event", "source": source, "event": event},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )

    try:
        while True:
            try:
                stats = listen_once(
                    seeds,
                    store,
                    page_size=args.page_size,
                    max_nodes=args.max_nodes,
                    max_pages=args.max_pages,
                    on_event=emit,
                )
                print(
                    json.dumps({"kind": "oac_listener_status", **asdict(stats)}),
                    file=sys.stderr,
                    flush=True,
                )
            except (ClientError, ListenerError, OSError, ValueError, KeyError) as error:
                print(
                    json.dumps({"error": "listener_failed", "detail": str(error)}),
                    file=sys.stderr,
                    flush=True,
                )
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(args.interval)
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
