# Account

Orders, positions, balances and fills of a connection, read with the
`account:read` scope. The account is always **one connection**: a venue may
hold several trading accounts in the terminal, so every call takes a
`connection_id` and there is no default. Ids come from `connections()`.

```python
orders = terminal.account_orders(12)
for order in orders.data:            # open: pending, open, partially_filled
    print(order.key, order.exchange_id, order.side, order.price, order.remaining, order.status)
for trigger in orders.triggers:      # stop_loss, take_profit, stop
    print(trigger.id, trigger.trigger_type, trigger.trigger_price, trigger.rule)

for position in terminal.account_positions(12).data:
    print(position.instrument, position.side, position.size, position.entry_price,
          position.unrealized_pnl, position.mark_price)

for balance in terminal.account_balances(12).data:
    print(balance.currency, balance.total, balance.available, balance.locked)

fills = terminal.account_fills(12, limit=50, since_ts=last_seen)
```

```ts
const { data: orders, triggers } = await terminal.accountOrders(12);
const positions = await terminal.accountPositions(12);
const balances = await terminal.accountBalances(12);
const fills = await terminal.accountFills(12, { limit: 50, sinceTs: lastSeen });
```

## What you get, and from where

| Operation | Source in the terminal | Note |
| --- | --- | --- |
| orders | the same order book the window shows, the same instant | `key` is the terminal's own key (`t-…`), `exchange_id` the exchange's; either may be `null` while unknown |
| positions | the position bar's state | `mark_price` is the terminal's mark: best bid for a long, best ask for a short; `null` until the first book tick |
| balances | accumulated from exchange events since the API was switched on | a currency that has not changed since then is absent |
| fills | the last 1000 fills per connection since the API was switched on | re-read with `since_ts` after a stream gap |

Balances and fills are copies the terminal keeps for the API, not exchange
queries: enabling the API starts them, switching a connection off or
restarting it with new keys clears them. Orders and positions are live state
and need no warm-up.

## Live updates

Four stream topics mirror the four operations, keyed by connection instead
of instrument:

```python
async with terminal.stream() as stream:
    await stream.subscribe("account.orders", connection_id=12)
    await stream.subscribe("account.fills", connection_id=12)
    async for frame in stream:
        ...
```

- `account.orders` carries the full list of orders and triggers of **one
  instrument** after any change — replace, do not merge.
- `account.positions` carries one instrument's position; a close arrives
  as `position: null`.
- `account.balances` carries one currency.
- `account.fills` carries one fill per frame. Frames are conflated like the
  other topics: one that does not fit a slow client's queue is dropped and
  `seq` jumps; re-read `/v1/account/fills` with `since_ts` to recover.

Subscribing does not touch the exchange and sends no snapshot: read the
current state with the operations above, then follow the stream.

## Money and sizes

Prices, sizes and amounts are decimal strings on the wire. Sizes are in the
base coin (`size`, `filled`, `remaining`); `notional` is the quote amount the
trader entered, `null` for orders that came from an exchange snapshot. On
MOEX positions are in lots, with `lot_size` giving base units per lot.
