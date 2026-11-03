"""Shared test fixtures: the contract fixtures and a fake Local API listener.

The fake listener is a stdlib ``http.server`` on a random loopback port that
serves the fixtures from ``../contract/fixtures``, enforces the token and the
``Origin`` rule the way the terminal does, and records every request so
tests can assert URLs, query strings and headers. No real terminal, no
network beyond loopback.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "contract" / "fixtures"

TOKEN = "spt_" + "ab" * 32
"""A synthetic token of the contract's shape; never a real one."""


def load_fixture(name: str) -> Any:
    """The decoded JSON of ``contract/fixtures/<name>.json``."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def error_body(code: str, message: str = "") -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


@dataclass
class Recorded:
    """One request the fake listener saw."""

    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]


@dataclass
class Override:
    """A canned answer for one path: status, JSON or raw body, extra headers."""

    status: int
    body: Any = None
    raw: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)


SECOND_PAGE_CURSOR = "page2"


def _second_page() -> dict[str, Any]:
    page = load_fixture("instruments")
    second = dict(page["data"][0])
    second.update(instrument="binance:futures:ETHUSDT", symbol="ETHUSDT", base="ETH")
    return {**page, "data": [second], "next_cursor": None}


class FakeTerminal:
    """A stand-in for the terminal's Local API listener."""

    def __init__(self) -> None:
        self.token = TOKEN
        self.requests: list[Recorded] = []
        self.overrides: dict[str, Override] = {}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silence the test output
                pass

            def do_GET(self) -> None:  # noqa: N802 - http.server naming
                fake._handle(self)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port: int = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def override(self, path: str, status: int, body: Any = None, **kwargs: Any) -> None:
        """Answer ``path`` (``/v1/...``) with ``status`` and ``body`` from now on."""
        self.overrides[path] = Override(status, body, **kwargs)

    @property
    def last(self) -> Recorded:
        return self.requests[-1]

    # --- serving ------------------------------------------------------------

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        parts = urlsplit(handler.path)
        headers = {key: value for key, value in handler.headers.items()}
        self.requests.append(Recorded(parts.path, parse_qs(parts.query), headers))
        status, body, extra = self._answer(parts.path, parse_qs(parts.query), headers)
        if isinstance(body, bytes):
            payload = body
            content_type = "text/plain"
        else:
            payload = json.dumps(body).encode("utf-8")
            content_type = "application/json"
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(payload)))
        for key, value in extra.items():
            handler.send_header(key, value)
        handler.end_headers()
        handler.wfile.write(payload)

    def _answer(
        self, path: str, query: dict[str, list[str]], headers: dict[str, str]
    ) -> tuple[int, Any, dict[str, str]]:
        if "Origin" in headers:
            return 403, error_body("forbidden", "requests from browser pages are not accepted"), {}
        if headers.get("Authorization") != f"Bearer {self.token}":
            return (
                401,
                error_body("unauthorized", "a valid bearer token is required"),
                {"WWW-Authenticate": "Bearer"},
            )
        override = self.overrides.get(path)
        if override is not None:
            body = override.raw if override.raw is not None else override.body
            return override.status, body, override.headers
        if path == "/v1/instruments":
            cursor = query.get("cursor", [None])[0]
            if cursor == SECOND_PAGE_CURSOR:
                return 200, _second_page(), {}
            return 200, {**load_fixture("instruments"), "next_cursor": SECOND_PAGE_CURSOR}, {}
        if path == "/v1/connections/12":
            return 200, load_fixture("connection"), {}
        if path.startswith("/v1/connections/"):
            return 404, error_body("not_found", "no such connection"), {}
        routes = {
            "/v1/meta": "meta",
            "/v1/health": "health",
            "/v1/connections": "connections",
            "/v1/market/candles": "candles",
            "/v1/market/intervals": "intervals",
            "/v1/market/trades": "trades",
            "/v1/market/snapshot": "snapshot",
            "/v1/market/orderbook": "orderbook",
            "/v1/market/clusters": "clusters",
        }
        name = routes.get(path)
        if name is None:
            return 404, load_fixture("error"), {}
        return 200, load_fixture(name), {}


@pytest.fixture
def fake_terminal() -> Iterator[FakeTerminal]:
    fake = FakeTerminal()
    try:
        yield fake
    finally:
        fake.close()
