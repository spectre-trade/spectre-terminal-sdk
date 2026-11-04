# spectre-terminal

Python client for the **Local API** of Spectre Terminal: connections, the
instrument catalogue, trades, order books, clusters, candles and the
account from a running terminal on the same machine, plus orders placed
with the same commands the window uses — over HTTP and WebSocket on
`127.0.0.1`.

- Python 3.10+, one dependency (`websockets`), HTTP through the standard library.
- Money is `decimal.Decimal`, never `float`; timestamps are `int` UTC milliseconds.
- The token is taken only from `SPECTRE_LOCAL_API_TOKEN` or the constructor
  argument and never appears in errors or logs.

## Install

```bash
pip install spectre-terminal
```

Switch the API on in the terminal: **Settings App → General → Local API**,
then **Copy token** and keep it in `SPECTRE_LOCAL_API_TOKEN`.

## Quick start

```python
from spectre_terminal import Terminal

terminal = Terminal.discover()  # port from instance.json, token from SPECTRE_LOCAL_API_TOKEN

for connection in terminal.connections():
    print(connection.id, connection.exchange, connection.market, connection.status.state)

snapshot = terminal.snapshot("binance:futures:BTCUSDT")
print(snapshot.best_bid, snapshot.best_ask, snapshot.last_trade)

book = terminal.orderbook("binance:futures:BTCUSDT", depth=10)
print(book.bids[0], book.asks[0])
```

Live data over the stream:

```python
import asyncio
from spectre_terminal import Terminal


async def main():
    terminal = Terminal.discover()
    async with terminal.stream() as stream:
        await stream.subscribe("trades", "binance:futures:BTCUSDT")
        await stream.subscribe("book.top", "binance:futures:BTCUSDT", depth=5, interval_ms=200)
        async for frame in stream:
            print(frame)


asyncio.run(main())
```

Every operation of the contract is a method of `Terminal`: `meta`, `health`,
`connections`, `connection`, `instruments` / `iter_instruments`,
`intervals`, `candles`, `trades`, `snapshot`, `orderbook`, `clusters`,
`account_orders`, `account_positions`, `account_balances`, `account_fills`,
`place_order`, `cancel_order`, `cancel_all`, `close_position`, `place_trigger`,
`cancel_trigger`, `cancel_all_triggers`, `amend_trigger`, `leverage`,
`set_leverage`, `set_margin_mode`, `workspace`, `workspace_window`,
`open_stack`, `open_multiview`, `set_stack_instrument`, `close_stack`,
`close_tab`, `activate_tab`, `close_window`, `activate_window`, `stream`.
Errors derive from `SpectreTerminalError`; the terminal's own refusals are
`ApiError` with the contract's `code` and the HTTP `status`.

Runnable scripts live in [`examples/`](examples/); `examples/smoke.py` calls
every read operation once against a running terminal.

## Account

Orders, positions, balances and fills of **one connection**: `connection_id`
is required, there is no default connection here. Balances and fills are
accumulated from the moment the API was switched on.

```python
orders = terminal.account_orders(12)
for order in orders.data:
    print(order.key, order.side, order.order_type, order.remaining, "@", order.price)
for trigger in orders.triggers:
    print(trigger.trigger_type, trigger.rule, trigger.trigger_price)

for position in terminal.account_positions(12).data:
    print(position.instrument, position.side, position.size, position.unrealized_pnl)

for balance in terminal.account_balances(12).data:
    print(balance.currency, balance.total, balance.available)

for fill in terminal.account_fills(12, limit=50).data:
    print(fill.ts, fill.instrument, fill.side, fill.qty, "@", fill.price, fill.fee)
```

The JSON key `type` is `order_type` on `Order` and `trigger_type` on
`TriggerOrder`. Live changes come over the stream: the `account.*` topics
subscribe by `connection_id` and take no instrument, and `Event.data` is an
`OrdersUpdate` (orders and triggers of one instrument), a `PositionUpdate`
(`position` is `None` on a close), a `Balance` or a `Fill`. There is no
snapshot frame on subscribe: read the current state over HTTP first.

```python
async with terminal.stream() as stream:
    await stream.subscribe("account.orders", connection_id=12)
    await stream.subscribe("account.fills", connection_id=12)
    async for frame in stream:
        print(frame.topic, frame.data)
```

## Trading

`place_order`, `cancel_order`, `cancel_all` and `close_position` go through
the same handlers as the window. Each returns `Accepted` — accepted **by the
terminal**, not by the exchange: the confirmation, fill or rejection arrives
on `account.orders`, under `Accepted.key`. Money is `Decimal`, `str` or
`int` and travels as a string; a `float` is refused.

```python
from decimal import Decimal

accepted = terminal.place_order(
    12,
    "binance:futures:BTCUSDT",
    side="buy",
    order_type="limit",
    price=Decimal("60000"),
    size="0.001",
    client_key="bot-42",  # idempotency: a repeat with the same key places nothing
)
print(accepted.key, accepted.operation_id)

terminal.cancel_order(12, "binance:futures:BTCUSDT", accepted.key)
terminal.cancel_all(12, "binance:futures:BTCUSDT")  # the space bar in the order book
terminal.close_position(12, "binance:futures:BTCUSDT")  # as the window closes it
```

A connection that does not trade (disabled, read-only, without credentials)
is `ApiError` with code `not_tradable`; a venue minimum or step refusal is
`invalid_request`; more than `meta().limits.commands_per_second` commands
per second is `rate_limited`. `examples/place_and_cancel.py` places one
limit far below the market, watches it appear on `account.orders` and
cancels it — on a real account, so pick a test one.

Trigger orders and leverage go the same way. A stop loss or take profit is
placed on the open position (its side and size come from the position); a
`stop` carries its own side and quote amount. Triggers are cancelled and
moved by the numeric `id` from `account_orders().triggers`.

```python
sl = terminal.place_trigger(12, "binance:futures:BTCUSDT", kind="stop_loss", trigger_price="59000")
trigger = next(t for t in terminal.account_orders(12).triggers if t.client_id == sl.key)
terminal.amend_trigger(
    12, "binance:futures:BTCUSDT", trigger.id, kind="stop_loss", trigger_price="58500"
)
terminal.cancel_trigger(12, "binance:futures:BTCUSDT", trigger.id)

print(
    terminal.leverage(12, "binance:futures:BTCUSDT")
)  # not_active until the terminal touched the instrument
terminal.set_leverage(12, "binance:futures:BTCUSDT", leverage=20)
terminal.set_margin_mode(12, "binance:futures:BTCUSDT", "isolated")
```

The layout — windows, tabs, stacks and charts — is read with `workspace()`
and changed with commands the window applies itself: a stack opens in a new
tab or window, tabs and windows are selected and closed, a stack is
re-pointed or closed. Ids are numbers of the current run of the terminal;
the `workspace` stream topic sends the whole layout on every change.

```python
opened = terminal.open_stack("binance:futures:BTCUSDT", chart=True, activate=False)
terminal.set_stack_instrument(opened.stacks[0], "binance:futures:ETHUSDT")
terminal.close_tab(opened.window_id, opened.tab_id)
```

## Documentation

The guides are in [`../docs`](../docs); the authoritative description of
the API is [`../contract/contract-v1.md`](../contract/contract-v1.md).

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests run against the fixtures in `../contract/fixtures`; no terminal is
needed.
