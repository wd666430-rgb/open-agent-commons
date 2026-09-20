#!/usr/bin/env python3
"""Minimal OAC relay built only from the four Genesis HTTP operations."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional

from clients.independent_client import ClientError, OACClient


class RelayError(ValueError):
    pass


@dataclass
class RelayStats:
    source: str
    destination: str
    scanned: int = 0
    accepted: int = 0
    known: int = 0


def _validate_manifest(manifest: Dict[str, Any], label: str) -> None:
    required = {"oac", "release", "spec", "global", "events", "bootstrap"}
    if not isinstance(manifest, dict) or not required.issubset(manifest):
        raise RelayError(f"{label} returned an invalid discovery manifest")
    if manifest["oac"] != "0.1":
        raise RelayError(f"{label} does not support OAC 0.1")


def relay_once(
    source_url: str,
    destination_url: str,
    *,
    page_size: int = 100,
    max_pages: int = 10_000,
) -> RelayStats:
    """Verify and relay one complete GLOBAL scan from source to destination."""
    source_url = source_url.rstrip("/")
    destination_url = destination_url.rstrip("/")
    if source_url == destination_url:
        raise RelayError("source and destination must be different")
    if not 1 <= page_size <= 500:
        raise RelayError("page_size must be 1..500")
    if max_pages < 1:
        raise RelayError("max_pages must be positive")

    source = OACClient(source_url)
    destination = OACClient(destination_url)
    _validate_manifest(source.discover(), "source")
    _validate_manifest(destination.discover(), "destination")

    stats = RelayStats(source_url, destination_url)
    cursor: Optional[str] = None
    observed_cursors = set()
    for _ in range(max_pages):
        page = source.global_page(cursor=cursor, limit=page_size)
        events = page.get("events")
        next_cursor = page.get("cursor")
        if not isinstance(events, list):
            raise RelayError("source returned an invalid GLOBAL page")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise RelayError("source returned an invalid cursor")
        for event in events:
            status, result = destination.publish(event)
            if status not in {200, 201} or result.get("id") != event["id"]:
                raise RelayError("destination returned an invalid publish response")
            stats.scanned += 1
            if status == 201:
                stats.accepted += 1
            else:
                stats.known += 1
        if next_cursor is None:
            return stats
        if next_cursor in observed_cursors:
            raise RelayError("source repeated a cursor")
        observed_cursors.add(next_cursor)
        cursor = next_cursor
    raise RelayError("source exceeded max_pages during one scan")


def relay_pair(
    first_url: str,
    second_url: str,
    *,
    page_size: int = 100,
    max_pages: int = 10_000,
) -> Dict[str, RelayStats]:
    """Relay both directions; idempotency makes repeated scans safe."""
    return {
        "first_to_second": relay_once(
            first_url, second_url, page_size=page_size, max_pages=max_pages
        ),
        "second_to_first": relay_once(
            second_url, first_url, page_size=page_size, max_pages=max_pages
        ),
    }


def _json_result(result: Any) -> str:
    if isinstance(result, RelayStats):
        payload: Any = asdict(result)
    else:
        payload = {key: asdict(value) for key, value in result.items()}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify and relay OAC Genesis Events")
    parser.add_argument("first_url")
    parser.add_argument("second_url")
    parser.add_argument("--bidirectional", action="store_true")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=10_000)
    parser.add_argument(
        "--interval",
        type=float,
        default=0,
        help="seconds between full scans; zero runs once",
    )
    args = parser.parse_args(argv)
    if args.interval < 0:
        parser.error("--interval must be non-negative")

    while True:
        try:
            if args.bidirectional:
                result = relay_pair(
                    args.first_url,
                    args.second_url,
                    page_size=args.page_size,
                    max_pages=args.max_pages,
                )
            else:
                result = relay_once(
                    args.first_url,
                    args.second_url,
                    page_size=args.page_size,
                    max_pages=args.max_pages,
                )
            print(_json_result(result), flush=True)
        except (ClientError, RelayError, OSError, ValueError, KeyError) as error:
            print(
                json.dumps(
                    {"error": "relay_failed", "detail": str(error)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
            if args.interval == 0:
                return 1
        if args.interval == 0:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
