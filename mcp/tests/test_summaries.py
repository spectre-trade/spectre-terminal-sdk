"""The pure summaries against the contract fixtures and hand-made inputs."""

from __future__ import annotations

from decimal import Decimal

from spectre_terminal.models import (
    Candles,
    Clusters,
    Connection,
    Health,
    Meta,
    OrderBook,
    Snapshot,
    Trade,
    Trades,
)

from spectre_terminal_mcp.summaries import (
    book_summary,
    candle_rows,
    cluster_summary,
    iso,
    snapshot_summary,
    status_summary,
    trades_summary,
)

from .conftest import load_fixture


def test_iso_is_utc_with_milliseconds() -> None:
    assert iso(1730294400123) == "2024-10-30T13:20:00.123Z"
    assert iso(None) is None


def test_status_summary_lists_connections() -> None:
    meta = Meta.from_dict(load_fixture("meta.json"))
    health = Health.from_dict(load_fixture("health.json"))
    connections = [Connection.from_dict(c) for c in load_fixture("connections.json")["data"]]
    summary = status_summary(meta, health, connections)
    assert summary["api_version"] == "1"
    assert summary["connections"][0]["id"] == 12
    assert summary["connections"][0]["state"] == "connected"
    assert set(summary["limits"]) == {"api_only_instruments", "exchange_subscriptions_per_second"}


def test_snapshot_summary_has_spread_and_strings_only() -> None:
    snapshot = Snapshot.from_dict(load_fixture("snapshot.json"))
    summary = snapshot_summary(snapshot)
    assert summary["best_bid"] == ["67000.1", "1.25"]
    assert summary["spread"] == "0.1"
    assert summary["last_price"] == "67000.1"
    assert summary["time"].endswith("Z")
    assert all(not isinstance(v, Decimal) for v in summary.values())


def test_snapshot_summary_without_data_is_all_null() -> None:
    snapshot = Snapshot.from_dict(
        {
            "instrument": "binance:futures:BTCUSDT",
            "connection_id": 12,
            "ts": 1,
            "best_bid": None,
            "best_ask": None,
            "last_trade": None,
            "mark_price": None,
            "ticker": None,
        }
    )
    summary = snapshot_summary(snapshot)
    assert summary["last_price"] is None
    assert summary["spread"] is None
    assert summary["change_24h_pct"] is None


def test_book_summary_volumes_and_imbalance() -> None:
    book = OrderBook.from_dict(
        {
            "instrument": "binance:futures:BTCUSDT",
            "connection_id": 12,
            "ts": 1730294400123,
            "depth": 3,
            "bids": [["100.0", "3"], ["99.9", "1"], ["99.8", "5"]],
            "asks": [["100.1", "1"], ["100.2", "1"], ["100.3", "10"]],
        }
    )
    summary = book_summary(book, 2)
    assert summary["bids"] == [["100.0", "3"], ["99.9", "1"]]
    assert summary["asks"] == [["100.1", "1"], ["100.2", "1"]]
    assert summary["bid_volume"] == "4"
    assert summary["ask_volume"] == "2"
    assert summary["imbalance"] == "0.3333"
    assert summary["spread"] == "0.1"
    assert summary["mid"] == "100.05"
    assert summary["spread_bps"] == "10.00"


def test_trades_summary_by_hand() -> None:
    def trade(price: str, qty: str, side: str, ts: int) -> Trade:
        return Trade.from_dict(
            {
                "id": None,
                "price": price,
                "qty": qty,
                "side": side,
                "ts": ts,
                "exchange_ts": ts,
            }
        )

    trades = Trades(
        instrument="binance:futures:BTCUSDT",
        connection_id=12,
        data=[
            trade("100.0", "1", "buy", 1000),
            trade("101.0", "3", "sell", 2000),
            trade("102.0", "1", "buy", 3500),
        ],
    )
    summary = trades_summary(trades)
    assert summary["count"] == 3
    assert (summary["buy_count"], summary["sell_count"]) == (2, 1)
    assert summary["buy_volume"] == "2"
    assert summary["sell_volume"] == "3"
    assert summary["delta"] == "-1"
    # (100 + 303 + 102) / 5 = 101.0, at the price precision
    assert summary["vwap"] == "101.0"
    assert (summary["low"], summary["high"]) == ("100.0", "102.0")
    assert summary["span_ms"] == 2500
    assert summary["largest"] == {"price": "101.0", "qty": "3", "side": "sell", "ts": 2000}


def test_trades_summary_of_fixture_and_empty() -> None:
    trades = Trades.from_dict(load_fixture("trades.json"))
    summary = trades_summary(trades)
    assert summary["count"] == len(trades.data) > 0
    assert Decimal(summary["volume"]) == sum(t.qty for t in trades.data)
    empty = trades_summary(Trades(instrument="x:y:Z", connection_id=1, data=[]))
    assert empty == {"instrument": "x:y:Z", "connection_id": 1, "count": 0}


def test_cluster_summary_trims_buckets_and_ranks_levels() -> None:
    clusters = Clusters.from_dict(load_fixture("clusters.json"))
    summary = cluster_summary(clusters, buckets=1, top_levels=2)
    assert summary["interval"] == clusters.interval
    assert summary["buckets_available"] == len(clusters.data)
    assert len(summary["buckets"]) == 1
    bucket = summary["buckets"][0]
    assert bucket["levels_total"] == len(clusters.data[-1].levels)
    volumes = [Decimal(level["volume"]) for level in bucket["top_levels"]]
    assert volumes == sorted(volumes, reverse=True)
    assert len(volumes) <= 2
    assert Decimal(bucket["delta"]) == clusters.data[-1].buy_volume - clusters.data[-1].sell_volume


def test_candle_rows_are_compact() -> None:
    candles = Candles.from_dict(load_fixture("candles.json"))
    rows = candle_rows(candles)
    assert rows["columns"][0] == "ts"
    assert len(rows["rows"]) == len(candles.data)
    first = rows["rows"][0]
    assert first[0] == candles.data[0].ts
    assert first[2] == str(candles.data[0].open)
    assert isinstance(first[-1], bool)


def test_account_summaries_from_fixtures() -> None:
    from spectre_terminal.models import (
        AccountBalances,
        AccountFills,
        AccountOrders,
        AccountPositions,
    )

    from spectre_terminal_mcp.summaries import account_overview, fills_summary, open_orders_summary

    orders = AccountOrders.from_dict(load_fixture("account_orders.json"))
    positions = AccountPositions.from_dict(load_fixture("account_positions.json"))
    balances = AccountBalances.from_dict(load_fixture("account_balances.json"))
    fills = AccountFills.from_dict(load_fixture("account_fills.json"))

    overview = account_overview(balances, positions, orders)
    assert overview["open_orders_total"] == 1 and overview["triggers_total"] == 1
    assert overview["positions"][0]["unrealized_pnl"] == "250"
    assert all(not isinstance(v, Decimal) for b in overview["balances"] for v in b.values())

    listed = open_orders_summary(orders)
    assert listed["orders"][0]["remaining"] == "0.012"
    assert listed["orders"][0]["created_time"].endswith("Z")
    assert listed["triggers"][0]["rule"] == "price_below_or_equal"

    summary = fills_summary(fills)
    assert summary["count"] == 1
    assert summary["fills"][0]["fee"] == "0.32"
    assert summary["sell_volume"] == "0"
