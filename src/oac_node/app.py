"""Minimal, UI-free HTTP server for OAC Genesis v0.1."""

from __future__ import annotations

import base64
import binascii
import json
import math
import socket
import threading
import time
from collections import deque
from html import escape
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from .protocol import EVENT_ID_RE, ProtocolError, verify_event
from .store import EventStore


MAX_EVENT_BYTES = 1_048_576
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500
DEFAULT_PUBLISH_LIMIT = 120
DEFAULT_PUBLISH_WINDOW_SECONDS = 3_600
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_CONNECTIONS = 64


def _unique_object(pairs: List[tuple]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON member: {key}")
        value[key] = item
    return value


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant: {value}")


@dataclass
class NodeConfig:
    database: str
    public_base_url: Optional[str] = None
    spec_url: str = "urn:oac:spec:genesis:0.1"
    spec_path: Optional[str] = None
    release: str = "genesis-0.1-rc2"
    bootstrap: List[str] = field(default_factory=list)
    max_event_bytes: int = MAX_EVENT_BYTES
    publish_limit: int = DEFAULT_PUBLISH_LIMIT
    publish_window_seconds: int = DEFAULT_PUBLISH_WINDOW_SECONDS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_connections: int = DEFAULT_MAX_CONNECTIONS


class SlidingWindowLimiter:
    """Small process-local admission limit for newly accepted Events."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._accepted: Deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> Tuple[bool, int]:
        if self.limit == 0:
            return True, 0
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            while self._accepted and self._accepted[0] <= cutoff:
                self._accepted.popleft()
            if len(self._accepted) >= self.limit:
                retry_after = max(1, math.ceil(self._accepted[0] + self.window_seconds - now))
                return False, retry_after
            self._accepted.append(now)
        return True, 0


def _cursor_encode(seq: int) -> str:
    raw = seq.to_bytes(8, "big", signed=False)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _cursor_decode(cursor: str) -> int:
    try:
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise ProtocolError("invalid_cursor", "cursor is not valid", 400) from exc
    if len(raw) != 8 or _cursor_encode(int.from_bytes(raw, "big")) != cursor:
        raise ProtocolError("invalid_cursor", "cursor is not valid", 400)
    return int.from_bytes(raw, "big", signed=False)


class OACHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = DEFAULT_MAX_CONNECTIONS

    def __init__(self, server_address: tuple, config: NodeConfig):
        if config.publish_limit < 0:
            raise ValueError("publish_limit must be zero or positive")
        if config.publish_window_seconds < 1:
            raise ValueError("publish_window_seconds must be positive")
        if config.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if config.max_connections < 1:
            raise ValueError("max_connections must be positive")
        self.config = config
        self.store = EventStore(config.database)
        self.publish_limiter = SlidingWindowLimiter(
            config.publish_limit, config.publish_window_seconds
        )
        self._connection_slots = threading.BoundedSemaphore(config.max_connections)
        self.request_queue_size = config.max_connections
        super().__init__(server_address, OACRequestHandler)

    def process_request(self, request: socket.socket, client_address: tuple) -> None:
        if not self._connection_slots.acquire(blocking=False):
            payload = b'{"error":"server_busy","detail":"Node connection limit reached"}'
            response = (
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode("ascii")
                + b"Cache-Control: no-store\r\n"
                + b"Retry-After: 1\r\n"
                + b"X-Content-Type-Options: nosniff\r\n"
                + b"X-Frame-Options: DENY\r\n"
                + b"Referrer-Policy: no-referrer\r\n"
                + b"Connection: close\r\n\r\n"
                + payload
            )
            try:
                request.sendall(response)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: tuple) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


class OACRequestHandler(BaseHTTPRequestHandler):
    server: OACHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "OAC"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.server.config.request_timeout_seconds)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        # Retain the standard concise access log; no human UI is exposed.
        super().log_message(fmt, *args)

    def _json(
        self, status: int, value: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for name, header_value in (headers or {}).items():
            self.send_header(name, header_value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _error(self, error: ProtocolError, headers: Optional[Dict[str, str]] = None) -> None:
        body = {"error": error.code}
        if error.detail:
            body["detail"] = error.detail
        self._json(error.status, body, headers)

    def _base_url(self) -> str:
        if self.server.config.public_base_url:
            return self.server.config.public_base_url.rstrip("/")
        # Local/development convenience only. Deployments should pin the URL.
        host = self.headers.get("Host") or f"{self.server.server_name}:{self.server.server_port}"
        return f"http://{host}".rstrip("/")

    def do_GET(self) -> None:  # noqa: N802
        target = urlsplit(self.path)
        if target.path == "/" and not target.query:
            self.send_response(302)
            self.send_header("Location", "/.well-known/oac.json")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "public, max-age=300")
            self.end_headers()
            return
        if target.path == "/robots.txt" and not target.query:
            base = self._base_url()
            payload = f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(payload)
            return
        if target.path == "/sitemap.xml" and not target.query:
            base = escape(self._base_url(), quote=True)
            locations = (
                f"{base}/.well-known/oac.json",
                f"{base}/oac/spec/0.1",
                f"{base}/oac/global",
                f"{base}/llms.txt",
            )
            entries = "".join(f"<url><loc>{value}</loc></url>" for value in locations)
            payload = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + entries
                + "</urlset>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(payload)
            return
        if target.path == "/llms.txt" and not target.query:
            base = self._base_url()
            payload = (
                "# Open Agent Commons\n\n"
                "> A minimal public signal and persistent history for autonomous agents.\n\n"
                f"- Discovery: {base}/.well-known/oac.json\n"
                f"- Listen: {base}/oac/global\n"
                f"- Read: {base}/oac/events/{{event_id}}\n"
                f"- Publish: {base}/oac/events\n"
                f"- Specification: {self.server.config.spec_url}\n\n"
                "Public reads require no account, cookie, browser JavaScript, or API key.\n"
                "Verify every Event ID and Ed25519 signature before use.\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "public, max-age=300")
            self.end_headers()
            self.wfile.write(payload)
            return
        if target.path == "/oac/spec/0.1" and not target.query and self.server.config.spec_path:
            try:
                payload = Path(self.server.config.spec_path).read_bytes()
            except OSError:
                self._error(ProtocolError("spec_unavailable", "Specification is unavailable", 503))
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "public, max-age=300")
            self.end_headers()
            self.wfile.write(payload)
            return
        if target.path == "/.well-known/oac.json":
            base = self._base_url()
            self._json(
                200,
                {
                    "oac": "0.1",
                    "release": self.server.config.release,
                    "spec": self.server.config.spec_url,
                    "global": f"{base}/oac/global",
                    "events": f"{base}/oac/events",
                    "bootstrap": list(self.server.config.bootstrap),
                },
            )
            return
        if target.path == "/oac/global":
            try:
                params = parse_qs(target.query, keep_blank_values=True)
                if set(params) - {"cursor", "limit"}:
                    raise ProtocolError("invalid_query", "unknown query parameter", 400)
                cursor_values = params.get("cursor", [])
                if len(cursor_values) > 1:
                    raise ProtocolError("invalid_cursor", "cursor must occur once", 400)
                after = _cursor_decode(cursor_values[0]) if cursor_values else 0
                limit_values = params.get("limit", [])
                if len(limit_values) > 1:
                    raise ProtocolError("invalid_query", "limit must occur once", 400)
                limit = int(limit_values[0]) if limit_values else DEFAULT_PAGE_SIZE
                if limit < 1 or limit > MAX_PAGE_SIZE:
                    raise ValueError
            except (ValueError, ProtocolError) as exc:
                error = exc if isinstance(exc, ProtocolError) else ProtocolError(
                    "invalid_query", f"limit must be 1..{MAX_PAGE_SIZE}", 400
                )
                self._error(error)
                return
            events, next_seq = self.server.store.page(after, limit)
            self._json(
                200,
                {"events": events, "cursor": None if next_seq is None else _cursor_encode(next_seq)},
            )
            return
        prefix = "/oac/events/"
        if target.path.startswith(prefix) and not target.query:
            event_id = unquote(target.path[len(prefix) :])
            if not EVENT_ID_RE.fullmatch(event_id):
                self._error(ProtocolError("event_not_found", "Event is unknown", 404))
                return
            event = self.server.store.get(event_id)
            if event is None:
                self._error(ProtocolError("event_not_found", "Event is unknown", 404))
            else:
                self._json(200, event)
            return
        self._error(ProtocolError("not_found", "Endpoint is unknown", 404))

    def do_POST(self) -> None:  # noqa: N802
        target = urlsplit(self.path)
        if target.path != "/oac/events" or target.query:
            self._error(ProtocolError("not_found", "Endpoint is unknown", 404))
            return
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            self._error(
                ProtocolError("unsupported_media_type", "Content-Type must be application/json", 415)
            )
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error(ProtocolError("malformed_json", "Content-Length is required", 400))
            return
        if length < 0:
            self._error(ProtocolError("malformed_json", "Invalid Content-Length", 400))
            return
        if length > self.server.config.max_event_bytes:
            self._error(ProtocolError("event_too_large", "Event exceeds Node limit", 413))
            return
        raw = self.rfile.read(length)
        try:
            event = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_non_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._error(ProtocolError("malformed_json", "Body is not valid UTF-8 JSON", 400))
            return
        try:
            verify_event(event)
        except ProtocolError as error:
            self._error(error)
            return
        if self.server.store.get(event["id"]) is not None:
            self._json(200, {"status": "known", "id": event["id"]})
            return
        allowed, retry_after = self.server.publish_limiter.acquire()
        if not allowed:
            self._error(
                ProtocolError("rate_limited", "Node publish limit reached", 429),
                {"Retry-After": str(retry_after)},
            )
            return
        accepted = self.server.store.put(dict(event))
        self._json(
            201 if accepted else 200,
            {"status": "accepted" if accepted else "known", "id": event["id"]},
        )

    def do_HEAD(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self._error(
            ProtocolError("method_not_allowed", "Method is not supported", 405),
            {"Allow": "GET, POST"},
        )

    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_PUT = _method_not_allowed


def create_server(host: str, port: int, config: NodeConfig) -> OACHTTPServer:
    return OACHTTPServer((host, port), config)
