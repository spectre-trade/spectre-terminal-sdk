#!/usr/bin/env python3
"""Print the latest cluster buckets of one instrument and the levels of the last one.

Usage: ``clusters.py [exchange:market:SYMBOL]`` (default ``binance:futures:BTCUSDT``).
An instrument not open in the window is computed on request and seeded from
the backend; the first call can answer ``not_active`` — this script waits
three seconds and asks once more.
"""

from __future__ import annotations

import sys
import time

from spectre_terminal import ApiError, Clusters, SpectreTerminalError, Terminal

INSTRUMENT = sys.argv[1] if len(sys.argv) > 1 else "binance:futures:BTCUSDT"


def fetch(terminal: Terminal) -> Clusters:
    try:
        return terminal.clusters(INSTRUMENT)
    except ApiError as error:
        if error.code != "not_active":
            raise
        print("clusters are still being seeded, retrying in 3 s")
        time.sleep(3)
        return terminal.clusters(INSTRUMENT)


def main() -> int:
    terminal = Terminal.discover()
    clusters = fetch(terminal)
    print(f"{clusters.instrument} interval {clusters.interval}, {len(clusters.data)} bucket(s)")
    for bucket in clusters.data:
        state = "done" if bucket.completed else "open"
        print(
            f"  {bucket.ts} .. {bucket.end_ts} [{state}] volume {bucket.volume} "
            f"(buy {bucket.buy_volume} / sell {bucket.sell_volume}), {bucket.trades} trades, "
            f"vwap {bucket.vwap}, range {bucket.min_price}..{bucket.max_price}"
        )
    if clusters.data:
        last = clusters.data[-1]
        print(f"levels of the last bucket ({len(last.levels)}), highest price first:")
        for level in reversed(last.levels):
            print(
                f"  {level.price:>12}  {level.volume:>12}  "
                f"buy {level.buy_volume} ({level.buy_trades})  "
                f"sell {level.sell_volume} ({level.sell_trades})"
            )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SpectreTerminalError as error:
        sys.exit(f"error: {error}")
