# Trading

Placing and cancelling orders and closing positions, with the
`trading:write` scope. There is no separate write switch in the terminal:
an enabled Local API grants everything the token holds, and the Local API
toggle is the kill switch.

```python
accepted = terminal.place_order(
    12, "binance:futures:BTCUSDT",
    side="buy", order_type="limit", price="60000", size="0.001",
    client_key="bot-42",
)
print(accepted.key)                         # "t-…", the terminal's order key

terminal.cancel_order(12, "binance:futures:BTCUSDT", accepted.key)
terminal.cancel_all(12, "binance:futures:BTCUSDT")
terminal.close_position(12, "binance:futures:BTCUSDT")
```

```ts
const accepted = await terminal.placeOrder({
  connectionId: 12, instrument: "binance:futures:BTCUSDT",
  side: "buy", type: "limit", price: "60000", size: "0.001", clientKey: "bot-42",
});
await terminal.cancelOrder({ connectionId: 12, instrument: "binance:futures:BTCUSDT", orderId: accepted.key! });
await terminal.cancelAll({ connectionId: 12, instrument: "binance:futures:BTCUSDT" });
await terminal.closePosition({ connectionId: 12, instrument: "binance:futures:BTCUSDT" });
```

## Accepted is not filled

Every trading call answers with the same shape:

```json
{ "accepted": true, "operation_id": "…", "key": "t-…", "connection_id": 12,
  "instrument": "binance:futures:BTCUSDT" }
```

`accepted` means the **terminal** took the command and handed it to the
same path the window uses. The exchange's acknowledgement, fills and
rejections arrive afterwards, the way they arrive for the window: watch
`account.orders` in the stream, or poll `account_orders()`. The `key` is the
terminal's order key under which the order shows up there; cancellations
return `key: null`. `operation_id` identifies the operation in the terminal's
operations file, which is what support reads.

A bot that needs the outcome therefore subscribes to `account.orders` (and
`account.fills`) **before** placing, then matches by `key`.

## Orders

| Field | Rules |
| --- | --- |
| `side` | `buy` or `sell` |
| `type` | `limit` needs `price`; `market` must not have one |
| `size` or `notional` | exactly one: base-coin amount, or quote amount (the terminal converts as the window does) |
| `reduce_only`, `post_only` | optional, default `false` |
| `time_in_force` | `gtc`, `ioc`, `fok`, `post_only`; absent means the venue's default |
| `client_key` | your idempotency key: a repeat with the same key gets the previous answer and places nothing; the terminal remembers the last 1000 |

Minimums and price/size steps are checked before the command leaves, exactly
as for a click in the window; a refusal is `400 invalid_request` with the
reason.

`cancel_order` takes the terminal key (`t-…`) or the exchange's id. Cancel
only after the order shows an `exchange_id` in `account.orders`: a cancel
sent while the order is still `pending` reaches the exchange with nothing to
cancel, and the order stays.

`cancel_all` cancels every order of the instrument, like the space bar in
the order book. `close_position` closes the way the window does: on futures
a market order for the position size, on spot "cancel all and close" as one
atomic command; without an open position it is `400 invalid_request`.

## Refusals

| Code | Meaning |
| --- | --- |
| `not_tradable` (409) | the connection is disabled, read-only or has no credentials |
| `invalid_request` (400) | bad side/type/amount, instrument of another venue, below the venue's minimum |
| `unsupported` (501) | MOEX instruments are not served to external programs |
| `rate_limited` (429) | more than 10 commands per second on this listener |
| `unavailable` (503) | the terminal's command queue was full; the command was **not** sent, retry |

## Trigger orders

A stop loss or take profit is placed **on the open position**: the terminal
takes side, size and rule from it, exactly as the window does, and refuses
with `invalid_request` without one. A `stop` is your own order: it needs
`side` and `notional` (the quote amount) and takes an optional `rule`
(`price_above_or_equal` or `price_below_or_equal`; absent means above the
market for a buy, below for a sell).

```python
sl = terminal.place_trigger(12, "binance:futures:BTCUSDT", kind="stop_loss", trigger_price="59000", client_key="sl-1")
stop = terminal.place_trigger(12, "binance:futures:BTCUSDT", kind="stop", side="sell", notional="800", trigger_price="59000")

trigger = next(t for t in terminal.account_orders(12).triggers if t.client_id == sl.key)
terminal.amend_trigger(12, "binance:futures:BTCUSDT", trigger.id, kind="stop_loss", trigger_price="58500")
terminal.cancel_trigger(12, "binance:futures:BTCUSDT", trigger.id)
terminal.cancel_all_triggers(12, "binance:futures:BTCUSDT")   # plain orders stay
```

```ts
const sl = await terminal.placeTrigger({ connectionId: 12, instrument, kind: "stop_loss", triggerPrice: "59000", clientKey: "sl-1" });
const trigger = (await terminal.accountOrders(12)).triggers.find((t) => t.client_id === sl.key)!;
await terminal.amendTrigger({ connectionId: 12, instrument, triggerId: trigger.id, kind: "stop_loss", triggerPrice: "58500" });
await terminal.cancelTrigger({ connectionId: 12, instrument, triggerId: trigger.id });
```

`accepted.key` is the trigger's key (`sl_…`, `tp_…`, `stop_…`); it shows up
as `client_id` of the trigger in `account.orders`. Cancelling and amending
use the **numeric `id`** from there, not the key. Amending is the window's
sequential replacement: the old trigger is cancelled, a new one placed, and
`kind` has to be given again (a `stop` also its `side`). A venue for which
the terminal keeps no trigger orders answers `unsupported` (501).

## Leverage and margin mode

Futures only. Reading needs `account:read`, changing `trading:write`.

```python
print(terminal.leverage(12, "binance:futures:BTCUSDT"))      # Leverage(leverage=10, max_leverage=125, mode="manual", margin_mode="cross", …)
terminal.set_leverage(12, "binance:futures:BTCUSDT", leverage=20)
terminal.set_leverage(12, "binance:futures:BTCUSDT", mode="max")   # or "smart"
terminal.set_margin_mode(12, "binance:futures:BTCUSDT", "isolated")
```

```ts
await terminal.leverage({ connectionId: 12, instrument });
await terminal.setLeverage({ connectionId: 12, instrument, leverage: 20 });
await terminal.setMarginMode({ connectionId: 12, instrument, marginMode: "isolated" });
```

The read comes from the terminal's cache, which the window's instrument
selection and a leverage change fill: an instrument the terminal has not
touched yet answers `not_active` (409). Setting the leverage is the way it
enters the cache. `mode` in the answer is the terminal's leverage mode
(`manual`, `max`, `smart`), not the exchange's. Changing the margin mode
with an open position is refused by the exchange, as in the window; the
`accepted` answer does not know that yet.

## What is not there yet

Moving an order grid by dragging, and trading on MOEX. The MCP server
exposes the same operations as tools; see [mcp.md](mcp.md).
