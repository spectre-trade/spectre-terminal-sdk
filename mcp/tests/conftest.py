"""A fake Local API serving the contract fixtures, and a provider pointed at it."""

from __future__ import annotations

import json
import pathlib
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from spectre_terminal import Terminal

from spectre_terminal_mcp.terminal import TerminalProvider

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "contract" / "fixtures"
TOKEN = "spt_" + "ab" * 32

ROUTES = {
    "/v1/meta": "meta.json",
    "/v1/health": "health.json",
    "/v1/connections": "connections.json",
    "/v1/connections/12": "connection.json",
    "/v1/instruments": "instruments.json",
    "/v1/market/intervals": "intervals.json",
    "/v1/market/candles": "candles.json",
    "/v1/market/trades": "trades.json",
    "/v1/market/snapshot": "snapshot.json",
    "/v1/market/orderbook": "orderbook.json",
    "/v1/market/clusters": "clusters.json",
}


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeApi(ThreadingHTTPServer):
    """Serves fixtures; records every request; one 409 for a ``cold:`` cluster instrument."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests: list[tuple[str, dict[str, list[str]], dict[str, str]]] = []
        self.cold_served = False

    @property
    def port(self) -> int:
        return self.server_address[1]


class _Handler(BaseHTTPRequestHandler):
    server: FakeApi

    def log_message(self, *_args: object) -> None:  # keep pytest output clean
        pass

    def _send(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: int, code: str, message: str) -> None:
        self._send(status, {"error": {"code": code, "message": message}})

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        url = urlparse(self.path)
        query = parse_qs(url.query)
        self.server.requests.append((url.path, query, dict(self.headers)))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._error(401, "unauthorized", "token does not match")
            return
        instrument = query.get("instrument", [""])[0]
        if instrument.startswith("moex:"):
            self._error(501, "unsupported", "market data of moex is not relayed")
            return
        if url.path == "/v1/market/clusters" and instrument.startswith("cold:"):
            if not self.server.cold_served:
                self.server.cold_served = True
                self._error(409, "not_active", "clusters are not computed yet")
                return
        fixture = ROUTES.get(url.path)
        if fixture is None:
            self._error(404, "not_found", "no such operation")
            return
        body = load_fixture(fixture)
        if url.path == "/v1/instruments" and "cursor" in query:
            body = {**body, "data": [], "next_cursor": None}
        self._send(200, body)


@pytest.fixture
def fake_api() -> Iterator[FakeApi]:
    server = FakeApi()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def provider(fake_api: FakeApi) -> TerminalProvider:
    return TerminalProvider(factory=lambda: Terminal(TOKEN, port=fake_api.port))
