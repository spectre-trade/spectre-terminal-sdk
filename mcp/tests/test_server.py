"""The server in-process: tool list, schemas, answers and error mapping."""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from spectre_terminal.errors import TerminalUnreachable

from spectre_terminal_mcp import tools
from spectre_terminal_mcp.server import build_server
from spectre_terminal_mcp.terminal import TerminalProvider
from spectre_terminal_mcp.tools import market

from .conftest import TOKEN, FakeApi

EXPECTED_TOOLS = {
    "terminal_status",
    "find_instrument",
    "market_snapshot",
    "order_book_top",
    "recent_trades_summary",
    "cluster_summary",
    "candles",
    "account_overview",
    "open_orders",
    "recent_fills",
    "leverage",
    "place_order",
    "cancel_order",
    "cancel_all_orders",
    "close_position",
    "place_trigger",
    "cancel_trigger",
    "cancel_all_triggers",
    "amend_trigger",
    "set_leverage",
    "set_margin_mode",
    "workspace",
    "open_stack",
    "open_tab",
    "add_stacks",
    "open_multiview",
    "set_stack_instrument",
    "close_stack",
    "close_tab",
    "activate_tab",
    "close_window",
    "activate_window",
    "settings",
    "orderbook_settings",
    "update_settings",
}
TRADING_TOOLS = {
    "place_order",
    "cancel_order",
    "cancel_all_orders",
    "close_position",
    "place_trigger",
    "cancel_trigger",
    "cancel_all_triggers",
    "amend_trigger",
    "set_leverage",
    "set_margin_mode",
    "open_stack",
    "open_tab",
    "add_stacks",
    "open_multiview",
    "set_stack_instrument",
    "close_stack",
    "close_tab",
    "activate_tab",
    "close_window",
    "activate_window",
    "update_settings",
}


async def test_tools_are_registered_read_only(provider: TerminalProvider) -> None:
    server = build_server(provider)
    listed = await server.list_tools()
    assert {tool.name for tool in listed} == EXPECTED_TOOLS
    for tool in listed:
        assert tool.description, tool.name
        assert tool.input_schema["type"] == "object"
        assert tool.annotations is not None
        if tool.name in TRADING_TOOLS:
            assert tool.annotations.read_only_hint is False, tool.name
            assert tool.annotations.destructive_hint is True, tool.name
        else:
            assert tool.annotations.read_only_hint is True, tool.name
    place = next(t for t in listed if t.name == "place_order").input_schema
    assert "client_key" in place["required"], "the idempotency key is required"
    trigger = next(t for t in listed if t.name == "place_trigger").input_schema
    assert "client_key" in trigger["required"]
    schema = next(t for t in listed if t.name == "order_book_top").input_schema
    assert schema["required"] == ["instrument"]
    assert schema["properties"]["depth"]["maximum"] == 50


def _error_text(error: BaseException) -> str:
    """The message and its whole cause chain: the code may sit on the cause."""
    parts = []
    current: BaseException | None = error
    while current is not None:
        parts.append(str(current))
        current = current.__cause__
    return " | ".join(parts)


def _structured(result) -> dict:
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def test_terminal_status(provider: TerminalProvider, fake_api: FakeApi) -> None:
    server = build_server(provider)
    result = await server.call_tool("terminal_status", {})
    status = _structured(result)
    assert status["api_version"] == "1"
    assert status["connections"][0]["exchange"] == "binance"
    paths = [path for path, _query, _headers in fake_api.requests]
    assert paths == ["/v1/meta", "/v1/health", "/v1/connections"]
    assert all(h.get("Authorization") == f"Bearer {TOKEN}" for _p, _q, h in fake_api.requests)
    assert all("Origin" not in h for _p, _q, h in fake_api.requests)


async def test_market_snapshot_and_book(provider: TerminalProvider, fake_api: FakeApi) -> None:
    server = build_server(provider)
    snapshot = _structured(
        await server.call_tool("market_snapshot", {"instrument": "binance:futures:BTCUSDT"})
    )
    assert snapshot["best_bid"] == ["67000.1", "1.25"]
    assert snapshot["mark_price"] == "67001.0"
    book = _structured(
        await server.call_tool(
            "order_book_top", {"instrument": "binance:futures:BTCUSDT", "depth": 1}
        )
    )
    assert len(book["bids"]) == 1 and len(book["asks"]) == 1
    path, query, _headers = fake_api.requests[-1]
    assert path == "/v1/market/orderbook"
    assert query["depth"] == ["1"]
    assert query["instrument"] == ["binance:futures:BTCUSDT"]


async def test_trades_clusters_candles(provider: TerminalProvider, fake_api: FakeApi) -> None:
    server = build_server(provider)
    trades = _structured(
        await server.call_tool(
            "recent_trades_summary", {"instrument": "binance:futures:BTCUSDT", "limit": 5}
        )
    )
    assert trades["count"] >= 1 and "vwap" in trades
    assert fake_api.requests[-1][1]["limit"] == ["5"]

    clusters = _structured(
        await server.call_tool(
            "cluster_summary",
            {"instrument": "binance:futures:BTCUSDT", "buckets": 1, "top_levels": 1},
        )
    )
    assert len(clusters["buckets"]) == 1
    assert len(clusters["buckets"][0]["top_levels"]) <= 1

    candles = _structured(
        await server.call_tool(
            "candles", {"instrument": "binance:futures:BTCUSDT", "interval": "5m", "limit": 3}
        )
    )
    assert candles["columns"][0] == "ts"
    query = fake_api.requests[-1][1]
    assert query["interval"] == ["5m"] and query["limit"] == ["3"]


async def test_cluster_summary_retries_once_after_not_active(
    provider: TerminalProvider, fake_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(market, "_SEED_WAIT", 0.0)
    server = build_server(provider)
    result = await server.call_tool("cluster_summary", {"instrument": "cold:futures:XUSDT"})
    assert _structured(result)["buckets_available"] >= 1
    cluster_calls = [p for p, _q, _h in fake_api.requests if p == "/v1/market/clusters"]
    assert len(cluster_calls) == 2


async def test_find_instrument_ranks_exact_first(
    provider: TerminalProvider, fake_api: FakeApi
) -> None:
    server = build_server(provider)
    result = _structured(
        await server.call_tool(
            "find_instrument", {"query": "btc", "exchange": "binance", "market": "futures"}
        )
    )
    assert result["matches"], result
    assert result["matches"][0]["instrument"] == "binance:futures:BTCUSDT"
    assert result["matches"][0]["exchange"] == "binance"
    assert "tick_size" in result["matches"][0]
    instrument_calls = [q for p, q, _h in fake_api.requests if p == "/v1/instruments"]
    assert instrument_calls and instrument_calls[0]["q"] == ["btc"]

    pinned = _structured(
        await server.call_tool("find_instrument", {"query": "BTC", "connection_id": 12})
    )
    assert pinned["matches"][0]["connection_id"] == 12


async def test_api_error_becomes_tool_error(provider: TerminalProvider) -> None:
    # In-process `call_tool` raises; over the wire the same error is an
    # `is_error` result whose text is the message below.
    server = build_server(provider)
    with pytest.raises(ToolError) as raised:
        await server.call_tool("market_snapshot", {"instrument": "moex:futures:SiZ5"})
    assert "unsupported:" in _error_text(raised.value)


async def test_unreachable_terminal_is_reported_and_retried() -> None:
    attempts = 0

    def factory():
        nonlocal attempts
        attempts += 1
        raise TerminalUnreachable("connection refused")

    server = build_server(TerminalProvider(factory=factory))
    with pytest.raises(ToolError) as first:
        await server.call_tool("terminal_status", {})
    with pytest.raises(ToolError):
        await server.call_tool("terminal_status", {})
    assert "terminal_unreachable" in _error_text(first.value)
    assert attempts == 2, "a failed discovery is retried on the next call"


async def test_tool_errors_never_carry_the_token(provider: TerminalProvider) -> None:
    server = build_server(provider)
    with pytest.raises(ToolError) as raised:
        await server.call_tool("market_snapshot", {"instrument": "moex:futures:SiZ5"})
    assert TOKEN not in _error_text(raised.value)


def test_read_only_annotations_are_shared() -> None:
    assert tools.READ_ONLY.read_only_hint is True
    assert tools.READ_ONLY.destructive_hint is False


async def test_account_tools_read_one_connection(
    provider: TerminalProvider, fake_api: FakeApi
) -> None:
    server = build_server(provider)
    overview = _structured(await server.call_tool("account_overview", {"connection_id": 12}))
    assert overview["balances"][0]["currency"] == "USDT"
    assert overview["positions"][0]["side"] == "long"
    assert overview["open_orders"] == [
        {"instrument": "binance:futures:BTCUSDT", "orders": 1, "triggers": 1}
    ]
    paths = [p for p, _q, _h in fake_api.requests]
    assert paths == ["/v1/account/balances", "/v1/account/positions", "/v1/account/orders"]
    assert all(q["connection_id"] == ["12"] for _p, q, _h in fake_api.requests)

    orders = _structured(
        await server.call_tool(
            "open_orders", {"connection_id": 12, "instrument": "binance:futures:BTCUSDT"}
        )
    )
    assert orders["orders"][0]["key"] == "t-123456789012345678"
    assert orders["orders"][0]["type"] == "limit"
    assert orders["triggers"][0]["type"] == "stop_loss"
    none = _structured(
        await server.call_tool("open_orders", {"connection_id": 12, "instrument": "x:y:Z"})
    )
    assert none["orders"] == [] and none["triggers"] == []

    fills = _structured(
        await server.call_tool("recent_fills", {"connection_id": 12, "limit": 5, "since_ts": 7})
    )
    assert fills["count"] == 1 and fills["buy_volume"] == "0.012"
    query = fake_api.requests[-1][1]
    assert (query["limit"], query["since_ts"]) == (["5"], ["7"])

    with pytest.raises(ToolError) as raised:
        await server.call_tool("account_overview", {"connection_id": 99})
    assert "not_found" in _error_text(raised.value)


async def test_trading_tools_send_the_commands_and_answer_accepted(
    provider: TerminalProvider, fake_api: FakeApi
) -> None:
    server = build_server(provider)
    placed = _structured(
        await server.call_tool(
            "place_order",
            {
                "connection_id": 12,
                "instrument": "binance:futures:BTCUSDT",
                "side": "buy",
                "order_type": "limit",
                "price": "67000.1",
                "size": "0.012",
                "client_key": "intent-1",
                "post_only": True,
            },
        )
    )
    assert placed["accepted"] is True
    assert placed["key"] == "t-173029440012300001"
    assert "not by the exchange" in placed["note"]
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("POST", "/v1/orders")
    assert body["side"] == "buy" and body["type"] == "limit"
    assert body["price"] == "67000.1" and body["size"] == "0.012"
    assert body["client_key"] == "intent-1" and body["post_only"] is True

    cancelled = _structured(
        await server.call_tool(
            "cancel_order",
            {"connection_id": 12, "instrument": "binance:futures:BTCUSDT", "order_id": "t-1"},
        )
    )
    assert cancelled["key"] is None
    method, path, _body = fake_api.bodies[-1]
    assert method == "DELETE" and path.startswith("/v1/orders/t-1?")

    _structured(
        await server.call_tool(
            "cancel_all_orders", {"connection_id": 12, "instrument": "binance:futures:BTCUSDT"}
        )
    )
    assert fake_api.bodies[-1][1] == "/v1/orders/cancel-all"
    _structured(
        await server.call_tool(
            "close_position", {"connection_id": 12, "instrument": "binance:futures:BTCUSDT"}
        )
    )
    assert fake_api.bodies[-1][1] == "/v1/positions/close"

    with pytest.raises(ToolError) as raised:
        await server.call_tool(
            "close_position", {"connection_id": 13, "instrument": "binance:futures:BTCUSDT"}
        )
    assert "not_tradable" in _error_text(raised.value)


async def test_trigger_tools_send_the_commands(
    provider: TerminalProvider, fake_api: FakeApi
) -> None:
    server = build_server(provider)
    placed = _structured(
        await server.call_tool(
            "place_trigger",
            {
                "connection_id": 12,
                "instrument": "binance:futures:BTCUSDT",
                "kind": "stop",
                "side": "sell",
                "notional": "800",
                "trigger_price": "66000",
                "client_key": "stop-1",
            },
        )
    )
    assert placed["key"] == "sl_1730294400123"
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("POST", "/v1/orders/trigger")
    assert body["kind"] == "stop" and body["side"] == "sell" and body["notional"] == "800"
    assert body["trigger_price"] == "66000" and "rule" not in body

    moved = _structured(
        await server.call_tool(
            "amend_trigger",
            {
                "connection_id": 12,
                "instrument": "binance:futures:BTCUSDT",
                "trigger_id": "42",
                "kind": "stop_loss",
                "trigger_price": "65500",
            },
        )
    )
    assert moved["key"] is None
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("PATCH", "/v1/orders/trigger/42")
    assert body == {
        "connection_id": 12,
        "instrument": "binance:futures:BTCUSDT",
        "kind": "stop_loss",
        "trigger_price": "65500",
    }

    _structured(
        await server.call_tool(
            "cancel_trigger",
            {"connection_id": 12, "instrument": "binance:futures:BTCUSDT", "trigger_id": "42"},
        )
    )
    method, path, _body = fake_api.bodies[-1]
    assert method == "DELETE" and path.startswith("/v1/orders/trigger/42?")

    _structured(
        await server.call_tool(
            "cancel_all_triggers", {"connection_id": 12, "instrument": "binance:futures:BTCUSDT"}
        )
    )
    assert fake_api.bodies[-1][1] == "/v1/orders/trigger/cancel-all"

    with pytest.raises(ToolError) as raised:
        await server.call_tool(
            "place_trigger",
            {
                "connection_id": 12,
                "instrument": "binance:futures:BTCUSDT",
                "kind": "stop",
                "trigger_price": "1",
                "client_key": "stop-2",
            },
        )
    assert "side and notional" in _error_text(raised.value)


async def test_leverage_tools(provider: TerminalProvider, fake_api: FakeApi) -> None:
    server = build_server(provider)
    read = _structured(
        await server.call_tool(
            "leverage", {"connection_id": 12, "instrument": "binance:futures:BTCUSDT"}
        )
    )
    assert read == {
        "connection_id": 12,
        "instrument": "binance:futures:BTCUSDT",
        "leverage": 10,
        "max_leverage": 125,
        "mode": "manual",
        "margin_mode": "cross",
    }
    path, query, _headers = fake_api.requests[-1]
    assert path == "/v1/account/leverage" and query["instrument"] == ["binance:futures:BTCUSDT"]

    _structured(
        await server.call_tool(
            "set_leverage",
            {"connection_id": 12, "instrument": "binance:futures:BTCUSDT", "leverage": 20},
        )
    )
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("POST", "/v1/account/leverage") and body["leverage"] == 20
    assert "mode" not in body

    _structured(
        await server.call_tool(
            "set_margin_mode",
            {
                "connection_id": 12,
                "instrument": "binance:futures:BTCUSDT",
                "margin_mode": "isolated",
            },
        )
    )
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("POST", "/v1/account/margin-mode")
    assert body["margin_mode"] == "isolated"

    with pytest.raises(ToolError) as raised:
        await server.call_tool(
            "set_leverage",
            {
                "connection_id": 12,
                "instrument": "binance:futures:BTCUSDT",
                "leverage": 5,
                "mode": "max",
            },
        )
    assert "exactly one" in _error_text(raised.value)


async def test_workspace_tools(provider: TerminalProvider, fake_api: FakeApi) -> None:
    server = build_server(provider)
    layout = _structured(await server.call_tool("workspace", {}))
    assert fake_api.requests[-1][0] == "/v1/workspace"
    window = layout["windows"][0]
    assert window["id"] == 1 and window["main"] is True
    assert window["tabs"][0]["stacks"][0]["widget_id"] == 12
    assert window["tabs"][0]["charts"][0]["interval"] == "5m"
    assert "do not keep them" in layout["note"]

    opened = _structured(
        await server.call_tool(
            "open_stack",
            {"instrument": "binance:futures:BTCUSDT", "chart": True, "activate": False},
        )
    )
    assert opened == {"window_id": 1, "tab_id": 2, "stacks": [14], "charts": []}
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("POST", "/v1/workspace/stacks")
    assert body == {
        "instrument": "binance:futures:BTCUSDT",
        "chart": True,
        "target": "new_tab",
        "activate": False,
    }

    opened = _structured(
        await server.call_tool(
            "open_tab",
            {
                "items": [
                    {"instrument": "binance:futures:BTCUSDT", "chart": True},
                    {"instrument": "binance:futures:ETHUSDT", "connection_id": 12},
                ],
                "name": "Majors",
                "activate": False,
            },
        )
    )
    assert opened["window_id"] == 1
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("POST", "/v1/workspace/tabs")
    assert body == {
        "items": [
            {"instrument": "binance:futures:BTCUSDT", "chart": True},
            {"instrument": "binance:futures:ETHUSDT", "chart": False, "connection_id": 12},
        ],
        "target": "new_tab",
        "activate": False,
        "name": "Majors",
    }
    _structured(
        await server.call_tool(
            "add_stacks",
            {"window_id": 1, "tab_id": 2, "items": [{"instrument": "binance:futures:SOLUSDT"}]},
        )
    )
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("POST", "/v1/workspace/windows/1/tabs/2/stacks")
    assert body == {"items": [{"instrument": "binance:futures:SOLUSDT", "chart": False}]}
    with pytest.raises(ToolError):
        await server.call_tool("open_tab", {"items": []})

    _structured(await server.call_tool("open_multiview", {"base": "BTC", "target": "new_window"}))
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("POST", "/v1/workspace/multiview")
    assert body == {"base": "BTC", "activate": True, "target": "new_window"}

    _structured(
        await server.call_tool(
            "set_stack_instrument", {"widget_id": 12, "instrument": "binance:futures:ETHUSDT"}
        )
    )
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("PATCH", "/v1/workspace/stacks/12")
    assert body == {"instrument": "binance:futures:ETHUSDT"}

    _structured(await server.call_tool("close_stack", {"widget_id": 12}))
    assert fake_api.bodies[-1][:2] == ("DELETE", "/v1/workspace/stacks/12")
    _structured(await server.call_tool("activate_tab", {"window_id": 1, "tab_id": 2}))
    assert fake_api.bodies[-1][:2] == ("POST", "/v1/workspace/windows/1/tabs/2/activate")
    _structured(await server.call_tool("close_tab", {"window_id": 1, "tab_id": 2}))
    assert fake_api.bodies[-1][:2] == ("DELETE", "/v1/workspace/windows/1/tabs/2")
    _structured(await server.call_tool("activate_window", {"window_id": 2}))
    assert fake_api.bodies[-1][:2] == ("POST", "/v1/workspace/windows/2/activate")
    _structured(await server.call_tool("close_window", {"window_id": 2}))
    assert fake_api.bodies[-1][:2] == ("DELETE", "/v1/workspace/windows/2")

    with pytest.raises(ToolError) as raised:
        await server.call_tool("close_window", {"window_id": 1})
    assert "invalid_request" in str(raised.value)
    with pytest.raises(ToolError) as raised:
        await server.call_tool("close_stack", {"widget_id": 99})
    assert "not_found" in str(raised.value)


async def test_settings_tools(provider: TerminalProvider, fake_api: FakeApi) -> None:
    server = build_server(provider)
    rows = _structured(await server.call_tool("settings", {"category": "multiview"}))
    path, query, _headers = fake_api.requests[-1]
    assert path == "/v1/settings" and query["category"] == ["multiview"]
    assert rows["data"][0]["key"] == "stack_width_px" and rows["data"][0]["writable"] is True

    book = _structured(
        await server.call_tool(
            "orderbook_settings", {"connection_id": 12, "instrument": "binance:futures:BTCUSDT"}
        )
    )
    assert book["data"]["general"]["auto_scroll"]["resolved_from"] == "global"
    assert "resolved_from names" in book["note"]

    applied = _structured(
        await server.call_tool(
            "update_settings",
            {
                "changes": [
                    {"category": "multiview", "key": "stack_width_px", "value": 300},
                    {
                        "instrument": "binance:futures:BTCUSDT",
                        "connection_id": 12,
                        "category": "general",
                        "key": "auto_scroll",
                        "value": True,
                    },
                ]
            },
        )
    )
    assert applied == {"applied": 2}
    method, path, body = fake_api.bodies[-1]
    assert (method, path) == ("PATCH", "/v1/settings")
    assert body["changes"][1] == {
        "category": "general",
        "key": "auto_scroll",
        "value": True,
        "instrument": "binance:futures:BTCUSDT",
        "connection_id": 12,
    }

    with pytest.raises(ToolError) as raised:
        await server.call_tool(
            "update_settings", {"changes": [{"category": "nope", "key": "nope", "value": 1}]}
        )
    assert "changes[0]" in str(raised.value)
