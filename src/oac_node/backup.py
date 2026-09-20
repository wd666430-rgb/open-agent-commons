"""Verified online backups for an OAC SQLite event store."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def inspect_backup(path: Path) -> Dict[str, Any]:
    """Return non-sensitive integrity metadata for an OAC backup."""
    with _read_only_connection(path) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        event_count = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    return {"integrity": integrity, "events": event_count, "bytes": path.stat().st_size}


def restore_drill(path: Path, *, expected_min_events: int = 0) -> Dict[str, Any]:
    """Restore a snapshot to a new writable location and verify it there."""
    path = path.resolve()
    with tempfile.TemporaryDirectory(prefix="oac-restore-") as temporary_directory:
        restored = Path(temporary_directory) / "restored.sqlite3"
        shutil.copy2(path, restored)
        with sqlite3.connect(restored) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            event_count = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            connection.execute("PRAGMA journal_mode=WAL")
        if integrity != "ok":
            raise RuntimeError(f"restored database integrity check failed: {integrity}")
        if event_count < expected_min_events:
            raise RuntimeError(
                f"restored database has {event_count} events; expected at least {expected_min_events}"
            )
    return {
        "path": str(path),
        "restore": "ok",
        "integrity": integrity,
        "events": event_count,
        "bytes": path.stat().st_size,
    }


def create_backup(
    source: Path,
    destination_dir: Path,
    *,
    prefix: str = "oac-events",
    retain: int = 14,
    expected_min_events: int = 0,
) -> Dict[str, Any]:
    """Create, verify, atomically install, and rotate one online backup."""
    source = source.resolve()
    destination_dir = destination_dir.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source database does not exist: {source}")
    if retain < 1:
        raise ValueError("retain must be positive")
    if expected_min_events < 0:
        raise ValueError("expected_min_events must be zero or positive")
    if not prefix or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in prefix):
        raise ValueError("prefix may contain only letters, numbers, hyphen, and underscore")

    destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination_dir, 0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = destination_dir / f"{prefix}-{timestamp}.sqlite3"

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{prefix}-", suffix=".tmp", dir=destination_dir
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        with _read_only_connection(source) as source_connection:
            with sqlite3.connect(temporary_path) as backup_connection:
                source_connection.backup(backup_connection)
                backup_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                # A standalone backup must not depend on WAL/SHM sidecars whose
                # names would no longer match after the atomic rename.
                backup_connection.execute("PRAGMA journal_mode=DELETE")
        os.chmod(temporary_path, 0o600)
        metadata = inspect_backup(temporary_path)
        if metadata["integrity"] != "ok":
            raise RuntimeError(f"backup integrity check failed: {metadata['integrity']}")
        if metadata["events"] < expected_min_events:
            raise RuntimeError(
                f"backup has {metadata['events']} events; expected at least {expected_min_events}"
            )
        os.replace(temporary_path, destination)
        temporary_path = None
        directory_fd = os.open(destination_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
            Path(f"{temporary_path}-wal").unlink(missing_ok=True)
            Path(f"{temporary_path}-shm").unlink(missing_ok=True)

    backups = sorted(
        destination_dir.glob(f"{prefix}-????????T??????Z.sqlite3"),
        key=lambda item: item.name,
        reverse=True,
    )
    for expired in backups[retain:]:
        expired.unlink()

    return {"path": str(destination), **metadata}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a verified online OAC SQLite backup")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination-dir", type=Path)
    parser.add_argument("--prefix", default="oac-events")
    parser.add_argument("--retain", default=14, type=int)
    parser.add_argument("--expected-min-events", default=0, type=int)
    parser.add_argument(
        "--verify-only",
        type=Path,
        help="inspect an existing backup instead of creating one",
    )
    parser.add_argument(
        "--restore-drill",
        type=Path,
        help="restore an existing backup to a temporary database and verify it",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.verify_only is not None and args.restore_drill is not None:
        raise SystemExit("choose only one of --verify-only and --restore-drill")
    if args.verify_only is not None:
        result = {"path": str(args.verify_only.resolve()), **inspect_backup(args.verify_only)}
    elif args.restore_drill is not None:
        result = restore_drill(
            args.restore_drill,
            expected_min_events=args.expected_min_events,
        )
    else:
        if args.source is None or args.destination_dir is None:
            raise SystemExit("--source and --destination-dir are required when creating a backup")
        result = create_backup(
            args.source,
            args.destination_dir,
            prefix=args.prefix,
            retain=args.retain,
            expected_min_events=args.expected_min_events,
        )
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
