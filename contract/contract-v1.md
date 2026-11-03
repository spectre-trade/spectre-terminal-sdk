# Local API v1 — contract

The Local API is HTTP/JSON and WebSocket/JSON on `127.0.0.1` inside the
terminal process. An external program on the same machine — a script, an
SDK, later an MCP client — gets the same data the window gets: connections,
the instrument catalogue, trades, the order book, clusters, candles, the
account — and places orders with the same commands the window uses. The reasoning and the design live in
the terminal repository as ADR-0014; this page is what clients are promised.
Within v1 the contract only grows: new fields, codes, topics and operations
may appear, existing ones never change type and never disappear. A client
must ignore fields it does not know.

The terminal repository keeps a minimal example client next to this file;
the supported clients are the SDK packages.

## Address, enabling, token

- Base URL — `http://127.0.0.1:48180/v1`. The port is fixed; it can be
  overridden with the `SPECTRE_LOCAL_API_PORT` variable when the terminal
  starts. The terminal publishes the current port as `local_api_port` in
  `instance.json` next to its database (absent or `null` while the API is
  off).
- The API is **off by default**. It is switched on with the "Local API"
  toggle in the general settings of the Settings App, without a restart. The
  same row has "Copy token" and "Reissue token"; reissuing revokes the
  previous token immediately and closes open streams.
- The token is `spt_` followed by 64 hex characters. It is passed only in
  the `Authorization: Bearer <token>` header, for HTTP and for the WebSocket
  handshake alike. A token in the query string is not accepted.
- Token scopes: `market:read` (market data, catalogue, stream),
  `connections:read` (connections), `account:read` (orders, positions,
  balances, fills) and `trading:write` (placing and cancelling orders,
  closing positions). All are granted: there is no separate write switch,
  an enabled Local API grants everything (product decision). A token issued
  before a scope existed receives it on the next terminal start.

A request is rejected before processing when:

| Condition | Response |
| --- | --- |
| no token, a foreign token, or the API is off | `401 unauthorized`, header `WWW-Authenticate: Bearer` |
| an `Origin` header is present (request from a browser page) | `403 forbidden` |
| `Host` is neither `127.0.0.1` nor `localhost` | `403 forbidden` |
| the token lacks the required scope | `403 forbidden_scope` |

There is no CORS layer on purpose: a browser page must not reach the API.

## General rules

- **Instrument address** — the string `exchange:market:symbol`, exchange in
  lower case: `binance:futures:BTCUSDT`, `bybit:spot:BTCUSDT`. The symbol is
  the one from the exchange catalogue.
- **Source connection.** An exchange and market may have several connections
  (accounts). The `connection_id` parameter is optional: without it the
  enabled trading connection of that exchange and market is used, otherwise
  the read-only one, otherwise `404 not_found`. The chosen id is always
  returned in the response. A `connection_id` of another exchange or market
  is `400 invalid_request`; there is no silent substitution.
- **Money** — `Decimal` strings without normalisation: `"67000.10"` stays
  `"67000.10"`. Money never arrives as a JSON number.
- **Time** — `ts`, UTC milliseconds, integer. Exchange time, where it exists,
  is a separate `exchange_ts` field.
- **Lists** — wrapped as `{"data": [...]}`, metadata next to `data`.
- **Errors** — every non-2xx status carries the body
  `{"error": {"code": "...", "message": "..."}}`. The code is stable and part
  of the contract, the message is for humans. A `404` for an unknown path has
  the same form and likewise requires a token.

| Code | HTTP | When |
| --- | --- | --- |
| `unauthorized` | 401 | the token does not match or the API is off |
| `forbidden` | 403 | `Origin` present or a foreign `Host` |
| `forbidden_scope` | 403 | the token lacks the operation's scope |
| `not_found` | 404 | no such operation, connection, or no connection for the instrument |
| `invalid_request` | 400 | parameters: bad instrument, interval, depth, foreign `connection_id` |
| `unsupported` | 501 | the venue's data is not relayed (MOEX) or the terminal was built without the market-data tap |
| `not_active` | 409 | clusters of the instrument are not being computed yet (see `/market/clusters`) or the instrument's leverage is not loaded yet (see `/account/leverage`) |
| `rate_limited` | 429 | ceiling on connections, subscriptions, instruments, subscription rate or trading commands |
| `not_tradable` | 409 | the connection does not trade: disabled, read-only or without credentials |
| `unavailable` | 503 | storage, exchange or coordinator did not answer; no data yet |

MOEX data is not served through the API (`unsupported`) while the product
question of relaying it stays open.

## Operations

Reads are `GET`, writes are `POST` and `DELETE` (section "Writing"). The
required scope is named at each one.

### `/v1/meta` — any token

API version, terminal build, token scopes, limits, stream topics.

```json
{
  "api_version": "1",
  "app_version": "1.9.4",
  "build_hash": "3f1c2ab",
  "build_env": "production",
  "features": "local-api",
  "scopes": ["market:read", "connections:read", "account:read", "trading:write"],
  "limits": {
    "ws_connections_per_token": 8,
    "subscriptions_per_connection": 100,
    "api_only_instruments": 50,
    "exchange_subscriptions_per_second": 5,
    "commands_per_second": 10
  },
  "topics": ["trades", "ticker", "mark_price", "book.top", "clusters",
             "account.orders", "account.positions", "account.balances", "account.fills"]
}
```

`topics` is empty when the terminal was built without the market-data tap:
the stream and the market operations then answer `unsupported`.

### `/v1/health` — any token

```json
{
  "status": "ok",
  "uptime_ms": 1234,
  "clients": 1,
  "streams": 3,
  "api_only_instruments": 2,
  "dropped_events": 0,
  "dropped_frames": 0,
  "overflow_closes": 0,
  "stream_available": true
}
```

`clients` — stream connections, `streams` — pairs the hub holds,
`api_only_instruments` — those of them opened only for the API.
`dropped_events` — events the hub did not accept from the market-data loop
(its channel was full), `dropped_frames` — frames that did not fit into
client queues, `overflow_closes` — clients closed with code `4008`.

### `/v1/connections`, `/v1/connections/{id}` — `connections:read`

The terminal's connections. No secrets in any form: no keys, no wallet
address, no mask.

```json
{
  "data": [
    {
      "id": 12,
      "exchange": "binance",
      "market": "futures",
      "label": "Main",
      "enabled": true,
      "read_only": false,
      "has_credentials": true,
      "proxy_bound": false,
      "status": {
        "state": "connected",
        "last_event": { "code": "connected", "ts": 1730294400123 }
      }
    }
  ]
}
```

`status.state`: `disabled`, `enabled` (switched on, no attempts in this
session yet), `connecting`, `connected`, `failed`. It is derived from the
toggle and the last record of the connection history; `last_event.code` is a
code from the same feed the Settings App shows. `read_only` — a connection
without credentials, created by the terminal for market data.

### `/v1/instruments` — `market:read`

The catalogue of an exchange and market, paged by symbol.

| Parameter | Value |
| --- | --- |
| `connection_id` **or** `exchange` + `market` | whose pair to list, one of the two is required |
| `q` | substring of the symbol or the base coin, case-insensitive |
| `limit` | 1–2000, default 500 |
| `cursor` | `next_cursor` of the previous page |

```json
{
  "exchange": "binance",
  "market": "futures",
  "data": [
    {
      "instrument": "binance:futures:BTCUSDT",
      "exchange": "binance",
      "market": "futures",
      "symbol": "BTCUSDT",
      "base": "BTC",
      "quote": "USDT",
      "status": "active",
      "tick_size": "0.1",
      "lot_size": "0.001",
      "min_size": "0.001",
      "contract_value": "1"
    }
  ],
  "next_cursor": null
}
```

Steps and minimums are `null` when the exchange did not report them.
`status` is passed through as the exchange reported it.

### `/v1/market/candles` — `market:read`

Candle history by the same path the chart in the window uses.

| Parameter | Value |
| --- | --- |
| `instrument` | required |
| `connection_id` | optional |
| `interval` | a code from `/v1/market/intervals`: `1m`, `5m`, … |
| `limit` | up to 2000, default 500 |
| `end` | right boundary, UTC milliseconds; default now |

```json
{
  "instrument": "binance:futures:BTCUSDT",
  "connection_id": 12,
  "interval": "1m",
  "data": [
    {
      "ts": 1730294400000,
      "open": "67000.1", "high": "67010.5", "low": "66990.0", "close": "67003.4",
      "volume": "52.1", "quote_volume": "3490000.5",
      "closed": true
    }
  ]
}
```

`ts` is the bar open, `volume` is in the base coin. The exchange did not
answer — `503 unavailable`.

### `/v1/market/intervals` — `market:read`

Candle and cluster intervals the terminal knows.

```json
{
  "candles":  [{ "id": "1m", "duration_ms": 60000 }, { "id": "1M", "duration_ms": 2592000000 }],
  "clusters": [{ "id": "30s", "duration_ms": 30000 }, { "id": "1d", "duration_ms": 86400000 }]
}
```

`duration_ms` is nominal: for `1M` it is 30 days, month boundaries are taken
from the bars' `ts`.

### Cold market operations

`/v1/market/trades`, `/snapshot`, `/orderbook`, `/clusters` read the hub's
buffers. An instrument without a subscription gets a temporary one: the hub
opens a stream, waits for the first data **up to 3 s** and keeps the stream
for another **30 s** after the response, so a program polling one pair once a
second does not hit the exchange on every call. All four require
`market:read`, the `instrument` parameter and an optional `connection_id`.

#### `/v1/market/trades`

| Parameter | Value |
| --- | --- |
| `limit` | 1–1000 latest, default 100 |
| `since_ts` | not earlier than this receive time, UTC milliseconds |

```json
{
  "instrument": "binance:futures:BTCUSDT",
  "connection_id": 12,
  "data": [
    { "id": null, "price": "67000.1", "qty": "0.012", "side": "buy",
      "ts": 1730294400125, "exchange_ts": 1730294400119 }
  ]
}
```

Oldest to newest. `ts` is when the trade passed through the terminal; `id` is
always `null` in v1. The buffer is the last thousand trades of the pair; 3 s
without a single trade gives an honestly empty response.

#### `/v1/market/snapshot`

The latest the hub knows about the pair.

```json
{
  "instrument": "binance:futures:BTCUSDT",
  "connection_id": 12,
  "ts": 1730294400130,
  "best_bid": ["67000.1", "1.25"],
  "best_ask": ["67000.2", "0.40"],
  "last_trade": { "id": null, "price": "67000.1", "qty": "0.012", "side": "buy",
                  "ts": 1730294400125, "exchange_ts": 1730294400119 },
  "mark_price": "67001.0",
  "ticker": { "price": "67000.1", "change_24h_pct": "1.25", "volume_24h": "81234.5",
              "high_24h": null, "low_24h": null, "best_bid": null, "best_ask": null,
              "ts": 1730294400120 }
}
```

`best_bid` and `best_ask` are `[price, size]` pairs from the hub's book;
`null` until a book snapshot has arrived. The other fields are `null` until
data has arrived.

#### `/v1/market/orderbook`

| Parameter | Value |
| --- | --- |
| `depth` | 1–200, default 50 |

```json
{
  "instrument": "binance:futures:BTCUSDT",
  "connection_id": 12,
  "ts": 1730294400123,
  "depth": 20,
  "bids": [["67000.1", "1.25"]],
  "asks": [["67000.2", "0.40"]]
}
```

Bids from the best downwards, asks from the best upwards, a level is
`[price, size]`. No full book within 3 s — `503 unavailable`: an empty book
would look like an empty market.

#### `/v1/market/clusters`

Cluster buckets at the interval selected for the instrument in the terminal
(`5m` by default). The terminal computes the clusters, there is no second
computation; an instrument not open in the window is computed on API request
and its history is seeded from the Spectre backend. The first response waits
for the seed up to 3 s; if it does not arrive — `409 not_active`: the
clusters are not being computed yet, the stream is held for 30 s, and a
retry a few seconds later finds them.

```json
{
  "instrument": "binance:futures:BTCUSDT",
  "connection_id": 12,
  "interval": "5m",
  "ts": 1730294400123,
  "data": [
    {
      "interval": "5m",
      "ts": 1730294100000,
      "end_ts": 1730294400000,
      "volume": "12.5", "buy_volume": "7.25", "sell_volume": "5.25",
      "trades": 120,
      "vwap": "67000.1", "min_price": "66990.0", "max_price": "67010.5",
      "completed": false,
      "last_trade_ts": 1730294399870,
      "levels": [
        { "price": "67000.1", "volume": "1.25", "buy_volume": "0.75",
          "sell_volume": "0.5", "buy_trades": 3, "sell_trades": 2 }
      ]
    }
  ]
}
```

Oldest to newest, at most ten buckets. `levels` are all levels of the bucket
from the lowest price to the highest. `last_trade_ts` is `0` for a bucket
from history without a trade time. The interval is one per instrument and is
chosen in the terminal: a change shows up in the `interval` field of the next
response.

## Account — `account:read`

Orders, positions, balances and fills of **one connection**: `connection_id`
is required on all four operations, there is no default connection here — a
venue may have several trading connections, and showing someone else's
account silently is not acceptable. An unknown id is `404 not_found`. Orders
and positions are the same cut the terminal window sees; balances and fills
are accumulated by the terminal from the moment the API is switched on: the
exchange sends a balance on change, not on request, so a currency nothing
happened to since the switch-on is absent from the list. Instruments are
addressed as `exchange:market:symbol` everywhere. Switching a connection off
or restarting it clears its copy of balances and fills.

### `/v1/account/orders`

Open orders (`pending`, `open`, `partially_filled`) and trigger orders.

```json
{
  "connection_id": 12,
  "data": [
    { "key": "t-123456789012345678", "exchange_id": "987654321",
      "instrument": "binance:futures:BTCUSDT", "side": "buy", "type": "limit",
      "price": "67000.1", "size": "0.012", "filled": "0", "remaining": "0.012",
      "notional": "804", "status": "open", "created_ts": 1730294400123 }
  ],
  "triggers": [
    { "id": "42", "instrument": "binance:futures:BTCUSDT", "type": "stop_loss",
      "trigger_price": "66000", "rule": "price_below_or_equal", "size": "0.012",
      "notional": "804", "status": "open", "order_type": "market",
      "client_id": "c1", "created_ts": 1730294400123 }
  ]
}
```

`key` is the terminal's order key (`t-…`), `exchange_id` the exchange's id;
either is `null` while unknown. `size`, `filled`, `remaining` are in the base
coin, `notional` is the quote amount the trader entered (`null` for an order
that came from an exchange snapshot). `status`: `pending`, `open`,
`partially_filled`. A trigger's `type` is `stop_loss`, `take_profit` or
`stop`; `rule` is `price_above_or_equal` or `price_below_or_equal`; `status`
is `open`, `finished`, `inactive` or `invalid`; `size`, `notional`,
`order_type`, `client_id` and `created_ts` may be `null`.

### `/v1/account/positions`

```json
{
  "connection_id": 12,
  "data": [
    { "instrument": "binance:futures:BTCUSDT", "side": "long", "size": "0.5",
      "lot_size": "1", "entry_price": "66500", "notional": "33250",
      "unrealized_pnl": "250", "mark_price": "67000" }
  ]
}
```

`size` is in the base coin (on MOEX in lots, `lot_size` being base units per
lot), `notional` in the quote, `unrealized_pnl` as the terminal computes it,
`mark_price` the terminal's mark (best bid for a long, best ask for a short),
`null` until the first book tick.

### `/v1/account/balances`

```json
{
  "connection_id": 12,
  "data": [
    { "currency": "USDT", "total": "1000.5", "available": "900.5",
      "locked": "100", "ts": 1730294400123 }
  ]
}
```

Per currency, the latest value from the exchange; `available` and `locked`
are `null` when the venue does not report them; `ts` is the exchange time
where there is one, otherwise the receive time.

### `/v1/account/fills`

| Parameter | Value |
| --- | --- |
| `limit` | 1–1000 latest, default 100 |
| `since_ts` | not earlier than this exchange time, UTC milliseconds |

```json
{
  "connection_id": 12,
  "data": [
    { "trade_id": "t1", "order_id": "987654321",
      "instrument": "binance:futures:BTCUSDT", "side": "buy", "price": "67000.1",
      "qty": "0.012", "fee": "0.32", "fee_currency": "USDT",
      "position_side": "long", "ts": 1730294400123 }
  ]
}
```

Oldest to newest; the buffer is the connection's last thousand fills since
the API was switched on. `position_side` is `long`/`short` on hedged venues,
otherwise `null`.

## Writing — `trading:write`

Trading commands go through the same channel and the same handlers as the
window's commands, with source `api` in the operations file. The `accepted`
answer means **accepted by the terminal**, not by the exchange: the
exchange's confirmation, fill or rejection arrives through the stream — the
client watches `account.orders` in the stream or `GET /v1/account/orders`,
as the window watches its book. The connection must trade (enabled, with
credentials, not read-only), otherwise `409 not_tradable`; the instrument
must belong to its venue and market, otherwise `400 invalid_request`. The
rate is 10 commands per second per listener (`limits.commands_per_second`),
above it `429 rate_limited`. A full command queue is `503 unavailable` and
the command was not sent.

Every trading operation — triggers and leverage below included — answers alike:

```json
{
  "accepted": true,
  "operation_id": "1730294400123-000001",
  "key": "t-173029440012300001",
  "connection_id": 12,
  "instrument": "binance:futures:BTCUSDT"
}
```

`operation_id` identifies the operation in the terminal's operations file;
`key` is the terminal's order key (`t-…`) under which the order will appear
in `account.orders`; for cancellations, amendments and leverage `key` is `null`.

### `POST /v1/orders`

```json
{ "connection_id": 12, "instrument": "binance:futures:BTCUSDT",
  "side": "buy", "type": "limit", "price": "67000.1", "size": "0.012",
  "reduce_only": false, "post_only": false, "time_in_force": "gtc",
  "client_key": "bot-42" }
```

| Field | Value |
| --- | --- |
| `side` | `buy` or `sell` |
| `type` | `limit` (needs `price`) or `market` (no `price`) |
| `size` **or** `notional` | amount in the base coin or the quote amount — exactly one |
| `reduce_only`, `post_only` | optional, default `false` |
| `time_in_force` | `gtc`, `ioc`, `fok`, `post_only`; absent — the venue's default |
| `client_key` | the client's idempotency key: a repeat with the same key returns the previous answer and does not duplicate the order (the last thousand are remembered) |

The venue's minimums and steps are checked before sending, as the window
does: a refusal is `400 invalid_request` with the reason.

### `DELETE /v1/orders/{id}?connection_id=12&instrument=…`

`{id}` is the terminal key `t-…` or the exchange's order id. The
cancellation goes to the exchange directly; the confirmation arrives through
the stream.

### `POST /v1/orders/cancel-all`

```json
{ "connection_id": 12, "instrument": "binance:futures:BTCUSDT" }
```

Cancel every order of the instrument — the same as the space bar in the
order book.

### `POST /v1/positions/close`

Same body. Closes the instrument's position the way the window does: on
futures a market order for the position size with `close_position`, on spot
"cancel all and close" as one atomic command. Without an open position —
`400 invalid_request`.

### Trigger orders

The same services the window uses: a stop loss and a take profit are placed
**on the open position** (side, size and rule come from it; without a
position — `400 invalid_request`), a stop with its own side and amount. On a
venue for which the terminal keeps no trigger orders all four operations
answer `501 unsupported`. The trigger appears in `triggers` of
`/v1/account/orders` and of the `account.orders` topic: the key from
`accepted.key` is its `client_id`, and it is cancelled and amended by the
numeric `id` from there.

#### `POST /v1/orders/trigger`

```json
{ "connection_id": 12, "instrument": "binance:futures:BTCUSDT",
  "kind": "stop_loss", "trigger_price": "66000", "client_key": "sl-42" }
{ "connection_id": 12, "instrument": "binance:futures:BTCUSDT",
  "kind": "stop", "side": "sell", "notional": "800", "trigger_price": "66000",
  "rule": "price_below_or_equal" }
```

| Field | Value |
| --- | --- |
| `kind` | `stop_loss`, `take_profit` — on the open position; `stop` — its own |
| `trigger_price` | the trigger price |
| `side` | `stop` only: `buy` or `sell` |
| `notional` | `stop` only: the quote amount |
| `rule` | `stop` only: `price_above_or_equal` or `price_below_or_equal`; absent — above the market for a buy, below for a sell |
| `client_key` | idempotency key, as for `POST /v1/orders` |

`key` in the answer is the trigger's key (`sl_…`, `tp_…`, `stop_…`).

#### `DELETE /v1/orders/trigger/{id}?connection_id=12&instrument=…`

`{id}` is the numeric `id` of the trigger from `/v1/account/orders`; a
`t-…` or `sl_…` key is not accepted here (`400 invalid_request`).

#### `PATCH /v1/orders/trigger/{id}`

```json
{ "connection_id": 12, "instrument": "binance:futures:BTCUSDT",
  "kind": "stop_loss", "trigger_price": "65500" }
```

A new trigger price by the same sequential replacement the window does: the
old trigger is cancelled, a new one placed. `kind` is required; a `stop`
also needs `side` and takes an optional `rule`.

#### `POST /v1/orders/trigger/cancel-all`

```json
{ "connection_id": 12, "instrument": "binance:futures:BTCUSDT" }
```

Cancel every trigger of the instrument. Plain orders are not touched — they
are cancelled by `POST /v1/orders/cancel-all`.

## Leverage and margin mode

Futures operations: spot has no leverage.

### `GET /v1/account/leverage?connection_id=12&instrument=…` — `account:read`

```json
{
  "connection_id": 12,
  "instrument": "binance:futures:BTCUSDT",
  "leverage": 10,
  "max_leverage": 125,
  "mode": "manual",
  "margin_mode": "cross"
}
```

`mode` is `manual`, `max` or `smart` (the terminal's mode, not the
exchange's); `margin_mode` is `cross` or `isolated`. Read from the
terminal's cache, which the window's instrument selection and a leverage
change fill: an instrument the terminal has not touched yet answers
`409 not_active` — open it in the window or set the leverage with the `POST`
below.

### `POST /v1/account/leverage` — `trading:write`

```json
{ "connection_id": 12, "instrument": "binance:futures:BTCUSDT", "leverage": 20 }
{ "connection_id": 12, "instrument": "binance:futures:BTCUSDT", "mode": "max" }
```

Exactly one of the two: `leverage` (an integer ≥ 1) or `mode` (`max`,
`smart`). The answer is `accepted`; the applied value shows in `GET` after
the exchange answered.

### `POST /v1/account/margin-mode` — `trading:write`

```json
{ "connection_id": 12, "instrument": "binance:futures:BTCUSDT", "margin_mode": "isolated" }
```

`cross` or `isolated`. Changing it with an open position is refused by the
exchange, as in the window — the `accepted` answer does not know that.

## Stream `/v1/stream` — `market:read` (account topics: `account:read`)

WebSocket at the same address: `ws://127.0.0.1:48180/v1/stream`, the token in
the handshake header. All frames are text JSON with a `type` field.

### Client requests

```json
{ "type": "subscribe", "request_id": "r1", "topic": "trades",
  "instrument": "binance:futures:BTCUSDT", "connection_id": 12, "params": {} }
{ "type": "subscribe", "request_id": "r3", "topic": "account.fills", "connection_id": 12 }
{ "type": "unsubscribe", "request_id": "r2", "sub": "7:trades" }
```

`request_id` is optional and is returned in the response as is. For market
topics `instrument` is required and `connection_id` is chosen by the general
rule. For account topics (`account.*`) it is the other way round:
`connection_id` is required, `instrument` is not used, and the scope is
`account:read`. `params` apply only to `book.top`; other topics ignore them.

### Responses and events

```json
{ "type": "subscribed",   "request_id": "r1", "sub": "7:trades", "connection_id": 12 }
{ "type": "unsubscribed", "request_id": "r2", "sub": "7:trades" }
{ "type": "error", "request_id": "r1", "code": "not_found", "message": "..." }
{ "type": "error", "sub": "7:trades", "code": "unavailable", "message": "..." }
{ "type": "event", "sub": "7:trades", "seq": 41, "ts": 1730294400130, "data": [ ... ] }
{ "type": "gap",   "sub": "7:trades", "from_seq": 42, "to_seq": 57, "reason": "slow_consumer" }
```

- `sub` is the subscription identifier, `"{stream}:{topic}"`; for account
  topics `"{connection}:account.<topic>"`. It is the same for every client
  subscribed to the pair and topic; `unsubscribe` accepts only it.
- `seq` is the event number within the subscription; it grows by one for
  `trades`. For conflated topics gaps in the numbering are normal.
- `gap` arrives before the first frame after a loss, only for `trades`: the
  client was not reading, and events from `from_seq` to `to_seq` are lost.
  They can be re-read with `GET /v1/market/trades` and `since_ts`.
- `error` with `sub` and without `request_id` — the subscription was removed
  by the server: the venue refused or the coordinator did not subscribe the
  pair. A new `subscribe` starts it again.

### Topics

| Topic | `params` | event `data` | Delivery |
| --- | --- | --- | --- |
| `trades` | — | array of trades, as in `/market/trades` | in order, with `gap` on overflow |
| `ticker` | — | 24h ticker, as `ticker` in `/market/snapshot` | conflation: the last value of a batch |
| `mark_price` | — | `{ "mark_price": "...", "ts": ... }` | conflation |
| `book.top` | `depth` 1–200 (50), `interval_ms` ≥ 50 (100) | top of the book, as `/market/orderbook` | conflation at the subscriber's interval; `seq` is the book version; the first frame as soon as the book is ready |
| `clusters` | — | one bucket, as an element of `data` in `/market/clusters` | conflation per bucket; the source flushes every 16 ms |
| `account.orders` | — | `{ "instrument", "orders": [...], "triggers": [...] }` — orders and triggers of **one instrument** after a change, as in `/account/orders` | conflation: the latest state of the instrument |
| `account.positions` | — | `{ "instrument", "position": {...} }`, as an element of `/account/positions`; a close is `"position": null` | conflation |
| `account.balances` | — | one currency's balance, as an element of `/account/balances` | conflation |
| `account.fills` | — | one fill, as an element of `/account/fills` | a frame per fill; one that does not fit is lost and `seq` shows the gap — re-read `/account/fills` with `since_ts` |

`book.top` parameters are per subscriber; values out of range give
`error invalid_request` on the request. A `clusters` frame arrives for every
bucket that changed; an interval change in the terminal shows up in the
`interval` field. Account topics do not touch the exchange: subscribing only
opens the tap, events flow from the moment the connection sends them; there
is no snapshot frame on subscribe — the current state is read with the
`/account/*` operations.

### Connection life

- The server sends `ping` every 20 s; without a `pong` for 50 s the
  connection is considered dead and is closed.
- A client that does not read delays neither the terminal nor other clients:
  frames that do not fit into its queue are lost (`gap` for `trades`; for the
  other topics the next frame is newer). An overflow that lasts longer than
  5 s closes the connection with code `4008`.
- Close codes: `1001` — the API was switched off or the token was reissued;
  `4008` — the client is too slow; `4029` — the per-token connection limit.
- A close initiated by the client is completed by the server: it answers
  with a close frame carrying the client's code rather than dropping the
  connection.
- Unneeded subscriptions are removed by the server itself: closing the socket
  removes all subscriptions of the connection; a pair without subscribers is
  released at the exchange after 30 s. An explicit `unsubscribe` removes the
  subscription immediately.

### Limits

Printed in `/v1/meta`; a refusal is `error rate_limited` on the request or a
`4029` close.

| Limit | Value |
| --- | --- |
| stream connections per token | 8 |
| subscriptions per connection | 100 |
| instruments opened only for the API | 50; instruments open in the window do not count |
| new exchange subscriptions per second | 5 |
| trading commands per second | 10 |

## What the API does not do in v1

- It does not write settings and does not open order books in the window.
  Of trading, there is no grid move by dragging (`MoveOrderGrid`) and no
  trading on MOEX.
- It does not vouch for the outcome at the exchange: `accepted` is accepted
  by the terminal, the outcome is read from the account.
- It does not serve account history of past sessions: fills and balances
  start with the API being switched on; orders and positions are current.
- It does not choose the cluster interval and does not compute several
  intervals per instrument.
- It does not serve MOEX data.
- It does not accept requests from browser pages or foreign hosts.

## For terminal developers

- Operations — `src/infra/transport/local_api/v1/ops/`, DTOs —
  `v1/dto/mod.rs`, stream protocol — `v1/stream/`. The market-data hub —
  `src/modules/market_feed/`.
- The shape of every response is pinned by fixtures in
  `tests/it/local_api/fixtures/`: a field gone or changed type fails the
  `contract` test, and that is v2, not a v1 change.
- The market-data tap is built by the `local-api` feature, which is in the
  default build. A build without the tap: `cargo build --no-default-features`;
  in it `topics` is empty and the stream and market operations answer
  `unsupported`.
- Load run: `cargo test --release --features local-api-bench --test it
  local_api::load -- --ignored --nocapture`. Cost of the tap per event:
  `cargo test --release --features local-api-bench --lib market_feed_cost --
  --ignored --nocapture`.
