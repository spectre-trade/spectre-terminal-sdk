"""Pure summaries over the client's models: what a model needs, nothing more.

Every function here takes typed models from :mod:`spectre_terminal.models`
and returns a JSON-ready ``dict``: decimals as strings, timestamps as UTC
milliseconds with an ISO twin, nothing a model has to post-process. No I/O,
so each one is unit-tested against the contract fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from spectre_terminal.models import (
    AccountBalances,
    AccountFills,
    AccountOrders,
    AccountPositions,
    Candles,
    Cluster,
    Clusters,
    Connection,
    Health,
    Instrument,
    Level,
    Meta,
    OrderBook,
    Snapshot,
    Trades,
)

__all__ = [
    "account_overview",
    "book_summary",
    "fills_summary",
    "open_orders_summary",
    "candle_rows",
    "cluster_summary",
    "connection_row",
    "dec",
    "instrument_row",
    "iso",
    "snapshot_summary",
    "status_summary",
    "trades_summary",
]

_BPS = Decimal(10_000)


def dec(value: Decimal | None) -> str | None:
    """A decimal as the exact string the wire carried; ``None`` stays ``None``."""
    return None if value is None else str(value)


def iso(ts_ms: int | None) -> str | None:
    """UTC milliseconds as an ISO-8601 string with millisecond precision."""
    if ts_ms is None:
        return None
    moment = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _level(level: Level | None) -> list[str] | None:
    return None if level is None else [str(level.price), str(level.size)]


def _quantum(values: list[Decimal]) -> Decimal:
    """The finest exponent among ``values``: a VWAP is rounded to the price precision."""
    exponent = min((v.as_tuple().exponent for v in values), default=0)
    return Decimal(1).scaleb(exponent if isinstance(exponent, int) else 0)


def _ratio(numerator: Decimal, denominator: Decimal, places: str = "0.0001") -> Decimal | None:
    if denominator == 0:
        return None
    return (numerator / denominator).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _spread_bps(spread: Decimal | None, mid: Decimal | None) -> str | None:
    if spread is None or not mid:
        return None
    return dec(_ratio(spread * _BPS, mid, "0.01"))


def connection_row(connection: Connection) -> dict[str, Any]:
    """One connection as the agent sees it: who, where, and whether it is alive."""
    return {
        "id": connection.id,
        "exchange": connection.exchange,
        "market": connection.market,
        "label": connection.label,
        "enabled": connection.enabled,
        "read_only": connection.read_only,
        "state": connection.status.state,
    }


def status_summary(meta: Meta, health: Health, connections: list[Connection]) -> dict[str, Any]:
    """Terminal version, API health and the connection list in one answer."""
    return {
        "app_version": meta.app_version,
        "api_version": meta.api_version,
        "build_env": meta.build_env,
        "status": health.status,
        "uptime_s": health.uptime_ms // 1000,
        "stream_available": health.stream_available,
        "topics": list(meta.topics),
        "limits": {
            "api_only_instruments": meta.limits.api_only_instruments,
            "exchange_subscriptions_per_second": meta.limits.exchange_subscriptions_per_second,
        },
        "connections": [connection_row(c) for c in connections],
    }


def instrument_row(instrument: Instrument) -> dict[str, Any]:
    """The fields that matter when picking an instrument address."""
    return {
        "instrument": instrument.instrument,
        "symbol": instrument.symbol,
        "base": instrument.base,
        "quote": instrument.quote,
        "status": instrument.status,
        "tick_size": dec(instrument.tick_size),
        "lot_size": dec(instrument.lot_size),
    }


def snapshot_summary(snapshot: Snapshot) -> dict[str, Any]:
    """Last price, top of book with spread, mark and the 24h figures."""
    last = snapshot.last_trade
    ticker = snapshot.ticker
    bid = snapshot.best_bid
    ask = snapshot.best_ask
    spread = ask.price - bid.price if bid and ask else None
    mid = (ask.price + bid.price) / 2 if bid and ask else None
    last_price = last.price if last else (ticker.price if ticker else None)
    return {
        "instrument": snapshot.instrument,
        "connection_id": snapshot.connection_id,
        "ts": snapshot.ts,
        "time": iso(snapshot.ts),
        "last_price": dec(last_price),
        "last_side": last.side if last else None,
        "last_qty": dec(last.qty) if last else None,
        "best_bid": _level(bid),
        "best_ask": _level(ask),
        "spread": dec(spread),
        "spread_bps": _spread_bps(spread, mid),
        "mark_price": dec(snapshot.mark_price),
        "change_24h_pct": dec(ticker.change_24h_pct) if ticker else None,
        "volume_24h": dec(ticker.volume_24h) if ticker else None,
        "high_24h": dec(ticker.high_24h) if ticker else None,
        "low_24h": dec(ticker.low_24h) if ticker else None,
    }


def book_summary(book: OrderBook, depth: int) -> dict[str, Any]:
    """The top ``depth`` levels per side, their volumes and the imbalance between them."""
    bids = book.bids[:depth]
    asks = book.asks[:depth]
    bid_volume = sum((level.size for level in bids), Decimal(0))
    ask_volume = sum((level.size for level in asks), Decimal(0))
    best_bid = bids[0] if bids else None
    best_ask = asks[0] if asks else None
    spread = best_ask.price - best_bid.price if best_bid and best_ask else None
    mid = (best_ask.price + best_bid.price) / 2 if best_bid and best_ask else None
    return {
        "instrument": book.instrument,
        "connection_id": book.connection_id,
        "ts": book.ts,
        "time": iso(book.ts),
        "depth": len(bids) if len(bids) >= len(asks) else len(asks),
        "best_bid": _level(best_bid),
        "best_ask": _level(best_ask),
        "spread": dec(spread),
        "spread_bps": _spread_bps(spread, mid),
        "mid": dec(mid),
        "bid_volume": dec(bid_volume),
        "ask_volume": dec(ask_volume),
        # (bids - asks) / (bids + asks): +1 is all bids, -1 is all asks.
        "imbalance": dec(_ratio(bid_volume - ask_volume, bid_volume + ask_volume)),
        "bids": [_level(level) for level in bids],
        "asks": [_level(level) for level in asks],
    }


def trades_summary(trades: Trades) -> dict[str, Any]:
    """Volume by side, delta, VWAP, range and the largest print of a batch of trades."""
    rows = trades.data
    if not rows:
        return {
            "instrument": trades.instrument,
            "connection_id": trades.connection_id,
            "count": 0,
        }
    buys = [t for t in rows if t.side == "buy"]
    sells = [t for t in rows if t.side == "sell"]
    buy_volume = sum((t.qty for t in buys), Decimal(0))
    sell_volume = sum((t.qty for t in sells), Decimal(0))
    volume = buy_volume + sell_volume
    notional = sum((t.price * t.qty for t in rows), Decimal(0))
    prices = [t.price for t in rows]
    vwap = (notional / volume).quantize(_quantum(prices)) if volume else None
    largest = max(rows, key=lambda t: t.qty)
    first, last = rows[0], rows[-1]
    return {
        "instrument": trades.instrument,
        "connection_id": trades.connection_id,
        "count": len(rows),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "buy_volume": dec(buy_volume),
        "sell_volume": dec(sell_volume),
        "volume": dec(volume),
        "delta": dec(buy_volume - sell_volume),
        "vwap": dec(vwap),
        "low": dec(min(prices)),
        "high": dec(max(prices)),
        "first_price": dec(first.price),
        "last_price": dec(last.price),
        "from_ts": first.ts,
        "from_time": iso(first.ts),
        "to_ts": last.ts,
        "to_time": iso(last.ts),
        "span_ms": last.ts - first.ts,
        "largest": {
            "price": dec(largest.price),
            "qty": dec(largest.qty),
            "side": largest.side,
            "ts": largest.ts,
        },
    }


def _bucket_summary(bucket: Cluster, top_levels: int) -> dict[str, Any]:
    levels = sorted(bucket.levels, key=lambda level: level.volume, reverse=True)[:top_levels]
    return {
        "ts": bucket.ts,
        "time": iso(bucket.ts),
        "end_ts": bucket.end_ts,
        "completed": bucket.completed,
        "trades": bucket.trades,
        "volume": dec(bucket.volume),
        "buy_volume": dec(bucket.buy_volume),
        "sell_volume": dec(bucket.sell_volume),
        "delta": dec(bucket.buy_volume - bucket.sell_volume),
        "vwap": dec(bucket.vwap),
        "low": dec(bucket.min_price),
        "high": dec(bucket.max_price),
        "levels_total": len(bucket.levels),
        "top_levels": [
            {
                "price": dec(level.price),
                "volume": dec(level.volume),
                "buy_volume": dec(level.buy_volume),
                "sell_volume": dec(level.sell_volume),
            }
            for level in levels
        ],
    }


def cluster_summary(clusters: Clusters, buckets: int, top_levels: int) -> dict[str, Any]:
    """The newest ``buckets`` buckets, each with its ``top_levels`` levels by volume."""
    newest = clusters.data[-buckets:] if buckets > 0 else []
    return {
        "instrument": clusters.instrument,
        "connection_id": clusters.connection_id,
        "interval": clusters.interval,
        "buckets_available": len(clusters.data),
        "buckets": [_bucket_summary(bucket, top_levels) for bucket in newest],
    }


def candle_rows(candles: Candles) -> dict[str, Any]:
    """Bars as compact rows under a column header — the cheapest shape for a context window."""
    return {
        "instrument": candles.instrument,
        "connection_id": candles.connection_id,
        "interval": candles.interval,
        "columns": ["ts", "time", "open", "high", "low", "close", "volume", "closed"],
        "rows": [
            [
                candle.ts,
                iso(candle.ts),
                str(candle.open),
                str(candle.high),
                str(candle.low),
                str(candle.close),
                str(candle.volume),
                candle.closed,
            ]
            for candle in candles.data
        ],
    }


def _order_row(order: Any) -> dict[str, Any]:
    return {
        "key": order.key,
        "exchange_id": order.exchange_id,
        "instrument": order.instrument,
        "side": order.side,
        "type": order.order_type,
        "price": dec(order.price),
        "size": dec(order.size),
        "filled": dec(order.filled),
        "remaining": dec(order.remaining),
        "status": order.status,
        "created_ts": order.created_ts,
        "created_time": iso(order.created_ts),
    }


def _trigger_row(trigger: Any) -> dict[str, Any]:
    return {
        "id": trigger.id,
        "instrument": trigger.instrument,
        "type": trigger.trigger_type,
        "trigger_price": dec(trigger.trigger_price),
        "rule": trigger.rule,
        "size": dec(trigger.size),
        "notional": dec(trigger.notional),
        "status": trigger.status,
    }


def open_orders_summary(orders: AccountOrders, instrument: str | None = None) -> dict[str, Any]:
    """Open orders and triggers, optionally of one instrument, with the keys needed to cancel."""
    rows = [o for o in orders.data if instrument is None or o.instrument == instrument]
    triggers = [t for t in orders.triggers if instrument is None or t.instrument == instrument]
    return {
        "connection_id": orders.connection_id,
        "instrument": instrument,
        "orders": [_order_row(o) for o in rows],
        "triggers": [_trigger_row(t) for t in triggers],
    }


def account_overview(
    balances: AccountBalances, positions: AccountPositions, orders: AccountOrders
) -> dict[str, Any]:
    """Balances, positions and the number of open orders per instrument in one answer."""
    counts: dict[str, dict[str, int]] = {}
    for order in orders.data:
        counts.setdefault(order.instrument, {"orders": 0, "triggers": 0})["orders"] += 1
    for trigger in orders.triggers:
        counts.setdefault(trigger.instrument, {"orders": 0, "triggers": 0})["triggers"] += 1
    return {
        "connection_id": balances.connection_id,
        "balances": [
            {
                "currency": b.currency,
                "total": dec(b.total),
                "available": dec(b.available),
                "locked": dec(b.locked),
            }
            for b in balances.data
        ],
        "positions": [
            {
                "instrument": p.instrument,
                "side": p.side,
                "size": dec(p.size),
                "entry_price": dec(p.entry_price),
                "notional": dec(p.notional),
                "unrealized_pnl": dec(p.unrealized_pnl),
                "mark_price": dec(p.mark_price),
            }
            for p in positions.data
        ],
        "open_orders": [
            {"instrument": instrument, **count} for instrument, count in sorted(counts.items())
        ],
        "open_orders_total": len(orders.data),
        "triggers_total": len(orders.triggers),
    }


def fills_summary(fills: AccountFills) -> dict[str, Any]:
    """Fills oldest first plus buy and sell volume totals."""
    buy = sum((f.qty for f in fills.data if f.side == "buy"), Decimal(0))
    sell = sum((f.qty for f in fills.data if f.side == "sell"), Decimal(0))
    return {
        "connection_id": fills.connection_id,
        "count": len(fills.data),
        "buy_volume": dec(buy),
        "sell_volume": dec(sell),
        "fills": [
            {
                "trade_id": f.trade_id,
                "order_id": f.order_id,
                "instrument": f.instrument,
                "side": f.side,
                "price": dec(f.price),
                "qty": dec(f.qty),
                "fee": dec(f.fee),
                "fee_currency": f.fee_currency,
                "ts": f.ts,
                "time": iso(f.ts),
            }
            for f in fills.data
        ],
    }
