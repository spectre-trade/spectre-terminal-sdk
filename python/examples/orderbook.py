#!/usr/bin/env python3
"""Print the top of one instrument's order book as a ladder.

Usage: ``orderbook.py [exchange:market:SYMBOL] [depth]`` (defaults
``binance:futures:BTCUSDT`` and 10). ``unavailable`` means no full book
arrived within 3 s; run it again.
"""

from __future__ import annotations

import sys

from spectre_terminal import SpectreTerminalError, Terminal

INSTRUMENT = sys.argv[1] if len(sys.argv) > 1 else "binance:futures:BTCUSDT"
DEPTH = int(sys.argv[2]) if len(sys.argv) > 2 else 10


def main() -> int:
    terminal = Terminal.discover()
    book = terminal.orderbook(INSTRUMENT, depth=DEPTH)
    print(
        f"{book.instrument} via connection {book.connection_id}, depth {book.depth}, ts {book.ts}"
    )
    for level in reversed(book.asks):
        print(f"  {'':>14}  | {level.price:>14} | {level.size:>12}")
    print(f"  {'-' * 14}  + {'-' * 14} + {'-' * 12}")
    for level in book.bids:
        print(f"  {level.size:>14}  | {level.price:>14} |")
    if book.bids and book.asks:
        print(f"spread: {book.asks[0].price - book.bids[0].price}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SpectreTerminalError as error:
        sys.exit(f"error: {error}")
