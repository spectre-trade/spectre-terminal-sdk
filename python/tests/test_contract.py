"""Every fixture of the contract parses into its model, with the promised types."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
from conftest import FIXTURES, load_fixture

from spectre_terminal import models
from spectre_terminal.models import (
    BookTop,
    Candles,
    Clusters,
    Connection,
    Event,
    Gap,
    Health,
    Intervals,
    Level,
    MarkPrice,
    Meta,
    OrderBook,
    Page,
    Snapshot,
    Subscribed,
    SubscriptionError,
    Ticker,
    Trade,
    Trades,
    Unsubscribed,
)

# fixture name -> parser. ``error`` is the envelope, not a model: the client turns it into ApiError.
PARSERS: dict[str, Any] = {
    "meta": Meta.from_dict,
    "health": Health.from_dict,
    "connections": lambda d: [Connection.from_dict(item) for item in d["data"]],
    "connection": Connection.from_dict,
    "instruments": Page.of_instruments,
    "intervals": Intervals.from_dict,
    "candles": Candles.from_dict,
    "trades": Trades.from_dict,
    "snapshot": Snapshot.from_dict,
    "orderbook": OrderBook.from_dict,
    "clusters": Clusters.from_dict,
}

FIXTURE_NAMES = sorted(path.stem for path in FIXTURES.glob("*.json"))


def test_every_fixture_has_a_parser() -> None:
    unknown = set(FIXTURE_NAMES) - set(PARSERS) - {"error"}
    assert not unknown, f"fixtures without a model: {sorted(unknown)}"


@pytest.mark.parametrize("name", [name for name in FIXTURE_NAMES if name != "error"])
def test_fixture_parses(name: str) -> None:
    parsed = PARSERS[name](load_fixture(name))
    assert parsed is not None


def test_error_fixture_is_the_envelope() -> None:
    body = load_fixture("error")
    assert set(body["error"]) >= {"code", "message"}


def _with_unknown_keys(value: Any) -> Any:
    """A deep copy with an extra key in every object, as a newer terminal would add."""
    if isinstance(value, dict):
        copied = {key: _with_unknown_keys(item) for key, item in value.items()}
        copied["added_in_v1_x"] = {"nested": True}
        return copied
    if isinstance(value, list):
        return [_with_unknown_keys(item) for item in value]
    return value


@pytest.mark.parametrize("name", [name for name in FIXTURE_NAMES if name != "error"])
def test_unknown_keys_are_ignored(name: str) -> None:
    original = load_fixture(name)
    extended = _with_unknown_keys(copy.deepcopy(original))
    assert PARSERS[name](extended) == PARSERS[name](original)


def test_meta_types() -> None:
    meta = Meta.from_dict(load_fixture("meta"))
    assert meta.api_version == "1"
    assert isinstance(meta.limits.ws_connections_per_token, int)
    assert meta.limits.exchange_subscriptions_per_second == 5
    assert meta.scopes == ["market:read", "connections:read"]
    assert meta.topics == []


def test_health_types() -> None:
    health = Health.from_dict(load_fixture("health"))
    assert health.status == "ok"
    assert isinstance(health.uptime_ms, int)
    assert health.stream_available is True


def test_connection_types() -> None:
    connection = Connection.from_dict(load_fixture("connection"))
    assert connection.id == 12
    assert connection.status.state == "connected"
    assert connection.status.last_event is not None
    assert connection.status.last_event.code == "connected"
    assert isinstance(connection.status.last_event.ts, int)


def test_connection_without_last_event() -> None:
    body = load_fixture("connection")
    del body["status"]["last_event"]
    assert Connection.from_dict(body).status.last_event is None
    body["status"]["last_event"] = None
    assert Connection.from_dict(body).status.last_event is None


def test_instruments_types() -> None:
    page = Page.of_instruments(load_fixture("instruments"))
    assert page.exchange == "binance" and page.market == "futures"
    assert page.next_cursor is None
    instrument = page.data[0]
    assert instrument.tick_size == Decimal("0.1")
    assert isinstance(instrument.lot_size, Decimal)
    assert instrument.contract_value == Decimal("1")


def test_instrument_null_steps() -> None:
    body = load_fixture("instruments")
    body["data"][0]["tick_size"] = None
    assert Page.of_instruments(body).data[0].tick_size is None


def test_candles_types() -> None:
    candles = Candles.from_dict(load_fixture("candles"))
    assert candles.connection_id == 12 and candles.interval == "1m"
    bar = candles.data[0]
    assert bar.ts == 1730294400000 and isinstance(bar.ts, int)
    assert bar.open == Decimal("67000.1")
    assert bar.quote_volume == Decimal("3490000.5")
    assert bar.closed is True


def test_intervals_types() -> None:
    intervals = Intervals.from_dict(load_fixture("intervals"))
    assert intervals.candles[0].id == "1m"
    assert intervals.clusters[0].duration_ms == 60000


def test_trades_types() -> None:
    trades = Trades.from_dict(load_fixture("trades"))
    trade = trades.data[0]
    assert trade.id is None
    assert trade.price == Decimal("67000.1") and not isinstance(trade.price, float)
    assert trade.qty == Decimal("0.012")
    assert trade.side == "buy"
    assert trade.ts == 1730294400125 and trade.exchange_ts == 1730294400119


def test_snapshot_types() -> None:
    snapshot = Snapshot.from_dict(load_fixture("snapshot"))
    assert snapshot.best_bid == Level(Decimal("67000.1"), Decimal("1.25"))
    assert snapshot.best_ask is not None and snapshot.best_ask.size == Decimal("0.40")
    assert str(snapshot.best_ask.size) == "0.40", "no normalisation of money strings"
    assert snapshot.mark_price == Decimal("67001.0")
    assert isinstance(snapshot.last_trade, Trade)
    assert isinstance(snapshot.ticker, Ticker)
    assert snapshot.ticker.change_24h_pct == Decimal("1.25")
    assert snapshot.ticker.high_24h is None
    assert snapshot.ticker.best_bid is None


def test_snapshot_all_null() -> None:
    body = load_fixture("snapshot")
    for key in ("best_bid", "best_ask", "last_trade", "mark_price", "ticker"):
        body[key] = None
    snapshot = Snapshot.from_dict(body)
    assert snapshot.best_bid is None and snapshot.ticker is None and snapshot.mark_price is None


def test_orderbook_types() -> None:
    book = OrderBook.from_dict(load_fixture("orderbook"))
    assert book.depth == 20
    assert book.bids == [Level(Decimal("67000.1"), Decimal("1.25"))]
    assert book.asks[0].price == Decimal("67000.2")
    assert isinstance(book, BookTop)


def test_clusters_types() -> None:
    clusters = Clusters.from_dict(load_fixture("clusters"))
    assert clusters.interval == "5m"
    bucket = clusters.data[0]
    assert bucket.trades == 120 and isinstance(bucket.trades, int)
    assert bucket.vwap == Decimal("67000.1")
    assert bucket.completed is False
    assert bucket.last_trade_ts == 1730294399870
    level = bucket.levels[0]
    assert level.buy_volume == Decimal("0.75") and level.sell_trades == 2


def test_cluster_without_trades() -> None:
    body = load_fixture("clusters")
    bucket = body["data"][0]
    bucket.update(vwap=None, min_price=None, max_price=None, last_trade_ts=0, levels=[])
    parsed = Clusters.from_dict(body).data[0]
    assert parsed.vwap is None and parsed.levels == []


# --- stream frames, from the contract's examples -------------------------------


def test_subscribed_frame() -> None:
    frame = Subscribed.from_dict(
        {"type": "subscribed", "request_id": "r1", "sub": "7:trades", "connection_id": 12}
    )
    assert frame.sub == "7:trades" and frame.connection_id == 12 and frame.request_id == "r1"
    assert frame.topic == "trades"
    assert Unsubscribed.from_dict({"type": "unsubscribed", "sub": "7:trades"}).request_id is None


def test_event_frame_trades() -> None:
    event = Event.from_dict(
        {
            "type": "event",
            "sub": "7:trades",
            "seq": 41,
            "ts": 1,
            "data": load_fixture("trades")["data"],
        }
    )
    assert event.topic == "trades" and event.seq == 41
    assert isinstance(event.data, list) and isinstance(event.data[0], Trade)


def test_event_frame_book_top() -> None:
    body = load_fixture("orderbook")
    data = {key: body[key] for key in ("ts", "depth", "bids", "asks")}
    event = Event.from_dict({"type": "event", "sub": "7:book.top", "seq": 9, "ts": 1, "data": data})
    assert event.topic == "book.top"
    assert isinstance(event.data, BookTop)
    assert event.data.bids[0].price == Decimal("67000.1")


def test_event_frame_ticker_mark_and_clusters() -> None:
    ticker = Event.from_dict(
        {
            "type": "event",
            "sub": "7:ticker",
            "seq": 1,
            "ts": 1,
            "data": load_fixture("snapshot")["ticker"],
        }
    )
    assert isinstance(ticker.data, Ticker)
    mark = Event.from_dict(
        {
            "type": "event",
            "sub": "7:mark_price",
            "seq": 1,
            "ts": 1,
            "data": {"mark_price": "1.5", "ts": 2},
        }
    )
    assert isinstance(mark.data, MarkPrice) and mark.data.mark_price == Decimal("1.5")
    cluster = Event.from_dict(
        {
            "type": "event",
            "sub": "7:clusters",
            "seq": 1,
            "ts": 1,
            "data": load_fixture("clusters")["data"][0],
        }
    )
    assert isinstance(cluster.data, models.Cluster)


def test_event_frame_unknown_topic_is_passed_through() -> None:
    event = Event.from_dict(
        {"type": "event", "sub": "7:funding", "seq": 1, "ts": 1, "data": {"x": "1"}}
    )
    assert event.topic == "funding" and event.data == {"x": "1"}


def test_gap_and_subscription_error_frames() -> None:
    gap = Gap.from_dict(
        {"type": "gap", "sub": "7:trades", "from_seq": 42, "to_seq": 57, "reason": "slow_consumer"}
    )
    assert (gap.from_seq, gap.to_seq, gap.reason) == (42, 57, "slow_consumer")
    error = SubscriptionError.from_dict(
        {"type": "error", "sub": "7:trades", "code": "unavailable", "message": "venue refused"}
    )
    assert error.code == "unavailable" and error.topic == "trades"
