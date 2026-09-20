"""Protocol primitives for OAC Genesis v0.1.

The signed Event Body is the complete Event object with ``id`` and ``sig``
removed. Its RFC 8785 representation is hashed with SHA-256. The raw 32-byte
digest is the Ed25519 message.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


VERSION = "0.1"
EVENT_TYPES = frozenset({"signal", "problem", "proposal", "contribution", "result"})
REQUIRED_FIELDS = frozenset(
    {"v", "id", "type", "author", "time", "topic", "text", "refs", "sig"}
)
BODY_FIELDS = REQUIRED_FIELDS - {"id", "sig"}
EVENT_ID_RE = re.compile(r"^[0-9a-f]{64}$")
BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class ProtocolError(ValueError):
    code: str
    detail: str
    status: int = 422

    def __str__(self) -> str:
        return self.detail


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str, *, size: int, label: str) -> bytes:
    if not isinstance(value, str) or not value or not BASE64URL_RE.fullmatch(value):
        raise ProtocolError("invalid_event", f"{label} must be unpadded base64url")
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise ProtocolError("invalid_event", f"{label} is not valid base64url") from exc
    if len(raw) != size or _b64url_encode(raw) != value:
        raise ProtocolError("invalid_event", f"{label} must encode exactly {size} bytes")
    return raw


def event_body(event: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in event.items() if key not in {"id", "sig"}}


def canonicalize_body(body: Mapping[str, Any]) -> bytes:
    try:
        return rfc8785.dumps(dict(body))
    except (TypeError, ValueError, rfc8785.CanonicalizationError) as exc:
        raise ProtocolError("invalid_event", "Event Body cannot be serialized with RFC 8785") from exc


def event_digest(body: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(canonicalize_body(body)).digest()


def event_id(body: Mapping[str, Any]) -> str:
    return event_digest(body).hex()


def public_identity(private_seed: bytes) -> str:
    if len(private_seed) != 32:
        raise ValueError("Ed25519 private seed must contain 32 bytes")
    public = Ed25519PrivateKey.from_private_bytes(private_seed).public_key().public_bytes_raw()
    return "ed25519:" + _b64url_encode(public)


def sign_event(body: Mapping[str, Any], private_seed: bytes) -> Dict[str, Any]:
    """Return a complete signed Event from an Event Body."""
    validate_body(body)
    private_key = Ed25519PrivateKey.from_private_bytes(private_seed)
    digest = event_digest(body)
    signed = dict(body)
    signed["id"] = digest.hex()
    signed["sig"] = _b64url_encode(private_key.sign(digest))
    return signed


def _require_string(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise ProtocolError("invalid_event", f"{field} must be a string")


def _require_string_list(value: Any, field: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProtocolError("invalid_event", f"{field} must be an array of strings")


def validate_body(body: Mapping[str, Any]) -> None:
    if not isinstance(body, Mapping):
        raise ProtocolError("invalid_event", "Event must be a JSON object")
    missing = sorted(BODY_FIELDS - set(body))
    if missing:
        raise ProtocolError("missing_field", f"Missing required field: {missing[0]}")
    unknown = sorted(set(body) - BODY_FIELDS)
    if unknown:
        raise ProtocolError("invalid_event", f"Unknown Genesis field: {unknown[0]}")
    if body["v"] != VERSION:
        raise ProtocolError("unsupported_version", "Only OAC version 0.1 is supported")
    _require_string(body["type"], "type")
    if body["type"] not in EVENT_TYPES:
        raise ProtocolError("invalid_event", "type is not a Genesis Event type")
    _require_string(body["author"], "author")
    if not body["author"].startswith("ed25519:"):
        raise ProtocolError("invalid_event", "author must use the ed25519 identity method")
    _b64url_decode(body["author"][8:], size=32, label="author key")
    if isinstance(body["time"], bool) or not isinstance(body["time"], int):
        raise ProtocolError("invalid_event", "time must be an integer Unix timestamp")
    if body["time"] < 0 or body["time"] > 9_007_199_254_740_991:
        raise ProtocolError("invalid_event", "time is outside the supported range")
    _require_string_list(body["topic"], "topic")
    _require_string(body["text"], "text")
    _require_string_list(body["refs"], "refs")
    if any(not EVENT_ID_RE.fullmatch(ref) for ref in body["refs"]):
        raise ProtocolError("invalid_event", "refs entries must be lowercase SHA-256 hex IDs")


def verify_event(event: Mapping[str, Any]) -> None:
    """Validate structure, content-derived ID, and Ed25519 signature.

    Raises ``ProtocolError`` with a stable machine code on failure.
    """
    if not isinstance(event, Mapping):
        raise ProtocolError("invalid_event", "Event must be a JSON object")
    missing = sorted(REQUIRED_FIELDS - set(event))
    if missing:
        raise ProtocolError("missing_field", f"Missing required field: {missing[0]}")
    unknown = sorted(set(event) - REQUIRED_FIELDS)
    if unknown:
        raise ProtocolError("invalid_event", f"Unknown Genesis field: {unknown[0]}")

    body = event_body(event)
    validate_body(body)
    if not isinstance(event["id"], str) or not EVENT_ID_RE.fullmatch(event["id"]):
        raise ProtocolError("invalid_event_id", "id must be lowercase SHA-256 hex")
    digest = event_digest(body)
    if event["id"] != digest.hex():
        raise ProtocolError("invalid_event_id", "id does not match SHA-256(JCS(Event Body))")

    try:
        signature = _b64url_decode(event["sig"], size=64, label="sig")
    except ProtocolError as exc:
        raise ProtocolError("invalid_signature", exc.detail) from exc
    public_raw = _b64url_decode(body["author"][8:], size=32, label="author key")
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, digest)
    except (InvalidSignature, ValueError) as exc:
        raise ProtocolError("invalid_signature", "Ed25519 verification failed") from exc


def require_fields(value: Mapping[str, Any], fields: Iterable[str]) -> None:
    """Small public helper for machine-readable adapters."""
    missing = sorted(set(fields) - set(value))
    if missing:
        raise ProtocolError("missing_field", f"Missing required field: {missing[0]}")
