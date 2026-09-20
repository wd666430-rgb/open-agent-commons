from __future__ import annotations

import json
import hashlib
import tomllib
from pathlib import Path

from oac_node import __version__
from oac_node.app import NodeConfig


ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_are_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    package_version = project["version"]
    registry = json.loads((ROOT / "server.json").read_text())

    assert package_version == __version__ == "0.1.0rc5"
    assert registry["version"] == "0.1.0-rc.5"
    assert registry["packages"][0]["version"] == package_version
    assert package_version in registry["packages"][0]["runtimeArguments"][0]["value"]
    assert NodeConfig(database=":memory:").release == "genesis-0.1-rc5"
    assert {
        "oac-keygen",
        "oac-sign",
        "oac-verify",
        "oac-node-check",
    }.issubset(project["scripts"])
    quick_node = (ROOT / "deploy" / "quick-node" / "compose.yaml").read_text()
    assert quick_node.count("genesis-0.1-rc5") == 3


def test_rc5_content_hash_manifest_matches_repository() -> None:
    manifest = json.loads((ROOT / "releases" / "genesis-0.1-rc5.json").read_text())
    release_hash = manifest.pop("release_hash")

    for name, record in manifest["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == record["sha256"]

    canonical = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert hashlib.sha256(canonical.encode()).hexdigest() == release_hash
