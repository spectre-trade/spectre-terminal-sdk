"""The HTTP client against a fake listener: headers, URLs, paging, errors."""

from __future__ import annotations

import socket
from decimal import Decimal

import pytest
from conftest import TOKEN, FakeTerminal

from spectre_terminal import (
    ApiError,
    Instrument,
    Level,
    SpectreTerminalError,
    Terminal,
    TerminalUnreachable,
    TokenMissing,
)


def client(fake: FakeTerminal, token: str = TOKEN) -> Terminal:
    return Terminal(token, port=fake.port, timeout=5)


def test_sends_bearer_and_accept_and_no_origin(fake_terminal: FakeTerminal) -> None:
    client(fake_terminal).meta()
    headers = fake_terminal.last.headers
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Accept"] == "application/json"
    assert "Origin" not in headers
    assert headers["Host"] == f"127.0.0.1:{fake_terminal.port}"


def test_meta_and_health(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    assert terminal.meta().api_version == "1"
    assert fake_terminal.last.path == "/v1/meta"
    assert terminal.health().status == "ok"
    assert fake_terminal.last.path == "/v1/health"
    assert fake_terminal.last.query == {}


def test_connections(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    connections = terminal.connections()
    assert fake_terminal.last.path == "/v1/connections"
    assert [c.id for c in connections] == [12]
    connection = terminal.connection(12)
    assert fake_terminal.last.path == "/v1/connections/12"
    assert connection.exchange == "binance" and connection.status.state == "connected"


def test_instruments_query(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    page = terminal.instruments(exchange="binance", market="futures", q="btc", limit=10)
    assert fake_terminal.last.path == "/v1/instruments"
    assert fake_terminal.last.query == {
        "exchange": ["binance"],
        "market": ["futures"],
        "q": ["btc"],
        "limit": ["10"],
    }
    assert page.exchange == "binance" and page.next_cursor == "page2"
    terminal.instruments(connection_id=12, cursor="page2")
    assert fake_terminal.last.query == {"connection_id": ["12"], "cursor": ["page2"]}


def test_iter_instruments_follows_next_cursor(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    instruments = list(terminal.iter_instruments(exchange="binance", market="futures", limit=1))
    assert [i.symbol for i in instruments] == ["BTCUSDT", "ETHUSDT"]
    assert all(isinstance(i, Instrument) for i in instruments)
    pages = [r for r in fake_terminal.requests if r.path == "/v1/instruments"]
    assert len(pages) == 2
    assert "cursor" not in pages[0].query
    assert pages[1].query["cursor"] == ["page2"]
    assert pages[1].query["limit"] == ["1"]


def test_intervals(fake_terminal: FakeTerminal) -> None:
    intervals = client(fake_terminal).intervals()
    assert fake_terminal.last.path == "/v1/market/intervals"
    assert intervals.candles[0].id == "1m"


def test_candles_query(fake_terminal: FakeTerminal) -> None:
    candles = client(fake_terminal).candles(
        "binance:futures:BTCUSDT", "1m", limit=5, end=1730294400000, connection_id=12
    )
    assert fake_terminal.last.path == "/v1/market/candles"
    assert fake_terminal.last.query == {
        "instrument": ["binance:futures:BTCUSDT"],
        "interval": ["1m"],
        "limit": ["5"],
        "end": ["1730294400000"],
        "connection_id": ["12"],
    }
    assert candles.data[0].close == Decimal("67003.4")


def test_trades_query(fake_terminal: FakeTerminal) -> None:
    trades = client(fake_terminal).trades("binance:futures:BTCUSDT", limit=50, since_ts=123)
    assert fake_terminal.last.path == "/v1/market/trades"
    assert fake_terminal.last.query == {
        "instrument": ["binance:futures:BTCUSDT"],
        "limit": ["50"],
        "since_ts": ["123"],
    }
    assert trades.connection_id == 12 and trades.data[0].id is None


def test_snapshot_query(fake_terminal: FakeTerminal) -> None:
    snapshot = client(fake_terminal).snapshot("binance:futures:BTCUSDT")
    assert fake_terminal.last.path == "/v1/market/snapshot"
    assert fake_terminal.last.query == {"instrument": ["binance:futures:BTCUSDT"]}
    assert snapshot.best_bid == Level(Decimal("67000.1"), Decimal("1.25"))
    assert isinstance(snapshot.best_bid.price, Decimal)


def test_orderbook_query(fake_terminal: FakeTerminal) -> None:
    book = client(fake_terminal).orderbook("binance:futures:BTCUSDT", depth=20, connection_id=12)
    assert fake_terminal.last.path == "/v1/market/orderbook"
    assert fake_terminal.last.query == {
        "instrument": ["binance:futures:BTCUSDT"],
        "depth": ["20"],
        "connection_id": ["12"],
    }
    assert book.instrument == "binance:futures:BTCUSDT" and book.depth == 20


def test_clusters_query(fake_terminal: FakeTerminal) -> None:
    clusters = client(fake_terminal).clusters("binance:futures:BTCUSDT")
    assert fake_terminal.last.path == "/v1/market/clusters"
    assert fake_terminal.last.query == {"instrument": ["binance:futures:BTCUSDT"]}
    assert clusters.data[0].levels[0].price == Decimal("67000.1")


def test_unauthorized(fake_terminal: FakeTerminal) -> None:
    with pytest.raises(ApiError) as excinfo:
        client(fake_terminal, token="spt_" + "00" * 32).meta()
    error = excinfo.value
    assert (error.code, error.status) == ("unauthorized", 401)
    assert "token" in error.message
    assert isinstance(error, SpectreTerminalError)


def test_not_found(fake_terminal: FakeTerminal) -> None:
    with pytest.raises(ApiError) as excinfo:
        client(fake_terminal).connection(99)
    assert (excinfo.value.code, excinfo.value.status) == ("not_found", 404)


def test_rate_limited(fake_terminal: FakeTerminal) -> None:
    fake_terminal.override(
        "/v1/market/trades",
        429,
        {"error": {"code": "rate_limited", "message": "too many subscriptions"}},
    )
    with pytest.raises(ApiError) as excinfo:
        client(fake_terminal).trades("binance:futures:BTCUSDT")
    error = excinfo.value
    assert (error.code, error.status, error.message) == (
        "rate_limited",
        429,
        "too many subscriptions",
    )
    assert str(error) == "429 rate_limited: too many subscriptions"


def test_not_active_and_unavailable(fake_terminal: FakeTerminal) -> None:
    fake_terminal.override(
        "/v1/market/clusters", 409, {"error": {"code": "not_active", "message": ""}}
    )
    with pytest.raises(ApiError, match="not_active") as excinfo:
        client(fake_terminal).clusters("binance:futures:BTCUSDT")
    assert excinfo.value.status == 409
    fake_terminal.override(
        "/v1/market/orderbook", 503, {"error": {"code": "unavailable", "message": ""}}
    )
    with pytest.raises(ApiError, match="unavailable"):
        client(fake_terminal).orderbook("binance:futures:BTCUSDT")


def test_non_json_error_body(fake_terminal: FakeTerminal) -> None:
    fake_terminal.override("/v1/meta", 500, raw=b"boom")
    with pytest.raises(ApiError) as excinfo:
        client(fake_terminal).meta()
    assert (excinfo.value.code, excinfo.value.message, excinfo.value.status) == (
        "unknown",
        "boom",
        500,
    )


def test_non_json_success_body(fake_terminal: FakeTerminal) -> None:
    fake_terminal.override("/v1/meta", 200, raw=b"<html>")
    with pytest.raises(SpectreTerminalError, match="non-JSON"):
        client(fake_terminal).meta()


def test_redirect_is_not_followed(fake_terminal: FakeTerminal) -> None:
    fake_terminal.override(
        "/v1/meta", 302, raw=b"", headers={"Location": "http://example.invalid/"}
    )
    with pytest.raises(ApiError) as excinfo:
        client(fake_terminal).meta()
    assert excinfo.value.status == 302
    assert [r.path for r in fake_terminal.requests] == ["/v1/meta"]


def test_unreachable_on_closed_port() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(TerminalUnreachable) as excinfo:
        Terminal(TOKEN, port=port, timeout=2).meta()
    assert str(port) in str(excinfo.value)


def test_rejects_non_loopback_host_and_empty_token() -> None:
    with pytest.raises(ValueError):
        Terminal(TOKEN, host="example.invalid")
    with pytest.raises(TokenMissing):
        Terminal("")
    assert Terminal(TOKEN, host="localhost").base_url == "http://localhost:48180/v1"


def test_token_never_appears_in_errors_or_repr(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    assert TOKEN not in repr(terminal)
    assert TOKEN not in repr(vars(terminal).get("_opener"))
    fake_terminal.override("/v1/market/snapshot", 500, raw=b"boom")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    attempts = [
        lambda: client(fake_terminal, token="spt_" + "00" * 32).meta(),
        lambda: terminal.connection(99),
        lambda: terminal.snapshot("binance:futures:BTCUSDT"),
        lambda: Terminal(TOKEN, port=closed_port, timeout=2).meta(),
    ]
    for attempt in attempts:
        with pytest.raises(SpectreTerminalError) as excinfo:
            attempt()
        assert TOKEN not in str(excinfo.value)
        assert TOKEN not in repr(excinfo.value)
        assert TOKEN not in repr(vars(excinfo.value))
