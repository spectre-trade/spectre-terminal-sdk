#!/usr/bin/env python3
"""Subscribe to trades and the top of the book of one instrument, print ten frames, exit.

Usage: ``trades_stream.py [exchange:market:SYMBOL]`` (default ``binance:futures:BTCUSDT``).
"""

from __future__ import annotations

import asyncio
import sys

from spectre_terminal import Event, Gap, SpectreTerminalError, SubscriptionError, Terminal

INSTRUMENT = sys.argv[1] if len(sys.argv) > 1 else "binance:futures:BTCUSDT"
FRAMES = 10


async def main() -> int:
    terminal = Terminal.discover()
    async with terminal.stream() as stream:
        trades = await stream.subscribe("trades", INSTRUMENT)
        book = await stream.subscribe("book.top", INSTRUMENT, depth=5, interval_ms=500)
        print(f"subscribed: {trades.sub} and {book.sub} via connection {trades.connection_id}")
        seen = 0
        async for frame in stream:
            if isinstance(frame, Gap):
                print(f"gap on {frame.sub}: events {frame.from_seq}..{frame.to_seq} lost")
                continue
            if isinstance(frame, SubscriptionError):
                print(f"subscription {frame.sub} removed: {frame.code} {frame.message}")
                continue
            assert isinstance(frame, Event)
            seen += 1
            if frame.topic == "trades":
                last = frame.data[-1]
                print(
                    f"trades seq={frame.seq}: {len(frame.data)} trade(s), "
                    f"last {last.side} {last.qty} @ {last.price}"
                )
            elif frame.topic == "book.top":
                bid, ask = frame.data.bids[0], frame.data.asks[0]
                print(
                    f"book v{frame.seq}: bid {bid.price} ({bid.size}) / "
                    f"ask {ask.price} ({ask.size})"
                )
            if seen >= FRAMES:
                break
        await stream.unsubscribe(trades)
        await stream.unsubscribe(book)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except SpectreTerminalError as error:
        sys.exit(f"error: {error}")
    except KeyboardInterrupt:
        pass
