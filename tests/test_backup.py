from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oac_node.backup import create_backup, inspect_backup, restore_drill
from oac_node.store import EventStore


def test_online_backup_is_complete_and_verified(tmp_path: Path) -> None:
    source = tmp_path / "live" / "events.sqlite3"
    store = EventStore(str(source))
    with sqlite3.connect(source) as connection:
        connection.execute(
            "INSERT INTO events(event_id, event_json) VALUES (?, ?)",
            ("a" * 64, '{"id":"' + "a" * 64 + '"}'),
        )

    result = create_backup(
        source,
        tmp_path / "backups",
        prefix="test-events",
        retain=2,
        expected_min_events=1,
    )

    backup = Path(result["path"])
    assert backup.is_file()
    assert backup.stat().st_mode & 0o777 == 0o600
    assert inspect_backup(backup)["integrity"] == "ok"
    assert inspect_backup(backup)["events"] == store.count() == 1
    assert restore_drill(backup, expected_min_events=1)["restore"] == "ok"


def test_backup_rejects_regressed_event_count(tmp_path: Path) -> None:
    source = tmp_path / "events.sqlite3"
    EventStore(str(source))

    with pytest.raises(RuntimeError, match="expected at least 1"):
        create_backup(source, tmp_path / "backups", expected_min_events=1)

    assert list((tmp_path / "backups").glob("*.sqlite3")) == []


def test_backup_retention_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "events.sqlite3"
    EventStore(str(source))
    destination = tmp_path / "backups"
    for stamp in ("20260918T000000Z", "20260919T000000Z", "20260920T000000Z"):
        old = destination / f"oac-events-{stamp}.sqlite3"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_bytes(b"old")

    create_backup(source, destination, retain=2)

    assert len(list(destination.glob("oac-events-*.sqlite3"))) == 2
