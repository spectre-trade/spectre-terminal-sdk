# Streaming

`/v1/stream` is a WebSocket at the same address as the HTTP API
(`ws://127.0.0.1:48180/v1/stream`), authenticated by the same bearer header on
the handshake. All frames are text JSON with a `type` field. Requires
`market:read`.

```python
async with terminal.stream() as stream:
    trades = await stream.subscribe("trades", "binance:futures:BTCUSDT")
    top = await stream.subscribe("book.top", "binance:futures:BTCUSDT", depth=5, interval_ms=200)
    async for frame in stream:
        match frame:
            case Event(sub=trades.sub):  ...
            case Gap():                  ...   # trades were lost while you were not reading
            case SubscriptionError():    ...   # the server dropped a subscription
```

```ts
const stream = await terminal.stream();
const trades = await stream.subscribe({ topic: "trades", instrument: "binance:futures:BTCUSDT" });
for await (const frame of stream) {
  if (frame.type === "event" && frame.sub === trades.sub) ...
}
await stream.close();
```

## Subscriptions

A subscription is a topic on an instrument (plus the optional
`connection_id`, chosen by the same rule as in HTTP). The reply carries the
subscription id `sub` — `"{stream}:{topic}"` — and the chosen connection.
The id is shared by every client subscribed to the same pair and topic;
`unsubscribe` takes it, not the topic and instrument.

| Topic | `params` | Event `data` | Delivery |
| --- | --- | --- | --- |
| `trades` | — | array of trades, as in `/market/trades` | in order; `gap` on overflow |
| `ticker` | — | the 24h ticker, as `ticker` in `/market/snapshot` | conflated: last value of a batch |
| `mark_price` | — | `{ "mark_price": "…", "ts": … }` | conflated |
| `book.top` | `depth` 1–200 (50), `interval_ms` ≥ 50 (100) | top of the book, as `/market/orderbook` | conflated at your interval; `seq` is the book version; first frame as soon as the book is ready |
| `clusters` | — | one bucket, as an element of `data` in `/market/clusters` | conflated per bucket; the source flushes every 16 ms |
| `account.orders` | — | `{ instrument, orders, triggers }` of one instrument after a change | conflated: latest state |
| `account.positions` | — | `{ instrument, position }`; a close is `position: null` | conflated |
| `account.balances` | — | one currency's balance | conflated |
| `account.fills` | — | one fill | a frame per fill, dropped when the queue is full; `seq` shows the gap |

Account topics are keyed by **connection**, not instrument: subscribe with
`connection_id` and no `instrument` (scope `account:read`). They do not touch
the exchange and send no snapshot; read the state with `/v1/account/*` first.
See [account.md](account.md).

`book.top` parameters are per subscriber: two clients can watch the same book
at different depths and rates. Out-of-range values are refused with
`invalid_request`.

## Events, sequence numbers, gaps

Every event frame has `sub`, `seq`, `ts` (when the frame was built) and
`data`. For `trades` `seq` grows by one per event; for conflated topics the
numbers skip, which is normal.

A client that stops reading does not slow the terminal or other clients down:
frames that do not fit into its queue are dropped. For `trades` the next
frame after a loss is preceded by

```json
{ "type": "gap", "sub": "7:trades", "from_seq": 42, "to_seq": 57, "reason": "slow_consumer" }
```

and the lost trades can be re-read with `GET /v1/market/trades` and
`since_ts`. For the other topics there is no gap frame: the next frame is
simply the newest state. An overflow that lasts more than 5 s closes the
connection with code `4008`.

## Server-side errors on a subscription

```json
{ "type": "error", "sub": "7:trades", "code": "unavailable", "message": "…" }
```

An `error` with `sub` and without `request_id` means the server removed the
subscription: the venue refused, the connection was switched off, or the
coordinator could not subscribe the pair. The clients surface it as a
`SubscriptionError` frame in the iterator. Subscribe again when the cause is
gone (for a connection that was switched off: when it is back).

## Connection life

- The server pings every 20 s; a connection without a pong for 50 s is
  closed. The client libraries answer pings for you.
- Closing the socket removes all its subscriptions; a pair nobody holds is
  released at the exchange 30 s later. An explicit `unsubscribe` removes a
  subscription at once.
- A close you initiate is answered with a close frame carrying your code; the
  server never drops the connection on you.

| Close code | Meaning | What to do |
| --- | --- | --- |
| `1001` | the API was switched off or the token was reissued | reconnect with the current token when the API is back |
| `4008` | your client was not reading for more than 5 s | read faster, subscribe to less, or conflate on your side |
| `4029` | too many stream connections for this token (8) | reuse a connection; one socket can hold 100 subscriptions |

The clients raise `StreamClosed(code, reason)` from the iterator on these
codes and expose `close_code`/`closeCode` otherwise.

## Limits

Printed by `/v1/meta`: 8 stream connections per token, 100 subscriptions per
connection, 50 instruments opened only for the API (instruments open in a
terminal window do not count), 5 new exchange subscriptions per second. A
refusal is an `error` with code `rate_limited` on the request (retry after a
moment) or a `4029` close.
