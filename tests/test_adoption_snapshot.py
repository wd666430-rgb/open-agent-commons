from __future__ import annotations

import pytest

from clients.adoption_snapshot import PARTICIPATION_CALL_ID, scan_events, summarize


def event(event_id: str, author: str, refs: list[str] | None = None) -> dict:
    return {"id": event_id, "author": author, "refs": refs or []}


class FakeClient:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.calls = []

    def global_page(self, cursor=None, limit=100):
        self.calls.append((cursor, limit))
        return self.pages[len(self.calls) - 1]


def test_snapshot_counts_only_public_verified_events():
    pages = [
        {"events": [event(PARTICIPATION_CALL_ID, "founder")], "cursor": "next"},
        {"events": [event("reply", "participant", [PARTICIPATION_CALL_ID])], "cursor": None},
    ]
    client = FakeClient(pages)
    summary = summarize(scan_events(client, page_size=1), {"stars": 2, "forks": 0})
    assert client.calls == [(None, 1), ("next", 1)]
    assert summary == {
        "event_count": 2,
        "distinct_public_author_count": 2,
        "participation_call_present": True,
        "participation_call_reply_count": 1,
        "participation_call_reply_author_count": 1,
        "github": {"stars": 2, "forks": 0},
    }


def test_snapshot_rejects_duplicate_id_and_cursor():
    repeated_id = FakeClient([
        {"events": [event("same", "a")], "cursor": "next"},
        {"events": [event("same", "a")], "cursor": None},
    ])
    with pytest.raises(ValueError, match="repeated Event ID"):
        scan_events(repeated_id)
    repeated_cursor = FakeClient([
        {"events": [], "cursor": "next"},
        {"events": [], "cursor": "next"},
    ])
    with pytest.raises(ValueError, match="repeated cursor"):
        scan_events(repeated_cursor)
