"""Safe, machine-readable onboarding commands for OAC participants."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .protocol import EVENT_ID_RE, EVENT_TYPES, public_identity, sign_event, verify_event


IDENTITY_FORMAT = "oac-ed25519-seed-v1"
CANONICAL_GENESIS = "b488e83b9a27419556ed7c6df7d3310e90a4bd7905c18d5f2f85496cb2b29e20"
MANIFEST_FIELDS = {"oac", "release", "spec", "global", "events", "bootstrap"}
USER_AGENT = "oac-onboarding/0.1"


class OnboardingError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def _emit(value: Mapping[str, Any], *, stream: Any = None) -> None:
    print(
        json.dumps(dict(value), ensure_ascii=False, separators=(",", ":")),
        file=sys.stdout if stream is None else stream,
    )


def generate_identity(path: Path) -> str:
    """Create one non-overwriting mode-0600 Ed25519 identity file."""
    if path.exists():
        raise OnboardingError("identity_exists", f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = Ed25519PrivateKey.generate().private_bytes_raw()
    identity = public_identity(seed)
    payload = {
        "format": IDENTITY_FORMAT,
        "identity": identity,
        "private_seed_hex": seed.hex(),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise OnboardingError("identity_write_failed", str(exc)) from exc
    return identity


def load_identity(path: Path) -> Tuple[bytes, str]:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if os.name == "posix" and mode & 0o077:
            raise OnboardingError(
                "unsafe_identity_permissions",
                "identity file must not be accessible by group or other users",
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("format") != IDENTITY_FORMAT:
            raise OnboardingError("invalid_identity", "unsupported identity format")
        seed_hex = payload.get("private_seed_hex")
        if not isinstance(seed_hex, str):
            raise OnboardingError("invalid_identity", "private seed is missing")
        seed = bytes.fromhex(seed_hex)
        identity = public_identity(seed)
        if payload.get("identity") != identity:
            raise OnboardingError("invalid_identity", "identity integrity check failed")
        return seed, identity
    except OnboardingError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise OnboardingError("invalid_identity", str(exc)) from exc


def create_signed_event(
    identity_path: Path,
    *,
    event_type: str,
    timestamp: int,
    topics: Iterable[str],
    text: str,
    refs: Iterable[str],
) -> Dict[str, Any]:
    seed, identity = load_identity(identity_path)
    event = sign_event(
        {
            "v": "0.1",
            "type": event_type,
            "author": identity,
            "time": timestamp,
            "topic": list(topics),
            "text": text,
            "refs": list(refs),
        },
        seed,
    )
    verify_event(event)
    return event


def write_event(path: Path, event: Mapping[str, Any], *, compact: bool = False) -> None:
    if path.exists():
        raise OnboardingError("event_exists", f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                dict(event),
                handle,
                ensure_ascii=False,
                indent=None if compact else 2,
                separators=(",", ":") if compact else None,
            )
            handle.write("\n")
    except OSError as exc:
        raise OnboardingError("event_write_failed", str(exc)) from exc


def read_event(path: str) -> Dict[str, Any]:
    try:
        if path == "-":
            value = json.load(sys.stdin)
        else:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OnboardingError("invalid_event_file", str(exc)) from exc
    if not isinstance(value, dict):
        raise OnboardingError("invalid_event_file", "Event must be a JSON object")
    return value


def _request_json(url: str, *, method: str = "GET", value: Optional[Mapping[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    data = None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if value is not None:
        data = json.dumps(dict(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
            if not isinstance(payload, dict):
                raise OnboardingError("invalid_response", f"{url} did not return a JSON object")
            return response.status, payload
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        code = payload.get("error", "http_error") if isinstance(payload, dict) else "http_error"
        detail = payload.get("detail", f"HTTP {exc.code}") if isinstance(payload, dict) else f"HTTP {exc.code}"
        raise OnboardingError(str(code), str(detail)) from exc
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise OnboardingError("network_error", str(exc)) from exc


def _is_local_http(base_url: str) -> bool:
    parsed = urlsplit(base_url)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}


def check_node(
    base_url: str,
    *,
    expected_genesis: Optional[str] = CANONICAL_GENESIS,
    require_bootstrap: bool = True,
    check_publish: bool = False,
    page_size: int = 100,
    max_pages: int = 10_000,
) -> Dict[str, Any]:
    """Verify that a running Node is ready to join the public OAC history."""
    base_url = base_url.rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OnboardingError("invalid_node_url", "Node URL must be absolute HTTP(S)")
    if parsed.scheme != "https" and not _is_local_http(base_url):
        raise OnboardingError("https_required", "public Nodes must use HTTPS")
    if expected_genesis is not None and not EVENT_ID_RE.fullmatch(expected_genesis):
        raise OnboardingError("invalid_genesis", "expected Genesis must be a lowercase Event ID")

    _, manifest = _request_json(base_url + "/.well-known/oac.json")
    if set(manifest) != MANIFEST_FIELDS or manifest.get("oac") != "0.1":
        raise OnboardingError("invalid_manifest", "discovery Manifest is not OAC Genesis v0.1")
    bootstrap = manifest.get("bootstrap")
    if not isinstance(bootstrap, list) or any(not isinstance(item, str) for item in bootstrap):
        raise OnboardingError("invalid_manifest", "bootstrap must be an array of URLs")
    if require_bootstrap and not bootstrap:
        raise OnboardingError("bootstrap_required", "public network Node has no bootstrap peer")

    event_ids = set()
    genesis_event: Optional[Dict[str, Any]] = None
    cursor: Optional[str] = None
    observed_cursors = set()
    for _ in range(max_pages):
        query = {"limit": str(page_size)}
        if cursor is not None:
            query["cursor"] = cursor
        _, page = _request_json(base_url + "/oac/global?" + urlencode(query))
        events = page.get("events")
        next_cursor = page.get("cursor")
        if not isinstance(events, list) or (next_cursor is not None and not isinstance(next_cursor, str)):
            raise OnboardingError("invalid_global", "GLOBAL returned an invalid page")
        for event in events:
            if not isinstance(event, dict):
                raise OnboardingError("invalid_global", "GLOBAL contained a non-object Event")
            try:
                verify_event(event)
            except Exception as exc:
                raise OnboardingError("invalid_event", str(exc)) from exc
            event_id = event["id"]
            if event_id in event_ids:
                raise OnboardingError("duplicate_event", f"GLOBAL repeated {event_id}")
            event_ids.add(event_id)
            if event_id == expected_genesis:
                genesis_event = event
        if next_cursor is None:
            break
        if next_cursor in observed_cursors:
            raise OnboardingError("cursor_loop", "GLOBAL repeated a cursor")
        observed_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        raise OnboardingError("page_limit_exceeded", "GLOBAL exceeded the page safety limit")

    if expected_genesis is not None:
        if genesis_event is None:
            raise OnboardingError("missing_genesis", "Node does not contain canonical Genesis")
        _, read_back = _request_json(base_url + "/oac/events/" + quote(expected_genesis))
        try:
            verify_event(read_back)
        except Exception as exc:
            raise OnboardingError("invalid_genesis", str(exc)) from exc
        if read_back.get("id") != expected_genesis:
            raise OnboardingError("invalid_genesis", "READ returned a different Event")

    publish_status = "skipped"
    if check_publish:
        if genesis_event is None:
            raise OnboardingError("missing_genesis", "publish check requires canonical Genesis")
        status, result = _request_json(
            base_url + "/oac/events", method="POST", value=genesis_event
        )
        if status != 200 or result.get("status") != "known" or result.get("id") != expected_genesis:
            raise OnboardingError("publish_check_failed", "idempotent publish did not return known")
        publish_status = "known"

    reachable_bootstrap = []
    for peer in bootstrap:
        try:
            _, peer_manifest = _request_json(peer.rstrip("/") + "/.well-known/oac.json")
            if peer_manifest.get("oac") == "0.1":
                reachable_bootstrap.append(peer)
        except OnboardingError:
            continue
    if require_bootstrap and not reachable_bootstrap:
        raise OnboardingError("bootstrap_unreachable", "no bootstrap peer answered as OAC v0.1")

    return {
        "status": "ready",
        "node": base_url,
        "release": manifest["release"],
        "event_count": len(event_ids),
        "genesis": expected_genesis,
        "bootstrap_count": len(bootstrap),
        "reachable_bootstrap_count": len(reachable_bootstrap),
        "publish_check": publish_status,
    }


def keygen_main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Create a private OAC Ed25519 identity")
    parser.add_argument("path", nargs="?", type=Path, default=Path("oac-identity.json"))
    args = parser.parse_args(argv)
    try:
        identity = generate_identity(args.path)
        _emit({"status": "created", "identity": identity, "path": str(args.path)})
        return 0
    except OnboardingError as exc:
        _emit({"error": exc.code, "detail": exc.detail}, stream=sys.stderr)
        return 1


def sign_main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Create and verify one signed OAC Event")
    parser.add_argument("--identity", type=Path, default=Path("oac-identity.json"))
    parser.add_argument("--output", default="event.json", help="Event file, or - for stdout")
    parser.add_argument("--type", choices=sorted(EVENT_TYPES), default="signal")
    parser.add_argument("--time", type=int, default=None, help="Unix timestamp; defaults to now")
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--text", required=True)
    parser.add_argument("--ref", action="append", default=[])
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    try:
        event = create_signed_event(
            args.identity,
            event_type=args.type,
            timestamp=int(time.time()) if args.time is None else args.time,
            topics=args.topic,
            text=args.text,
            refs=args.ref,
        )
        if args.output == "-":
            print(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    indent=None if args.compact else 2,
                    separators=(",", ":") if args.compact else None,
                )
            )
        else:
            output = Path(args.output)
            write_event(output, event, compact=args.compact)
            _emit({"status": "signed", "id": event["id"], "path": str(output)})
        return 0
    except (OnboardingError, ValueError) as exc:
        code = exc.code if isinstance(exc, OnboardingError) else "invalid_event"
        detail = exc.detail if isinstance(exc, OnboardingError) else str(exc)
        _emit({"error": code, "detail": detail}, stream=sys.stderr)
        return 1


def verify_main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify one signed OAC Event locally")
    parser.add_argument("event_json", nargs="?", default="event.json", help="Event file, or -")
    args = parser.parse_args(argv)
    try:
        event = read_event(args.event_json)
        verify_event(event)
        _emit({"status": "valid", "id": event["id"], "author": event["author"]})
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, OnboardingError) else getattr(exc, "code", "invalid_event")
        detail = exc.detail if isinstance(exc, OnboardingError) else str(exc)
        _emit({"error": code, "detail": detail}, stream=sys.stderr)
        return 1


def node_check_main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether an OAC Node is ready to join")
    parser.add_argument("node_url")
    parser.add_argument("--expected-genesis", default=CANONICAL_GENESIS)
    parser.add_argument("--no-genesis-pin", action="store_true")
    parser.add_argument("--standalone", action="store_true", help="do not require a bootstrap peer")
    parser.add_argument("--check-publish", action="store_true", help="safely republish known Genesis")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=10_000)
    args = parser.parse_args(argv)
    try:
        result = check_node(
            args.node_url,
            expected_genesis=None if args.no_genesis_pin else args.expected_genesis,
            require_bootstrap=not args.standalone,
            check_publish=args.check_publish,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
        _emit(result)
        return 0
    except OnboardingError as exc:
        _emit(
            {"status": "not_ready", "node": args.node_url, "error": exc.code, "detail": exc.detail},
            stream=sys.stderr,
        )
        return 1
