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

## What is not there yet

Trigger orders (stop loss, take profit), leverage and margin mode, moving
an order grid, and trading on MOEX. The MCP server exposes the same four
operations as tools; see [mcp.md](mcp.md).
