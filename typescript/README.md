# @spectre-trade/terminal

TypeScript client for the **Local API** of Spectre Terminal: connections, the
instrument catalogue, trades, order books, clusters and candles from a running
terminal on the same machine, over HTTP and WebSocket on `127.0.0.1`.

Node 22 or newer, ESM only, no runtime dependencies. Browsers are not
supported: the token travels in a header and the API refuses requests that
carry an `Origin`.

## Install

```bash
npm install @spectre-trade/terminal
```

## Before you start

1. In the terminal, open **Settings App → General** and switch **Local API** on.
2. Press **Copy token** and put it into the `SPECTRE_LOCAL_API_TOKEN`
   environment variable. The token is a secret: it grants the same read access
   the terminal window has.

## Quick start

```ts
import { Terminal } from "@spectre-trade/terminal";

const terminal = await Terminal.discover(); // port from instance.json, token from SPECTRE_LOCAL_API_TOKEN

const { data: connections } = await terminal.connections();
console.log(connections.map((c) => `${c.id} ${c.exchange}:${c.market} ${c.status.state}`));

const snapshot = await terminal.snapshot("binance:futures:BTCUSDT");
console.log(snapshot.best_bid, snapshot.best_ask);

const book = await terminal.orderbook("binance:futures:BTCUSDT", { depth: 10 });
console.log(book.bids[0], book.asks[0]);
```

Live data over the stream:

```ts
const stream = await terminal.stream();
await stream.subscribe({ topic: "trades", instrument: "binance:futures:BTCUSDT" });
await stream.subscribe({ topic: "book.top", instrument: "binance:futures:BTCUSDT", params: { depth: 5, interval_ms: 200 } });

for await (const frame of stream) {
  if (frame.type === "event" && frame.topic === "trades") {
    for (const trade of frame.data) console.log(trade.side, trade.qty, trade.price);
  }
}
```

Every operation of the contract has a method: `meta`, `health`,
`connections`, `connection`, `instruments` / `iterInstruments`, `intervals`,
`candles`, `trades`, `snapshot`, `orderbook`, `clusters`, `stream`. Option
names are camelCase; response fields keep the wire names from the contract.

## Money and time

Prices and sizes are decimal **strings** and stay strings (`type Decimal =
string`); bring your own decimal library, `Number` would lose precision.
Timestamps are integer UTC milliseconds.

## Errors

Everything thrown extends `SpectreTerminalError`: `ApiError` (`code`,
`status`), `TerminalUnreachableError`, `TokenMissingError`,
`LocalApiDisabledError`, `IncompatibleTerminalError`, `StreamRequestError`,
`StreamClosedError`. No error ever carries the token.

## Examples

[`examples/`](examples/) are runnable from a checkout without a build
(`node examples/snapshot.ts binance:futures:BTCUSDT`); `examples/smoke.ts`
calls every operation once against a running terminal.

## Development

```bash
npm ci
npm run typecheck
npm test
npm run build
```

Tests run against the fixtures in [`../contract/fixtures`](../contract/fixtures)
and fake servers; no terminal is needed.

## Documentation

Guides live in [`../docs`](../docs/); the authoritative API description is
[`../contract/contract-v1.md`](../contract/contract-v1.md).
