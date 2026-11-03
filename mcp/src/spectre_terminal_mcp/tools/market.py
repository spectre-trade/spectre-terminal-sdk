"""Market tools: snapshot, top of book, trades summary, clusters, candles.

Each tool maps to one cold operation of the Local API and trims the answer to
what a model can use. The first call for an instrument that is not open in a
terminal window makes the terminal subscribe at the exchange: it can take up
to 3 s and answer with partial data (see the contract, "cold market
operations"); the tools wait once where that is cheap.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field
from spectre_terminal.errors import ApiError

from ..summaries import book_summary, candle_rows, cluster_summary, snapshot_summary, trades_summary
from ..terminal import TerminalProvider

__all__ = ["register"]

_INSTRUMENT = Field(
    description="Instrument address exchange:market:symbol, e.g. binance:futures:BTCUSDT"
)
_CONNECTION = Field(
    description="Connection id from terminal_status; the terminal picks one when omitted"
)
# A cold snapshot answers as soon as the first event arrives; the rest of the
# fields fill within a couple of seconds. One short wait gives the agent a
# complete answer instead of nulls.
_WARM_UP = 2.0
# Clusters of an instrument the terminal was not computing yet are seeded
# from the backend; the contract says a retry a few seconds later finds them.
_SEED_WAIT = 3.0


def register(server: MCPServer, provider: TerminalProvider) -> None:
    from . import READ_ONLY

    @server.tool(name="market_snapshot", annotations=READ_ONLY)
    def market_snapshot(
        instrument: Annotated[str, _INSTRUMENT],
        connection_id: Annotated[int | None, _CONNECTION] = None,
    ) -> dict[str, Any]:
        """Last price, best bid and ask with the spread, mark price and 24h change and volume.

        The cheapest way to answer "where is X trading right now". Fields the
        terminal has not received yet are null; for an instrument that is not
        open in the terminal the tool waits briefly once to fill them.
        """
        with provider.call() as terminal:
            snapshot = terminal.snapshot(instrument, connection_id=connection_id)
            if snapshot.last_trade is None or snapshot.ticker is None:
                time.sleep(_WARM_UP)
                snapshot = terminal.snapshot(instrument, connection_id=connection_id)
        return snapshot_summary(snapshot)

    @server.tool(name="order_book_top", annotations=READ_ONLY)
    def order_book_top(
        instrument: Annotated[str, _INSTRUMENT],
        depth: Annotated[int, Field(ge=1, le=50, description="Levels per side")] = 10,
        connection_id: Annotated[int | None, _CONNECTION] = None,
    ) -> dict[str, Any]:
        """The top levels of the order book with volume per side and the imbalance.

        ``imbalance`` is (bid volume - ask volume) / (bid volume + ask volume)
        over the returned levels: +1 is all bids, -1 is all asks. Levels are
        [price, size] pairs, bids from the best price down, asks from the best
        price up.
        """
        with provider.call() as terminal:
            book = terminal.orderbook(instrument, depth=depth, connection_id=connection_id)
        return book_summary(book, depth)

    @server.tool(name="recent_trades_summary", annotations=READ_ONLY)
    def recent_trades_summary(
        instrument: Annotated[str, _INSTRUMENT],
        limit: Annotated[
            int, Field(ge=1, le=1000, description="How many of the latest trades to summarise")
        ] = 200,
        connection_id: Annotated[int | None, _CONNECTION] = None,
    ) -> dict[str, Any]:
        """Buy and sell volume, delta, VWAP, price range and the largest print of recent trades.

        Summarises the latest ``limit`` trades the terminal has for the
        instrument (it keeps the last 1000). The trades themselves are not
        returned; ``span_ms`` says how much time the batch covers.
        """
        with provider.call() as terminal:
            trades = terminal.trades(instrument, limit=limit, connection_id=connection_id)
        return trades_summary(trades)

    @server.tool(name="cluster_summary", annotations=READ_ONLY)
    def cluster_summary_tool(
        instrument: Annotated[str, _INSTRUMENT],
        buckets: Annotated[int, Field(ge=1, le=10, description="Newest buckets to return")] = 3,
        top_levels: Annotated[
            int, Field(ge=1, le=20, description="Price levels per bucket, by volume")
        ] = 5,
        connection_id: Annotated[int | None, _CONNECTION] = None,
    ) -> dict[str, Any]:
        """Volume clusters per bucket: volume by side, delta, VWAP, range, busiest price levels.

        Buckets are at the interval the trader selected in the terminal for
        this instrument (5m by default); the newest bucket is usually still
        open (``completed`` false). An instrument the terminal was not
        computing yet is started on request and seeded with history; the tool
        waits once for the seed.
        """
        with provider.call() as terminal:
            try:
                clusters = terminal.clusters(instrument, connection_id=connection_id)
            except ApiError as error:
                if error.code != "not_active":
                    raise
                time.sleep(_SEED_WAIT)
                clusters = terminal.clusters(instrument, connection_id=connection_id)
        return cluster_summary(clusters, buckets, top_levels)

    @server.tool(name="candles", annotations=READ_ONLY)
    def candles(
        instrument: Annotated[str, _INSTRUMENT],
        interval: Annotated[
            str, Field(description="Bar interval: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M")
        ] = "1m",
        limit: Annotated[int, Field(ge=1, le=500, description="Newest bars to return")] = 50,
        end: Annotated[
            int | None,
            Field(description="Right boundary as UTC milliseconds; now when omitted"),
        ] = None,
        connection_id: Annotated[int | None, _CONNECTION] = None,
    ) -> dict[str, Any]:
        """OHLCV bars for an interval, newest ``limit`` bars, oldest first.

        Rows are compact arrays under ``columns``. ``ts`` is the bar open;
        ``closed`` false marks the bar still forming. Page backwards by
        passing the first row's ``ts`` as ``end``.
        """
        with provider.call() as terminal:
            history = terminal.candles(
                instrument, interval, limit=limit, end=end, connection_id=connection_id
            )
        return candle_rows(history)
