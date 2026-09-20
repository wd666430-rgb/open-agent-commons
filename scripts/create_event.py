#!/usr/bin/env python3
"""Create a signed OAC Genesis Event without publishing it."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from oac_node.protocol import EVENT_TYPES, public_identity, sign_event, verify_event


def load_seed(path: Path) -> bytes:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("format") != "oac-ed25519-seed-v1":
        raise SystemExit("Unsupported identity file format")
    seed = bytes.fromhex(payload["private_seed_hex"])
    if payload.get("identity") != public_identity(seed):
        raise SystemExit("Identity file integrity check failed")
    return seed


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a signed OAC Genesis Event")
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--type", choices=sorted(EVENT_TYPES), default="signal")
    parser.add_argument("--time", type=int, default=None, help="Unix timestamp; defaults to now")
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--text", required=True)
    parser.add_argument("--ref", action="append", default=[])
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite existing Event: {args.output}")
    seed = load_seed(args.identity)
    body = {
        "v": "0.1",
        "type": args.type,
        "author": public_identity(seed),
        "time": int(time.time()) if args.time is None else args.time,
        "topic": args.topic,
        "text": args.text,
        "refs": args.ref,
    }
    event = sign_event(body, seed)
    verify_event(event)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(event, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(event["id"])


if __name__ == "__main__":
    main()
