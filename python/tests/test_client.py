"""The HTTP client against a fake listener: headers, URLs, paging, errors."""

from __future__ import annotations

import socket
from decimal import Decimal

import pytest
from conftest import TOKEN, FakeTerminal

from spectre_terminal import (
    Accepted,
    ApiError,
    Fill,
    Instrument,
    Level,
    Order,
    Position,
    SettingChange,
    SpectreTerminalError,
    TabItem,
    Terminal,
    TerminalUnreachable,
    TokenMissing,
)

INSTRUMENT = "binance:futures:BTCUSDT"


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


# --- account ------------------------------------------------------------------


def test_account_orders_query(fake_terminal: FakeTerminal) -> None:
    orders = client(fake_terminal).account_orders(12)
    assert fake_terminal.last.method == "GET"
    assert fake_terminal.last.path == "/v1/account/orders"
    assert fake_terminal.last.query == {"connection_id": ["12"]}
    assert fake_terminal.last.body is None
    assert orders.connection_id == 12
    assert isinstance(orders.data[0], Order) and orders.data[0].order_type == "limit"
    assert orders.triggers[0].trigger_type == "stop_loss"


def test_account_positions_query(fake_terminal: FakeTerminal) -> None:
    positions = client(fake_terminal).account_positions(12)
    assert fake_terminal.last.path == "/v1/account/positions"
    assert fake_terminal.last.query == {"connection_id": ["12"]}
    assert isinstance(positions.data[0], Position)
    assert positions.data[0].mark_price == Decimal("67000")


def test_account_balances_query(fake_terminal: FakeTerminal) -> None:
    balances = client(fake_terminal).account_balances(12)
    assert fake_terminal.last.path == "/v1/account/balances"
    assert fake_terminal.last.query == {"connection_id": ["12"]}
    assert balances.data[0].currency == "USDT" and balances.data[0].total == Decimal("1000.5")


def test_account_fills_query(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    fills = terminal.account_fills(12)
    assert fake_terminal.last.path == "/v1/account/fills"
    assert fake_terminal.last.query == {"connection_id": ["12"]}
    assert isinstance(fills.data[0], Fill) and fills.data[0].price == Decimal("67000.1")
    terminal.account_fills(12, limit=50, since_ts=1730294400000)
    assert fake_terminal.last.query == {
        "connection_id": ["12"],
        "limit": ["50"],
        "since_ts": ["1730294400000"],
    }


def test_account_unknown_connection_is_not_found(fake_terminal: FakeTerminal) -> None:
    with pytest.raises(ApiError) as excinfo:
        client(fake_terminal).account_orders(99)
    assert (excinfo.value.code, excinfo.value.status) == ("not_found", 404)


# --- trading ------------------------------------------------------------------


def test_place_order_posts_json(fake_terminal: FakeTerminal) -> None:
    accepted = client(fake_terminal).place_order(
        12,
        INSTRUMENT,
        side="buy",
        order_type="limit",
        price=Decimal("67000.10"),
        size="0.012",
        post_only=True,
        time_in_force="gtc",
        client_key="bot-42",
    )
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/orders"
    assert request.query == {}
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Accept"] == "application/json"
    assert "Origin" not in request.headers
    assert request.body == {
        "connection_id": 12,
        "instrument": INSTRUMENT,
        "side": "buy",
        "type": "limit",
        "price": "67000.10",
        "size": "0.012",
        "reduce_only": False,
        "post_only": True,
        "time_in_force": "gtc",
        "client_key": "bot-42",
    }
    assert isinstance(request.body["price"], str), "money travels as a string, never a number"
    assert isinstance(request.body["post_only"], bool)
    assert isinstance(accepted, Accepted)
    assert accepted.accepted is True and accepted.key == "t-173029440012300001"
    assert accepted.connection_id == 12 and accepted.instrument == INSTRUMENT


def test_place_market_order_by_notional(fake_terminal: FakeTerminal) -> None:
    client(fake_terminal).place_order(
        12, INSTRUMENT, side="sell", order_type="market", notional=100, reduce_only=True
    )
    body = fake_terminal.last.body
    assert body["type"] == "market" and body["side"] == "sell"
    assert "price" not in body and "size" not in body
    assert body["notional"] == "100" and isinstance(body["notional"], str)
    assert body["reduce_only"] is True and body["post_only"] is False
    assert "time_in_force" not in body and "client_key" not in body


def test_place_order_money_is_exact(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    terminal.place_order(
        12, INSTRUMENT, side="buy", order_type="limit", price=Decimal("1E+2"), size=Decimal("0.50")
    )
    assert fake_terminal.last.body["price"] == "100"
    assert fake_terminal.last.body["size"] == "0.50", "no normalisation of money strings"
    with pytest.raises(TypeError):
        terminal.place_order(12, INSTRUMENT, side="buy", order_type="limit", price=1.5, size="1")
    assert fake_terminal.last.body["size"] == "0.50", "a float never reaches the terminal"


def test_place_order_needs_exactly_one_amount(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    with pytest.raises(ValueError, match="size and notional"):
        terminal.place_order(12, INSTRUMENT, side="buy", order_type="market")
    with pytest.raises(ValueError, match="size and notional"):
        terminal.place_order(
            12, INSTRUMENT, side="buy", order_type="market", size="1", notional="100"
        )
    assert fake_terminal.requests == [], "refused before any request"


def test_cancel_order_deletes_with_query(fake_terminal: FakeTerminal) -> None:
    accepted = client(fake_terminal).cancel_order(12, INSTRUMENT, "t-173029440012300001")
    request = fake_terminal.last
    assert request.method == "DELETE"
    assert request.path == "/v1/orders/t-173029440012300001"
    assert request.query == {"connection_id": ["12"], "instrument": [INSTRUMENT]}
    assert request.body is None and "Content-Type" not in request.headers
    assert accepted.key is None and accepted.instrument == INSTRUMENT
    client(fake_terminal).cancel_order(12, INSTRUMENT, "987654321")
    assert fake_terminal.last.path == "/v1/orders/987654321"


def test_cancel_order_id_is_url_escaped(fake_terminal: FakeTerminal) -> None:
    client(fake_terminal).cancel_order(12, INSTRUMENT, "a/b?c")
    assert fake_terminal.last.path == "/v1/orders/a%2Fb%3Fc"
    assert fake_terminal.last.query == {"connection_id": ["12"], "instrument": [INSTRUMENT]}


def test_cancel_all_and_close_position_post_json(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    accepted = terminal.cancel_all(12, INSTRUMENT)
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/orders/cancel-all"
    assert request.headers["Content-Type"] == "application/json"
    assert request.body == {"connection_id": 12, "instrument": INSTRUMENT}
    assert accepted.key is None and accepted.operation_id == "1730294400123-000001"
    accepted = terminal.close_position(12, INSTRUMENT)
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/positions/close"
    assert request.body == {"connection_id": 12, "instrument": INSTRUMENT}
    assert accepted.key is None


def test_place_trigger_posts_json(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    accepted = terminal.place_trigger(
        12, INSTRUMENT, kind="stop_loss", trigger_price=Decimal("66000"), client_key="sl-42"
    )
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/orders/trigger"
    assert request.body == {
        "connection_id": 12,
        "instrument": INSTRUMENT,
        "kind": "stop_loss",
        "trigger_price": "66000",
        "client_key": "sl-42",
    }
    assert accepted.key == "sl_1730294400123" and accepted.instrument == INSTRUMENT

    terminal.place_trigger(
        12,
        INSTRUMENT,
        kind="stop",
        side="sell",
        notional="800",
        trigger_price="66000",
        rule="price_below_or_equal",
    )
    assert fake_terminal.last.body == {
        "connection_id": 12,
        "instrument": INSTRUMENT,
        "kind": "stop",
        "trigger_price": "66000",
        "side": "sell",
        "notional": "800",
        "rule": "price_below_or_equal",
    }


def test_place_trigger_checks_the_fields_of_its_kind(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    with pytest.raises(ValueError):
        terminal.place_trigger(12, INSTRUMENT, kind="stop", trigger_price="1")
    with pytest.raises(ValueError):
        terminal.place_trigger(12, INSTRUMENT, kind="take_profit", trigger_price="1", side="buy")
    with pytest.raises(ValueError):
        terminal.amend_trigger(12, INSTRUMENT, 42, kind="stop", trigger_price="1")
    with pytest.raises(TypeError):
        terminal.place_trigger(12, INSTRUMENT, kind="stop_loss", trigger_price=1.5)
    assert fake_terminal.requests == []


def test_cancel_and_amend_trigger(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    accepted = terminal.cancel_trigger(12, INSTRUMENT, 42)
    request = fake_terminal.last
    assert request.method == "DELETE" and request.path == "/v1/orders/trigger/42"
    assert request.query == {"connection_id": ["12"], "instrument": [INSTRUMENT]}
    assert request.body is None and accepted.key is None

    accepted = terminal.amend_trigger(12, INSTRUMENT, "42", kind="stop_loss", trigger_price="65500")
    request = fake_terminal.last
    assert request.method == "PATCH" and request.path == "/v1/orders/trigger/42"
    assert request.headers["Content-Type"] == "application/json"
    assert request.body == {
        "connection_id": 12,
        "instrument": INSTRUMENT,
        "kind": "stop_loss",
        "trigger_price": "65500",
    }
    assert accepted.key is None

    terminal.amend_trigger(12, INSTRUMENT, 42, kind="stop", trigger_price="65500", side="sell")
    assert fake_terminal.last.body["side"] == "sell" and "rule" not in fake_terminal.last.body

    accepted = terminal.cancel_all_triggers(12, INSTRUMENT)
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/orders/trigger/cancel-all"
    assert request.body == {"connection_id": 12, "instrument": INSTRUMENT}
    assert accepted.key is None


def test_leverage_reads_and_writes(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    leverage = terminal.leverage(12, INSTRUMENT)
    request = fake_terminal.last
    assert request.method == "GET" and request.path == "/v1/account/leverage"
    assert request.query == {"connection_id": ["12"], "instrument": [INSTRUMENT]}
    assert (leverage.leverage, leverage.max_leverage) == (10, 125)
    assert (leverage.mode, leverage.margin_mode) == ("manual", "cross")

    accepted = terminal.set_leverage(12, INSTRUMENT, leverage=20)
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/account/leverage"
    assert request.body == {"connection_id": 12, "instrument": INSTRUMENT, "leverage": 20}
    assert accepted.key is None

    terminal.set_leverage(12, INSTRUMENT, mode="max")
    assert fake_terminal.last.body == {"connection_id": 12, "instrument": INSTRUMENT, "mode": "max"}

    accepted = terminal.set_margin_mode(12, INSTRUMENT, "isolated")
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/account/margin-mode"
    assert request.body == {
        "connection_id": 12,
        "instrument": INSTRUMENT,
        "margin_mode": "isolated",
    }
    assert accepted.key is None


def test_set_leverage_needs_exactly_one_of_value_and_mode(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    with pytest.raises(ValueError):
        terminal.set_leverage(12, INSTRUMENT)
    with pytest.raises(ValueError):
        terminal.set_leverage(12, INSTRUMENT, leverage=5, mode="max")
    with pytest.raises(ValueError):
        terminal.set_leverage(12, INSTRUMENT, leverage=0)
    assert fake_terminal.requests == []


def test_leverage_not_active_keeps_its_code(fake_terminal: FakeTerminal) -> None:
    fake_terminal.override(
        "/v1/account/leverage",
        409,
        {"error": {"code": "not_active", "message": "leverage is not loaded yet"}},
    )
    with pytest.raises(ApiError) as error:
        client(fake_terminal).leverage(12, INSTRUMENT)
    assert (error.value.code, error.value.status) == ("not_active", 409)


def test_not_tradable(fake_terminal: FakeTerminal) -> None:
    fake_terminal.override(
        "/v1/orders",
        409,
        {"error": {"code": "not_tradable", "message": "connection 12 is read-only"}},
    )
    with pytest.raises(ApiError) as excinfo:
        client(fake_terminal).place_order(
            12, INSTRUMENT, side="buy", order_type="limit", price="1", size="1"
        )
    error = excinfo.value
    assert (error.code, error.status) == ("not_tradable", 409)
    assert str(error) == "409 not_tradable: connection 12 is read-only"
    assert TOKEN not in str(error) and TOKEN not in repr(vars(error))


def test_trading_refusals_keep_their_codes(fake_terminal: FakeTerminal) -> None:
    fake_terminal.override(
        "/v1/orders/cancel-all", 429, {"error": {"code": "rate_limited", "message": "10/s"}}
    )
    with pytest.raises(ApiError, match="rate_limited") as excinfo:
        client(fake_terminal).cancel_all(12, INSTRUMENT)
    assert excinfo.value.status == 429
    fake_terminal.override(
        "/v1/positions/close",
        400,
        {"error": {"code": "invalid_request", "message": "no open position"}},
    )
    with pytest.raises(ApiError, match="invalid_request"):
        client(fake_terminal).close_position(12, INSTRUMENT)
    fake_terminal.override(
        "/v1/orders", 503, {"error": {"code": "unavailable", "message": "queue full"}}
    )
    with pytest.raises(ApiError, match="unavailable"):
        client(fake_terminal).place_order(12, INSTRUMENT, side="buy", order_type="market", size="1")


# --- errors -------------------------------------------------------------------


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
    fake_terminal.override(
        "/v1/orders", 409, {"error": {"code": "not_tradable", "message": "read-only"}}
    )
    attempts = [
        lambda: client(fake_terminal, token="spt_" + "00" * 32).meta(),
        lambda: terminal.connection(99),
        lambda: terminal.snapshot("binance:futures:BTCUSDT"),
        lambda: terminal.account_orders(99),
        lambda: terminal.place_order(12, INSTRUMENT, side="buy", order_type="market", size="1"),
        lambda: Terminal(TOKEN, port=closed_port, timeout=2).meta(),
    ]
    for attempt in attempts:
        with pytest.raises(SpectreTerminalError) as excinfo:
            attempt()
        assert TOKEN not in str(excinfo.value)
        assert TOKEN not in repr(excinfo.value)
        assert TOKEN not in repr(vars(excinfo.value))


# --- workspace ----------------------------------------------------------------


def test_workspace_reads_the_snapshot_and_one_window(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    workspace = terminal.workspace()
    assert fake_terminal.last.method == "GET" and fake_terminal.last.path == "/v1/workspace"
    assert workspace.main is not None and workspace.main.id == 1
    tab = workspace.main.active_tab
    assert tab is not None and tab.name == "XRP"
    stack = workspace.stack(12)
    assert stack is not None and stack.position is not None and stack.position.column == 0
    assert tab.charts[0].interval == "5m"

    window = terminal.workspace_window(1)
    assert fake_terminal.last.path == "/v1/workspace/windows/1"
    assert window.main and window.width == 1920 and window.maximized
    assert window.tab(1) is not None and window.tab(2) is None

    with pytest.raises(ApiError) as error:
        terminal.workspace_window(2)
    assert (error.value.code, error.value.status) == ("not_found", 404)


def test_open_stack_and_multiview_send_their_bodies(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    outcome = terminal.open_stack(INSTRUMENT, chart=True, window_id=1, activate=False)
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/workspace/stacks"
    assert request.body == {
        "instrument": INSTRUMENT,
        "chart": True,
        "target": "new_tab",
        "window_id": 1,
        "activate": False,
    }
    assert (outcome.window_id, outcome.tab_id, outcome.stacks) == (1, 2, [14])

    terminal.open_stack(INSTRUMENT, connection_id=12, target="new_window")
    assert fake_terminal.last.body == {
        "instrument": INSTRUMENT,
        "chart": False,
        "target": "new_window",
        "activate": True,
        "connection_id": 12,
    }
    with pytest.raises(ValueError):
        terminal.open_stack(INSTRUMENT, target="somewhere")

    terminal.open_multiview("BTC")
    request = fake_terminal.last
    assert request.path == "/v1/workspace/multiview"
    assert request.body == {"base": "BTC", "activate": True}
    terminal.open_multiview("BTC", target="new_window", window_id=1, activate=False)
    assert fake_terminal.last.body == {
        "base": "BTC",
        "activate": False,
        "target": "new_window",
        "window_id": 1,
    }

    with pytest.raises(ApiError) as error:
        terminal.open_stack("binance:futures:NOPE")
    assert error.value.code == "invalid_request"


def test_open_tab_and_add_stacks_send_their_columns(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    outcome = terminal.open_tab(
        [TabItem(INSTRUMENT, chart=True), TabItem("binance:futures:ETHUSDT", connection_id=12)],
        name="Majors",
        window_id=1,
        activate=False,
    )
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/workspace/tabs"
    assert request.body == {
        "items": [
            {"instrument": INSTRUMENT, "chart": True},
            {"instrument": "binance:futures:ETHUSDT", "chart": False, "connection_id": 12},
        ],
        "target": "new_tab",
        "activate": False,
        "name": "Majors",
        "window_id": 1,
    }
    assert (outcome.stacks, outcome.charts) == ([20, 22], [21])

    # Bare addresses are stacks without charts; the defaults are not sent.
    terminal.open_tab([INSTRUMENT, "binance:futures:ETHUSDT"], target="new_window")
    assert fake_terminal.last.body == {
        "items": [
            {"instrument": INSTRUMENT, "chart": False},
            {"instrument": "binance:futures:ETHUSDT", "chart": False},
        ],
        "target": "new_window",
        "activate": True,
    }

    added = terminal.add_stacks(1, 1, [TabItem("binance:futures:SOLUSDT", chart=True)])
    request = fake_terminal.last
    assert request.method == "POST"
    assert request.path == "/v1/workspace/windows/1/tabs/1/stacks"
    assert request.body == {"items": [{"instrument": "binance:futures:SOLUSDT", "chart": True}]}
    assert added.stacks == [20, 22]

    with pytest.raises(ValueError):
        terminal.open_tab([])
    with pytest.raises(ValueError):
        terminal.open_tab(INSTRUMENT)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        terminal.open_tab([INSTRUMENT], target="somewhere")
    with pytest.raises(ApiError) as error:
        terminal.open_tab([INSTRUMENT, "binance:futures:NOPE"])
    assert error.value.code == "invalid_request"
    assert "items[1]" in error.value.message


def test_stack_tab_and_window_commands_use_their_routes(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    outcome = terminal.set_stack_instrument(12, INSTRUMENT, connection_id=12)
    request = fake_terminal.last
    assert request.method == "PATCH" and request.path == "/v1/workspace/stacks/12"
    assert request.body == {"instrument": INSTRUMENT, "connection_id": 12}
    assert outcome.stacks == [12]

    terminal.close_stack(12)
    request = fake_terminal.last
    assert request.method == "DELETE" and request.path == "/v1/workspace/stacks/12"
    assert request.body is None

    terminal.activate_tab(1, 1)
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/workspace/windows/1/tabs/1/activate"

    terminal.activate_window(1)
    request = fake_terminal.last
    assert request.method == "POST" and request.path == "/v1/workspace/windows/1/activate"

    with pytest.raises(ApiError) as error:
        terminal.close_tab(1, 1)
    assert (error.value.code, error.value.status) == ("invalid_request", 400)
    assert fake_terminal.last.method == "DELETE"
    assert fake_terminal.last.path == "/v1/workspace/windows/1/tabs/1"

    with pytest.raises(ApiError) as error:
        terminal.close_window(1)
    assert error.value.code == "invalid_request"

    with pytest.raises(ApiError) as error:
        terminal.close_stack(99)
    assert error.value.code == "not_found"


# --- settings -----------------------------------------------------------------


def test_settings_reads_rows_and_the_orderbook_ladder(fake_terminal: FakeTerminal) -> None:
    terminal = client(fake_terminal)
    settings = terminal.settings(category="multiview", key="stack_width_px")
    request = fake_terminal.last
    assert request.method == "GET" and request.path == "/v1/settings"
    assert request.query == {"category": ["multiview"], "key": ["stack_width_px"]}
    row = settings.get("multiview", "stack_width_px")
    assert row is not None and row.value == 250 and row.writable is True
    assert row.scope == "global" and row.scope_id == "default" and row.connection_id is None

    terminal.settings(instrument=INSTRUMENT, connection_id=12, scope="order_book")
    assert fake_terminal.last.query == {
        "instrument": [INSTRUMENT],
        "connection_id": ["12"],
        "scope": ["order_book"],
    }
    with pytest.raises(ApiError) as error:
        terminal.settings(connection_id=77)
    assert error.value.code == "not_found"

    book = terminal.orderbook_settings(12, INSTRUMENT)
    request = fake_terminal.last
    assert request.path == "/v1/settings/orderbook"
    assert request.query == {"connection_id": ["12"], "instrument": [INSTRUMENT]}
    assert book.connection_id == 12 and book.instrument == INSTRUMENT
    auto_scroll = book.get("general", "auto_scroll")
    assert auto_scroll is not None
    assert (auto_scroll.value, auto_scroll.resolved_from, auto_scroll.writable) == (
        False,
        "global",
        True,
    )
    assert book.get("general", "nope") is None
    with pytest.raises(ApiError) as error:
        terminal.orderbook_settings(77, INSTRUMENT)
    assert error.value.code == "invalid_request"


def test_update_settings_sends_the_changes_and_keeps_the_refusal_index(
    fake_terminal: FakeTerminal,
) -> None:
    terminal = client(fake_terminal)
    applied = terminal.update_settings(
        [
            SettingChange("multiview", "stack_width_px", 300),
            SettingChange("general", "auto_scroll", True, instrument=INSTRUMENT, connection_id=12),
            SettingChange("general", "trim_trailing_zeros", False, scope="order_book"),
        ]
    )
    request = fake_terminal.last
    assert request.method == "PATCH" and request.path == "/v1/settings"
    assert request.body == {
        "changes": [
            {"category": "multiview", "key": "stack_width_px", "value": 300},
            {
                "category": "general",
                "key": "auto_scroll",
                "value": True,
                "instrument": INSTRUMENT,
                "connection_id": 12,
            },
            {
                "category": "general",
                "key": "trim_trailing_zeros",
                "value": False,
                "scope": "order_book",
            },
        ]
    }
    assert applied.applied == 3

    with pytest.raises(ValueError):
        terminal.update_settings([])
    with pytest.raises(ApiError) as error:
        terminal.update_settings(
            [SettingChange("multiview", "open_mode", "tab"), SettingChange("nope", "nope", 1)]
        )
    assert error.value.code == "invalid_request"
    assert "changes[1]" in str(error.value)
    with pytest.raises(ApiError) as error:
        terminal.update_settings(
            [SettingChange("trading", "leverage_mode", {"mode": "max"}, scope="order_book")]
        )
    assert (error.value.code, error.value.status) == ("unsupported", 501)
