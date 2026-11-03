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
}


async def test_tools_are_registered_read_only(provider: TerminalProvider) -> None:
    server = build_server(provider)
    listed = await server.list_tools()
    assert {tool.name for tool in listed} == EXPECTED_TOOLS
    for tool in listed:
        assert tool.description, tool.name
        assert tool.input_schema["type"] == "object"
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
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
