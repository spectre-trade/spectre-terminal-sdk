#!/usr/bin/env python3
"""Live smoke check: every operation of the contract once, plus a short stream.

Usage: ``smoke.py [exchange:market:SYMBOL]`` (default ``binance:futures:ETHUSDT``)
with a running terminal, the Local API switched on and the token in
``SPECTRE_LOCAL_API_TOKEN``. Prints one ``PASS``/``FAIL`` line per operation
and exits non-zero if any failed. The token is never printed.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable
from typing import Any

from spectre_terminal import ApiError, Event, SpectreTerminalError, Terminal

INSTRUMENT = sys.argv[1] if len(sys.argv) > 1 else "binance:futures:ETHUSDT"
STREAM_WAIT = 15.0

failures = 0


def check(name: str, operation: Callable[[], Any]) -> Any:
    """Run ``operation``, print one line, return its result (``None`` on failure)."""
    global failures
    started = time.monotonic()
    try:
        result = operation()
    except Exception as error:  # a FAIL line, never a traceback
        failures += 1
        print(f"FAIL {name}: {type(error).__name__}: {error}")
        return None
    elapsed = (time.monotonic() - started) * 1000
    print(f"PASS {name}: {result} ({elapsed:.0f} ms)")
    return result


def clusters_with_retry(terminal: Terminal) -> str:
    try:
        clusters = terminal.clusters(INSTRUMENT)
    except ApiError as error:
        if error.code != "not_active":
            raise
        time.sleep(3)
        clusters = terminal.clusters(INSTRUMENT)
    last = clusters.data[-1] if clusters.data else None
    levels = len(last.levels) if last else 0
    return f"interval {clusters.interval}, {len(clusters.data)} buckets, last has {levels} levels"


async def stream_check(terminal: Terminal) -> str:
    async with terminal.stream() as stream:
        trades = await stream.subscribe("trades", INSTRUMENT)
        book = await stream.subscribe("book.top", INSTRUMENT, depth=5, interval_ms=200)
        wanted = {trades.sub, book.sub}
        seen: dict[str, int] = {}
        deadline = asyncio.get_running_loop().time() + STREAM_WAIT
        while set(seen) < wanted:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(
                    f"no event on {sorted(wanted - set(seen))} within {STREAM_WAIT} s"
                )
            frame = await asyncio.wait_for(stream.__anext__(), timeout=remaining)
            if isinstance(frame, Event):
                seen[frame.sub] = frame.seq
        await stream.unsubscribe(trades)
        await stream.unsubscribe(book)
    return "events on " + ", ".join(f"{sub} (seq {seq})" for sub, seq in sorted(seen.items()))


def main() -> int:
    exchange, market, _symbol = INSTRUMENT.split(":", 2)
    terminal = check("discover", Terminal.discover)
    if terminal is None:
        return 1

    meta = check(
        "meta", lambda: f"app {terminal.meta().app_version}, topics {terminal.meta().topics}"
    )
    check(
        "health", lambda: f"status {terminal.health().status}, clients {terminal.health().clients}"
    )

    connections = check("connections", lambda: terminal.connections())
    if connections:
        first = connections[0].id
        check("connection", lambda: f"{terminal.connection(first).exchange} id {first}")
        print(
            f"     {len(connections)} connection(s): "
            + ", ".join(f"{c.id}={c.exchange}:{c.market}:{c.status.state}" for c in connections)
        )

    pair = {"exchange": exchange, "market": market}
    page = check("instruments", lambda: terminal.instruments(**pair, limit=5))
    if page is not None:
        print(f"     {len(page.data)} on the page, next_cursor {page.next_cursor!r}")
    check(
        "iter_instruments",
        lambda: (
            f"{sum(1 for _ in terminal.iter_instruments(**pair, q='BTC', limit=50))} matching BTC"
        ),
    )

    intervals = check(
        "intervals",
        lambda: terminal.intervals(),
    )
    interval = intervals.candles[0].id if intervals and intervals.candles else "1m"
    if intervals:
        candle_ids = [i.id for i in intervals.candles]
        cluster_ids = [i.id for i in intervals.clusters]
        print(f"     candles {candle_ids}, clusters {cluster_ids}")
    check(
        "candles",
        lambda: f"{len(terminal.candles(INSTRUMENT, interval, limit=5).data)} bars of {interval}",
    )
    check("trades", lambda: f"{len(terminal.trades(INSTRUMENT, limit=20).data)} trades")
    check(
        "snapshot",
        lambda: (lambda s: f"bid {s.best_bid} ask {s.best_ask} mark {s.mark_price}")(
            terminal.snapshot(INSTRUMENT)
        ),
    )
    check(
        "orderbook",
        lambda: (lambda b: f"depth {b.depth}, top {b.bids[0].price} / {b.asks[0].price}")(
            terminal.orderbook(INSTRUMENT, depth=5)
        ),
    )
    check("clusters", lambda: clusters_with_retry(terminal))
    if meta is not None:
        check("stream", lambda: asyncio.run(stream_check(terminal)))

    print(f"{'ALL PASS' if failures == 0 else f'{failures} FAILED'} for {INSTRUMENT}")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SpectreTerminalError as error:
        sys.exit(f"error: {error}")
