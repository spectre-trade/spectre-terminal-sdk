"""Shared test fixtures: the contract fixtures and a fake Local API listener.

The fake listener is a stdlib ``http.server`` on a random loopback port that
serves the fixtures from ``../contract/fixtures``, enforces the token and the
``Origin`` rule the way the terminal does, and records every request so
tests can assert methods, URLs, query strings, headers and JSON bodies. No
real terminal, no network beyond loopback, and no order ever leaves it.
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
    """One request the fake listener saw. ``body`` is the decoded JSON body, ``None`` without."""

    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    method: str = "GET"
    body: Any = None


@dataclass
class Override:
    """A canned answer for one path: status, JSON or raw body, extra headers."""

    status: int
    body: Any = None
    raw: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)


SECOND_PAGE_CURSOR = "page2"
CONNECTION_ID = 12
"""The one connection the fixtures know."""

WRITE_PATHS = ("/v1/positions/close", "/v1/account/leverage", "/v1/account/margin-mode")
"""Writes outside ``/v1/orders``; ``/v1/account/leverage`` is a read on ``GET``."""

WINDOW_ID = 1
"""The one window the workspace fixtures know; ``2`` is used as a window that does not exist."""

ACCOUNT_ROUTES = {
    "/v1/account/leverage": "leverage",
    "/v1/account/orders": "account_orders",
    "/v1/account/positions": "account_positions",
    "/v1/account/balances": "account_balances",
    "/v1/account/fills": "account_fills",
}


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

            def do_POST(self) -> None:  # noqa: N802 - http.server naming
                fake._handle(self)

            def do_DELETE(self) -> None:  # noqa: N802 - http.server naming
                fake._handle(self)

            def do_PATCH(self) -> None:  # noqa: N802 - http.server naming
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
        length = int(headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length) if length else b""
        body_in = json.loads(raw) if raw else None
        self.requests.append(
            Recorded(parts.path, parse_qs(parts.query), headers, handler.command, body_in)
        )
        status, body, extra = self._answer(
            handler.command, parts.path, parse_qs(parts.query), headers, body_in
        )
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
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
        headers: dict[str, str],
        body_in: Any,
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
        if path.startswith("/v1/workspace"):
            return self._workspace(method, path, body_in)
        if path.startswith("/v1/settings"):
            return self._settings(method, path, query, body_in)
        if path.startswith("/v1/account/") and method == "GET":
            return self._account(path, query)
        if path.startswith("/v1/orders") or path in WRITE_PATHS:
            return self._trading(method, path, query, body_in)
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

    @staticmethod
    def _account(path: str, query: dict[str, list[str]]) -> tuple[int, Any, dict[str, str]]:
        """``/v1/account/*``: ``connection_id`` is required and only ``12`` exists."""
        if query.get("connection_id") != [str(CONNECTION_ID)]:
            return 404, error_body("not_found", "no such connection"), {}
        name = ACCOUNT_ROUTES.get(path)
        if name is None:
            return 404, load_fixture("error"), {}
        return 200, load_fixture(name), {}

    @staticmethod
    def _settings(
        method: str, path: str, query: dict[str, list[str]], body_in: Any
    ) -> tuple[int, Any, dict[str, str]]:
        """``/v1/settings*``: fixtures on read; a write answers the applied fixture.

        A change whose ``key`` is ``nope`` is ``invalid_request`` naming its
        index, ``leverage_mode`` is ``unsupported``, like the terminal.
        """
        if method == "GET" and path == "/v1/settings":
            if query.get("connection_id") not in (None, [str(CONNECTION_ID)]):
                return 404, error_body("not_found", "no such connection"), {}
            return 200, load_fixture("settings"), {}
        if method == "GET" and path == "/v1/settings/orderbook":
            if query.get("connection_id") != [str(CONNECTION_ID)]:
                return 400, error_body("invalid_request", "connection is not of this venue"), {}
            return 200, load_fixture("settings_orderbook"), {}
        if method == "PATCH" and path == "/v1/settings":
            changes = body_in.get("changes") if isinstance(body_in, dict) else None
            if not changes:
                return 400, error_body("invalid_request", "changes must not be empty"), {}
            for index, change in enumerate(changes):
                if change.get("key") == "nope":
                    return (
                        400,
                        error_body("invalid_request", f"changes[{index}]: unknown setting"),
                        {},
                    )
                if change.get("key") == "leverage_mode":
                    return (
                        501,
                        error_body(
                            "unsupported", f"changes[{index}]: leverage has its own operation"
                        ),
                        {},
                    )
            return 200, {"applied": len(changes)}, {}
        return 404, load_fixture("error"), {}

    @staticmethod
    def _workspace(method: str, path: str, body_in: Any) -> tuple[int, Any, dict[str, str]]:
        """``/v1/workspace*``: reads from the fixtures, writes answer the outcome fixture.

        Window ``1`` exists with tab ``1``; stack ``12`` exists; the main
        window refuses to close like the terminal does.
        """
        outcome = load_fixture("workspace_outcome")
        parts = path.split("/")[3:]  # after /v1/workspace
        if method == "GET":
            if not parts:
                return 200, load_fixture("workspace"), {}
            if parts == ["windows", str(WINDOW_ID)]:
                return 200, load_fixture("workspace_window"), {}
            if parts[:1] == ["windows"]:
                return 404, error_body("not_found", "no such window"), {}
            return 404, load_fixture("error"), {}
        if method == "POST" and parts == ["stacks"]:
            if not isinstance(body_in, dict) or body_in.get("instrument") == "binance:futures:NOPE":
                return 400, error_body("invalid_request", "unknown instrument"), {}
            return 200, outcome, {}
        if method == "POST" and parts == ["multiview"]:
            return 200, outcome, {}
        if parts[:1] == ["stacks"] and len(parts) == 2:
            if parts[1] != "12":
                return 404, error_body("not_found", "no stack with this widget_id"), {}
            if method in ("PATCH", "DELETE"):
                return 200, {**outcome, "stacks": [12], "charts": []}, {}
        if parts[:1] == ["windows"] and len(parts) >= 2:
            if parts[1] != str(WINDOW_ID):
                return 404, error_body("not_found", "no such window"), {}
            if len(parts) == 2 and method == "DELETE":
                return 400, error_body("invalid_request", "the main window cannot be closed"), {}
            if parts[2:] == ["activate"] and method == "POST":
                return 200, {**outcome, "tab_id": None, "stacks": [], "charts": []}, {}
            if parts[2:3] == ["tabs"] and len(parts) in (4, 5):
                if parts[3] != "1":
                    return 404, error_body("not_found", "no such tab"), {}
                if len(parts) == 4 and method == "DELETE":
                    return 400, error_body("invalid_request", "the only tab"), {}
                if parts[4:] == ["activate"] and method == "POST":
                    return 200, {**outcome, "tab_id": 1, "stacks": [], "charts": []}, {}
        return 404, load_fixture("error"), {}

    @staticmethod
    def _trading(
        method: str, path: str, query: dict[str, list[str]], body_in: Any
    ) -> tuple[int, Any, dict[str, str]]:
        """Every write of the contract answers ``accepted``; only placements carry a ``key``."""
        accepted = load_fixture("accepted")
        if method == "DELETE" and path.startswith("/v1/orders/"):
            if query.get("connection_id") != [str(CONNECTION_ID)]:
                return 404, error_body("not_found", "no such connection"), {}
            instrument = query.get("instrument", [accepted["instrument"]])[0]
            return 200, {**accepted, "key": None, "instrument": instrument}, {}
        if not isinstance(body_in, dict) or body_in.get("connection_id") != CONNECTION_ID:
            return 404, error_body("not_found", "no such connection"), {}
        instrument = body_in.get("instrument")
        if method == "POST" and path == "/v1/orders":
            return 200, {**accepted, "instrument": instrument}, {}
        if method == "POST" and path == "/v1/orders/trigger":
            return 200, {**accepted, "key": "sl_1730294400123", "instrument": instrument}, {}
        if method == "PATCH" and path.startswith("/v1/orders/trigger/"):
            return 200, {**accepted, "key": None, "instrument": instrument}, {}
        if method == "POST" and path in (
            "/v1/orders/cancel-all",
            "/v1/orders/trigger/cancel-all",
            "/v1/positions/close",
            "/v1/account/leverage",
            "/v1/account/margin-mode",
        ):
            return 200, {**accepted, "key": None, "instrument": instrument}, {}
        return 404, load_fixture("error"), {}


@pytest.fixture
def fake_terminal() -> Iterator[FakeTerminal]:
    fake = FakeTerminal()
    try:
        yield fake
    finally:
        fake.close()
