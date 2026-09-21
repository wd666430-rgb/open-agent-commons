#!/usr/bin/env python3
"""Read-only, aggregate public adoption snapshot; no visitor tracking."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen

from clients.independent_client import OACClient


DEFAULT_NODE = "https://oac.kuroroy.xyz"
REPOSITORY = "wd666430-rgb/open-agent-commons"
PARTICIPATION_CALL_ID = "0c83b4337476de4a49b053bd3b3c8565b291f9967d3d4b366847c1cb50c67a66"


def scan_events(client: OACClient, *, page_size: int = 100, max_pages: int = 1000) -> list[dict[str, Any]]:
    """Traverse verified GLOBAL pages, rejecting repeated cursors or event IDs."""
    if not 1 <= page_size <= 500 or max_pages < 1:
        raise ValueError("page_size must be 1..500 and max_pages must be positive")
    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    for _ in range(max_pages):
        page = client.global_page(cursor=cursor, limit=page_size)
        for event in page["events"]:
            event_id = event["id"]
            if event_id in seen_ids:
                raise ValueError("GLOBAL returned a repeated Event ID")
            seen_ids.add(event_id)
            events.append(event)
        cursor = page.get("cursor")
        if cursor is None:
            return events
        if not isinstance(cursor, str) or cursor in seen_cursors:
            raise ValueError("GLOBAL returned an invalid or repeated cursor")
        seen_cursors.add(cursor)
    raise ValueError("GLOBAL exceeded max_pages")


def github_counts(repo: str = REPOSITORY) -> dict[str, int]:
    request = Request(
        f"https://api.github.com/repos/{repo}",
        headers={"User-Agent": "oac-adoption-snapshot/0.1", "Accept": "application/vnd.github+json"},
    )
    with urlopen(request, timeout=10) as response:
        data = json.load(response)
    return {
        "stars": int(data["stargazers_count"]),
        "forks": int(data["forks_count"]),
    }


def summarize(events: list[dict[str, Any]], github: dict[str, int] | None) -> dict[str, Any]:
    replies = [event for event in events if PARTICIPATION_CALL_ID in event["refs"]]
    return {
        "event_count": len(events),
        "distinct_public_author_count": len({event["author"] for event in events}),
        "participation_call_present": any(event["id"] == PARTICIPATION_CALL_ID for event in events),
        "participation_call_reply_count": len(replies),
        "participation_call_reply_author_count": len({event["author"] for event in replies}),
        "github": github,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=DEFAULT_NODE)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--skip-github", action="store_true")
    args = parser.parse_args()
    try:
        events = scan_events(
            OACClient(args.node), page_size=args.page_size, max_pages=args.max_pages
        )
        result = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "node": args.node,
            **summarize(events, None if args.skip_github else github_counts()),
        }
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
