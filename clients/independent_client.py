#!/usr/bin/env python3
"""Independent minimal OAC Genesis client.

This implementation intentionally shares no protocol code with ``oac_node``.
It uses PyNaCl instead of cryptography and a small, schema-constrained JCS
encoder instead of the rfc8785 package. The encoder covers every JSON type
admitted by the strict Genesis Event schema (objects, arrays, strings, and
integers).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey


FIELDS = {"v", "id", "type", "author", "time", "topic", "text", "refs", "sig"}
BODY_FIELDS = FIELDS - {"id", "sig"}
EVENT_TYPES = {"signal", "problem", "proposal", "contribution", "result"}
USER_AGENT = "oac-client/0.1"


class ClientError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def unb64url(value: str, size: int) -> bytes:
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except Exception as exc:
        raise ClientError("invalid_event", "invalid base64url") from exc
    if len(raw) != size or b64url(raw) != value:
        raise ClientError("invalid_event", f"base64url value must encode {size} bytes")
    return raw


def _reject_surrogates(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ClientError("invalid_event", "lone Unicode surrogate is not valid JCS")


def jcs(value: Any) -> bytes:
    """Canonicalize the JSON subset admitted by the Genesis schema."""
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, float):
        raise ClientError("invalid_event", "Genesis schema does not admit floating point values")
    if isinstance(value, str):
        _reject_surrogates(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(jcs(item) for item in value) + b"]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ClientError("invalid_event", "JSON object keys must be strings")
        # Genesis field names are ASCII, for which Unicode and UTF-16 ordering coincide.
        encoded = []
        for key in sorted(value):
            _reject_surrogates(key)
            encoded.append(jcs(key) + b":" + jcs(value[key]))
        return b"{" + b",".join(encoded) + b"}"
    raise ClientError("invalid_event", "value is outside the Genesis JSON schema")


def body_of(event: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in event.items() if key not in {"id", "sig"}}


def validate_body(body: Mapping[str, Any]) -> None:
    if not isinstance(body, Mapping):
        raise ClientError("invalid_event", "Event Body must be an object")
    missing = BODY_FIELDS - set(body)
    if missing:
        raise ClientError("missing_field", f"missing {sorted(missing)[0]}")
    if set(body) != BODY_FIELDS:
        raise ClientError("invalid_event", "unknown Genesis field")
    if body["v"] != "0.1":
        raise ClientError("unsupported_version")
    if body["type"] not in EVENT_TYPES:
        raise ClientError("invalid_event", "invalid Event type")
    if not isinstance(body["author"], str) or not body["author"].startswith("ed25519:"):
        raise ClientError("invalid_event", "invalid author")
    unb64url(body["author"][8:], 32)
    if (
        isinstance(body["time"], bool)
        or not isinstance(body["time"], int)
        or body["time"] < 0
        or body["time"] > 9_007_199_254_740_991
    ):
        raise ClientError("invalid_event", "invalid time")
    if not isinstance(body["text"], str):
        raise ClientError("invalid_event", "invalid text")
    for field in ("topic", "refs"):
        if not isinstance(body[field], list) or any(not isinstance(x, str) for x in body[field]):
            raise ClientError("invalid_event", f"invalid {field}")
    if any(len(ref) != 64 or any(c not in "0123456789abcdef" for c in ref) for ref in body["refs"]):
        raise ClientError("invalid_event", "invalid ref")


def make_event(body: Mapping[str, Any], seed: bytes) -> Dict[str, Any]:
    validate_body(body)
    digest = hashlib.sha256(jcs(dict(body))).digest()
    event = dict(body)
    event["id"] = digest.hex()
    event["sig"] = b64url(SigningKey(seed).sign(digest).signature)
    return event


def verify_event(event: Mapping[str, Any]) -> None:
    if not isinstance(event, Mapping) or set(event) != FIELDS:
        raise ClientError("invalid_event", "invalid Event fields")
    body = body_of(event)
    validate_body(body)
    digest = hashlib.sha256(jcs(body)).digest()
    if event["id"] != digest.hex():
        raise ClientError("invalid_event_id")
    try:
        VerifyKey(unb64url(body["author"][8:], 32)).verify(digest, unb64url(event["sig"], 64))
    except (BadSignatureError, ValueError) as exc:
        raise ClientError("invalid_signature") from exc


def identity(seed: bytes) -> str:
    return "ed25519:" + b64url(bytes(SigningKey(seed).verify_key))


class OACClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _request(request: Request) -> Tuple[int, Dict[str, Any]]:
        if not request.has_header("User-Agent"):
            request.add_header("User-Agent", USER_AGENT)
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {
                    "error": "http_error",
                    "detail": f"HTTP {error.code} returned a non-JSON response",
                }
            raise ClientError(payload.get("error", "http_error"), payload.get("detail", "")) from error

    def discover(self) -> Dict[str, Any]:
        return self._request(Request(self.base_url + "/.well-known/oac.json"))[1]

    def publish(self, event: Mapping[str, Any]) -> Tuple[int, Dict[str, Any]]:
        verify_event(event)
        raw = json.dumps(dict(event), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._request(
            Request(
                self.base_url + "/oac/events",
                data=raw,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
        )

    def read(self, event_id: str) -> Dict[str, Any]:
        event = self._request(Request(self.base_url + "/oac/events/" + quote(event_id)))[1]
        verify_event(event)
        if event["id"] != event_id:
            raise ClientError(
                "invalid_event_id", "read response does not match the requested Event ID"
            )
        return event

    def global_page(self, cursor: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        query = {"limit": str(limit)}
        if cursor is not None:
            query["cursor"] = cursor
        page = self._request(Request(self.base_url + "/oac/global?" + urlencode(query)))[1]
        for event in page["events"]:
            verify_event(event)
        return page


VECTOR_SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
VECTOR_BODY = {
    "v": "0.1",
    "type": "problem",
    "author": identity(VECTOR_SEED),
    "time": 1789872000,
    "topic": ["mathematics"],
    "text": "Can X be proven more simply?",
    "refs": [],
}


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Independent OAC Genesis client")
    sub = parser.add_subparsers(dest="command", required=True)
    vector = sub.add_parser("vector", help="emit and verify the normative Event")
    vector.add_argument("--compact", action="store_true")
    discover = sub.add_parser("discover")
    discover.add_argument("base_url")
    listing = sub.add_parser("list")
    listing.add_argument("base_url")
    listing.add_argument("--cursor")
    listing.add_argument("--limit", type=int, default=100)
    read = sub.add_parser("read")
    read.add_argument("base_url")
    read.add_argument("event_id")
    publish = sub.add_parser("publish")
    publish.add_argument("base_url")
    publish.add_argument("event_json", help="path to a signed Event JSON file")
    args = parser.parse_args(argv)
    try:
        if args.command == "vector":
            value = make_event(VECTOR_BODY, VECTOR_SEED)
            verify_event(value)
            print(json.dumps(value, ensure_ascii=False, indent=None if args.compact else 2))
        elif args.command == "discover":
            print(json.dumps(OACClient(args.base_url).discover(), indent=2))
        elif args.command == "list":
            print(json.dumps(OACClient(args.base_url).global_page(args.cursor, args.limit), indent=2))
        elif args.command == "read":
            print(json.dumps(OACClient(args.base_url).read(args.event_id), indent=2))
        elif args.command == "publish":
            with open(args.event_json, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            status, result = OACClient(args.base_url).publish(value)
            print(json.dumps({"http_status": status, **result}, indent=2))
        return 0
    except ClientError as error:
        print(json.dumps({"error": error.code, "detail": error.detail}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
