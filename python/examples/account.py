#!/usr/bin/env python3
"""Print the open orders, positions, balances and latest fills of one connection.

Usage: ``account.py [connection_id]``. Without an argument the first
connection that trades (enabled, with credentials, not read-only) is used.
Needs a running terminal with the Local API switched on and the token in
``SPECTRE_LOCAL_API_TOKEN``. Reads only: nothing is placed or cancelled.
"""

from __future__ import annotations

import sys

from spectre_terminal import Connection, SpectreTerminalError, Terminal


def pick_connection(terminal: Terminal) -> Connection | None:
    for connection in terminal.connections():
        if connection.enabled and connection.has_credentials and not connection.read_only:
            return connection
    return None


def main() -> int:
    terminal = Terminal.discover()
    if len(sys.argv) > 1:
        connection = terminal.connection(int(sys.argv[1]))
    else:
        picked = pick_connection(terminal)
        if picked is None:
            print("no trading connection: enable one with credentials in the Settings App")
            return 1
        connection = picked
    cid = connection.id
    print(f"connection {cid}: {connection.exchange}:{connection.market} {connection.label!r}")

    orders = terminal.account_orders(cid)
    print(f"\n{len(orders.data)} open order(s), {len(orders.triggers)} trigger(s)")
    for order in orders.data:
        print(
            f"  {order.instrument:<28} {order.side:<4} {order.order_type:<6} "
            f"{order.remaining}/{order.size} @ {order.price}  {order.status}  key {order.key}"
        )
    for trigger in orders.triggers:
        print(
            f"  {trigger.instrument:<28} {trigger.trigger_type:<11} {trigger.rule} "
            f"{trigger.trigger_price}  size {trigger.size}  {trigger.status}"
        )

    positions = terminal.account_positions(cid)
    print(f"\n{len(positions.data)} position(s)")
    for position in positions.data:
        print(
            f"  {position.instrument:<28} {position.side:<5} {position.size} "
            f"@ {position.entry_price}  mark {position.mark_price}  pnl {position.unrealized_pnl}"
        )

    balances = terminal.account_balances(cid)
    print(f"\n{len(balances.data)} balance(s) since the API came on")
    for balance in balances.data:
        print(
            f"  {balance.currency:<8} total {balance.total}  available {balance.available}  "
            f"locked {balance.locked}"
        )

    fills = terminal.account_fills(cid, limit=20)
    print(f"\n{len(fills.data)} latest fill(s), oldest first")
    for fill in fills.data:
        fee = f"{fill.fee} {fill.fee_currency}" if fill.fee is not None else "-"
        print(
            f"  {fill.ts}  {fill.instrument:<28} {fill.side:<4} {fill.qty} @ {fill.price}  "
            f"fee {fee}  order {fill.order_id}"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SpectreTerminalError as error:
        sys.exit(f"error: {error}")
