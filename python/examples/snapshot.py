#!/usr/bin/env python3
"""Print the market snapshot of one instrument: best prices, last trade, mark, ticker.

Usage: ``snapshot.py [exchange:market:SYMBOL]`` (default ``binance:futures:BTCUSDT``).
A cold instrument takes up to 3 s while the terminal opens its stream.
"""

from __future__ import annotations

import sys

from spectre_terminal import SpectreTerminalError, Terminal

INSTRUMENT = sys.argv[1] if len(sys.argv) > 1 else "binance:futures:BTCUSDT"


def main() -> int:
    terminal = Terminal.discover()
    snapshot = terminal.snapshot(INSTRUMENT)
    print(f"{snapshot.instrument} via connection {snapshot.connection_id} at {snapshot.ts}")
    if snapshot.best_bid and snapshot.best_ask:
        spread = snapshot.best_ask.price - snapshot.best_bid.price
        print(f"  bid {snapshot.best_bid.price} x {snapshot.best_bid.size}")
        print(f"  ask {snapshot.best_ask.price} x {snapshot.best_ask.size}  (spread {spread})")
    else:
        print("  book: no snapshot yet")
    trade = snapshot.last_trade
    if trade:
        print(f"  last trade: {trade.side} {trade.qty} @ {trade.price} at {trade.ts}")
    print(f"  mark price: {snapshot.mark_price}")
    ticker = snapshot.ticker
    if ticker:
        print(
            f"  ticker: {ticker.price} ({ticker.change_24h_pct}% 24h), "
            f"volume {ticker.volume_24h}, high {ticker.high_24h}, low {ticker.low_24h}"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SpectreTerminalError as error:
        sys.exit(f"error: {error}")
