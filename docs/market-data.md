# Market data

All market operations require `market:read`. Each takes an instrument address
and an optional `connection_id`; see [Instruments and connections](#instruments-and-connections).
Money is a decimal string on the wire — `Decimal` in Python, `string` in
TypeScript — and time is integer UTC milliseconds. The exact shapes are in
[contract/contract-v1.md](../contract/contract-v1.md); this page is about
using them.

## Instruments and connections

An instrument is `exchange:market:symbol`, exchange in lower case, symbol as
the exchange spells it: `binance:futures:BTCUSDT`, `okx:futures:ETH-USDT-SWAP`,
`gate:futures:ETH_USDT`, `hyperliquid:futures:ETH`. The catalogue tells you
the spelling:

```python
page = terminal.instruments(exchange="binance", market="futures", q="BTC", limit=50)
for instrument in page.data:
    print(instrument.instrument, instrument.tick_size, instrument.lot_size)

for instrument in terminal.iter_instruments(connection_id=12):   # follows next_cursor
    ...
```

```ts
const page = await terminal.instruments({ exchange: "binance", market: "futures", q: "BTC" });
for await (const instrument of terminal.iterInstruments({ connectionId: 12 })) { ... }
```

A venue and market may have several connections (accounts) in the terminal.
Without `connection_id` the API picks the enabled trading connection of that
venue and market, else the read-only one, and returns the chosen id in every
response. Pass `connection_id` to pin one; an id of another venue or market is
`invalid_request`, never a silent substitution.

## Candles and intervals

```python
intervals = terminal.intervals()                   # .candles and .clusters, each with id and duration_ms
candles = terminal.candles("binance:futures:BTCUSDT", "1m", limit=500)
for candle in candles.data:                        # oldest first; ts is the bar open
    print(candle.ts, candle.open, candle.close, candle.volume, candle.closed)
```

`end` is the right boundary (UTC ms, default now); page backwards by passing
the first bar's `ts` as `end`. The history comes from the exchange through
the same path the terminal's chart uses, so `503 unavailable` means the
exchange did not answer.

## Cold operations: trades, snapshot, order book, clusters

`trades`, `snapshot`, `orderbook` and `clusters` read the terminal's
in-memory buffers. If the instrument is not open in a terminal window and no
stream subscriber holds it, the first call creates a temporary subscription
at the exchange, waits **up to 3 s** for the first data, and the terminal
keeps the subscription for **30 s** after the answer. Polling one pair once a
second therefore costs the exchange one subscription, not one per call.

Consequences worth knowing:

- The first call can be slow (the exchange round trip) and partially empty:
  `snapshot` answers as soon as the first event has arrived, and fields whose
  data has not come yet are `null`. A second call a few seconds later is
  complete. For live data use the stream instead of polling.
- `orderbook` never returns a partial book: without a full book within 3 s it
  answers `503 unavailable`.
- `clusters` of an instrument that the terminal is not computing yet may
  answer `409 not_active` on the first call; the subscription is held, so a
  retry after a few seconds succeeds.
- Opening many instruments only for the API is limited (50 by default, see
  `meta().limits`), and new exchange subscriptions are rate limited (5 per
  second): a burst over the limit gets `429 rate_limited` and should be
  retried later.

### Trades

```python
trades = terminal.trades("binance:futures:BTCUSDT", limit=200)      # oldest to newest
trades = terminal.trades("binance:futures:BTCUSDT", since_ts=last_seen_ts)
```

The buffer holds the last 1000 trades of the pair. `ts` is when the trade
passed through the terminal; `exchange_ts` is the exchange time; `id` is
always `null` in v1.

### Snapshot

```python
s = terminal.snapshot("binance:futures:BTCUSDT")
s.best_bid, s.best_ask       # (price, size) or None until a book snapshot has arrived
s.last_trade                 # Trade or None
s.mark_price                 # Decimal or None (futures)
s.ticker                     # Ticker or None: price, change_24h_pct, volume_24h, …
```

### Order book

```python
book = terminal.orderbook("binance:futures:BTCUSDT", depth=20)     # 1–200, default 50
book.bids[0], book.asks[0]                                          # best levels, (price, size)
```

Bids are sorted from the best price downwards, asks from the best upwards.
On exchanges whose book starts from a REST snapshot (the Binance family) the
first call costs the terminal one snapshot request against the exchange's
rate limit; the terminal paces these itself.

### Clusters

```python
clusters = terminal.clusters("binance:futures:BTCUSDT")
clusters.interval                                   # the interval chosen in the terminal, "5m" by default
for bucket in clusters.data:                        # oldest to newest, at most 10
    bucket.ts, bucket.end_ts, bucket.volume, bucket.buy_volume, bucket.sell_volume, bucket.vwap
    for level in bucket.levels:                     # lowest price to highest
        level.price, level.buy_volume, level.sell_volume
```

The terminal computes clusters once, for its own windows and for the API
alike, at **one interval per instrument** chosen in the terminal. The API
cannot pick the interval in v1; a change in the terminal shows up in the
`interval` field of the next response. Instruments not open in a window are
computed on request and seeded with history from the Spectre backend.

## MOEX

Data of the Moscow Exchange is not served through the API while the product
question of relaying it is open: every market operation and stream
subscription for a `moex:*` instrument answers `unsupported`.
