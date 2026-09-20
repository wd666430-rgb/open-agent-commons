#!/usr/bin/env python3
"""Generate and inspect an OAC Ed25519 identity file.

The identity file contains private key material. It is created with mode 0600,
is excluded by this repository's .gitignore, and must never be published.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from oac_node.protocol import public_identity


def generate(path: Path) -> None:
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing identity: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = Ed25519PrivateKey.generate().private_bytes_raw()
    payload = {
        "format": "oac-ed25519-seed-v1",
        "identity": public_identity(seed),
        "private_seed_hex": seed.hex(),
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print(payload["identity"])


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("format") != "oac-ed25519-seed-v1":
        raise SystemExit("Unsupported identity file format")
    seed = bytes.fromhex(payload["private_seed_hex"])
    if payload.get("identity") != public_identity(seed):
        raise SystemExit("Identity file integrity check failed")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage a local OAC Ed25519 identity")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("generate")
    create.add_argument("path", type=Path)
    show = subparsers.add_parser("show")
    show.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "generate":
        generate(args.path)
    else:
        print(load(args.path)["identity"])


if __name__ == "__main__":
    main()

