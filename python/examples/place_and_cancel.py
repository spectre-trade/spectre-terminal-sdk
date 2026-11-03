#!/usr/bin/env python3
"""Place one limit order far below the market, watch it appear, cancel it, exit.

Usage: ``place_and_cancel.py <connection_id> <exchange:market:SYMBOL> <size>``,
e.g. ``place_and_cancel.py 12 binance:futures:ETHUSDT 0.01``. ``size`` is in
the base coin and must satisfy the venue's minimum.

The order is a buy limit at half the best bid, rounded down to the tick, so
it cannot fill; it is cancelled as soon as it shows up on ``account.orders``.
Still, this is a real order on a real account: run it on a test account.
Needs the token in ``SPECTRE_LOCAL_API_TOKEN``.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from decimal import ROUND_DOWN, Decimal

from spectre_terminal import Event, OrdersUpdate, SpectreTerminalError, Stream, Terminal

WAIT = 15.0
"""Seconds to wait for the order to appear and, later, to disappear from the book."""


def far_price(terminal: Terminal, connection_id: int, instrument: str) -> Decimal:
    """Half the best bid, rounded down to the instrument's tick."""
    snapshot = terminal.snapshot(instrument, connection_id=connection_id)
    if snapshot.best_bid is None:
        raise SystemExit(f"no best bid for {instrument} yet: open its book in the window first")
    price = snapshot.best_bid.price / 2
    symbol = instrument.rsplit(":", 1)[1]
    for entry in terminal.iter_instruments(connection_id=connection_id, q=symbol):
        if entry.instrument == instrument and entry.tick_size:
            return price.quantize(entry.tick_size, rounding=ROUND_DOWN)
    return price


async def watch(stream: Stream, instrument: str, key: str, present: bool) -> bool:
    """Read ``account.orders`` frames until ``key`` is present (or absent) on ``instrument``."""
    deadline = asyncio.get_running_loop().time() + WAIT
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        frame = await asyncio.wait_for(stream.__anext__(), timeout=remaining)
        if not isinstance(frame, Event) or not isinstance(frame.data, OrdersUpdate):
            continue
        if frame.data.instrument != instrument:
            continue
        keys = {order.key for order in frame.data.orders}
        if (key in keys) == present:
            return True


async def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    connection_id, instrument, size = int(sys.argv[1]), sys.argv[2], Decimal(sys.argv[3])
    terminal = Terminal.discover()
    price = far_price(terminal, connection_id, instrument)
    client_key = f"example-{uuid.uuid4().hex[:12]}"

    async with terminal.stream() as stream:
        # subscribe before placing: the first frame may be the one that shows the order
        await stream.subscribe("account.orders", connection_id=connection_id)

        accepted = terminal.place_order(
            connection_id,
            instrument,
            side="buy",
            order_type="limit",
            price=price,
            size=size,
            client_key=client_key,
        )
        key = accepted.key or ""
        print(f"accepted by the terminal: key {key}, operation {accepted.operation_id}")

        if await watch(stream, instrument, key, present=True):
            print(f"order {key} is on the book at {price}")
        else:
            # the frame may have been conflated away: the HTTP view is the fallback
            open_keys = {o.key for o in terminal.account_orders(connection_id).data}
            if key not in open_keys:
                print(f"order {key} did not appear within {WAIT} s: check the window")
                return 1
            print(f"order {key} is on the book at {price} (seen over HTTP)")

        cancelled = terminal.cancel_order(connection_id, instrument, key)
        print(f"cancel accepted: operation {cancelled.operation_id}")
        if await watch(stream, instrument, key, present=False):
            print(f"order {key} left the book")
        else:
            print(f"no frame without {key} within {WAIT} s: check the window")
            return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except SpectreTerminalError as error:
        sys.exit(f"error: {error}")
    except KeyboardInterrupt:
        pass
