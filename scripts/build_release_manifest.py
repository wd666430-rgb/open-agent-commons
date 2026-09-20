#!/usr/bin/env python3
"""Build the content-hash manifest for the Genesis v0.1-rc1 candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "releases" / "genesis-0.1-rc1.json"
FILES = [
    "docs/spec.en.md",
    "docs/spec.zh-CN.md",
    "docs/ambiguities.md",
    "spec/oac-event-0.1.schema.json",
    "spec/oac-manifest-0.1.schema.json",
    "tests/test_genesis_conformance.py",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    payload = {
        "release": "genesis-0.1-rc1",
        "protocol": "oac/0.1",
        "parent": None,
        "public_node": "https://oac.kuroroy.xyz",
        "files": {name: {"sha256": sha256(ROOT / name)} for name in FILES},
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    payload["release_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(payload["release_hash"])


if __name__ == "__main__":
    main()

