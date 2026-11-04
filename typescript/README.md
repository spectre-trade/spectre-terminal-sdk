# @spectre-trade/terminal

TypeScript client for the **Local API** of Spectre Terminal: connections, the
instrument catalogue, trades, order books, clusters, candles and the account
from a running terminal on the same machine, plus placing and cancelling
orders with the same commands the window uses — over HTTP and WebSocket on
`127.0.0.1`.

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
   environment variable. The token is a secret: it grants everything the
   terminal window can do, reading the account and trading included — there
   is no separate write switch.

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
`candles`, `trades`, `snapshot`, `orderbook`, `clusters`, `accountOrders`,
`accountPositions`, `accountBalances`, `accountFills`, `placeOrder`,
`cancelOrder`, `cancelAll`, `closePosition`, `placeTrigger`, `cancelTrigger`,
`cancelAllTriggers`, `amendTrigger`, `leverage`, `setLeverage`,
`setMarginMode`, `workspace`, `workspaceWindow`, `openStack`, `openTab`,
`addStacks`, `openMultiview`,
`setStackInstrument`, `closeStack`, `closeTab`, `activateTab`, `closeWindow`,
`activateWindow`, `settings`, `orderbookSettings`, `updateSettings`, `stream`.
Option names are
camelCase; response fields keep the wire names from the contract.

## Account

Orders, positions, balances and fills of **one connection** (`account:read`):
every call takes a connection id, there is no default. Orders and positions
are the same cut the window shows; balances and fills are accumulated from
the moment the Local API was switched on.

```ts
const { data: orders, triggers } = await terminal.accountOrders(12);
const { data: positions } = await terminal.accountPositions(12);
const { data: balances } = await terminal.accountBalances(12);
const { data: fills } = await terminal.accountFills(12, { limit: 50, sinceTs: lastSeen });
```

The four `account.*` topics mirror the reads and are keyed by connection, not
instrument. Subscribing sends no snapshot: read first, then follow.

```ts
await stream.subscribe({ topic: "account.orders", connectionId: 12 });
await stream.subscribe({ topic: "account.fills", connectionId: 12 });

for await (const frame of stream) {
  if (frame.type !== "event") continue;
  if (frame.topic === "account.orders") console.log(frame.data.instrument, frame.data.orders.length); // the instrument's full list after a change
  if (frame.topic === "account.positions") console.log(frame.data.instrument, frame.data.position); // null on close
  if (frame.topic === "account.fills") console.log(frame.data.side, frame.data.qty, frame.data.price);
}
```

## Trading

`trading:write`: `placeOrder`, `cancelOrder`, `cancelAll` and `closePosition`
go through the same channel as the window's commands. The answer is
`Accepted` — accepted **by the terminal**, not by the exchange: watch
`account.orders` (or re-read `accountOrders`) for the order under `key`, as
the window watches its book. Money is passed as decimal strings and sent as
given; the terminal checks the venue's steps and minimums before sending.

```ts
const accepted = await terminal.placeOrder({
  connectionId: 12,
  instrument: "binance:futures:BTCUSDT",
  side: "buy",
  type: "limit",          // "market" takes no price
  price: "60000",
  size: "0.001",          // or notional: "60" — exactly one of the two
  postOnly: true,
  clientKey: "bot-42",    // idempotency: a repeat with the same key returns the previous answer
});
console.log(accepted.key); // the terminal's order key, "t-…"

await terminal.cancelOrder({ connectionId: 12, instrument: "binance:futures:BTCUSDT", orderId: accepted.key! });
await terminal.cancelAll({ connectionId: 12, instrument: "binance:futures:BTCUSDT" });
await terminal.closePosition({ connectionId: 12, instrument: "binance:futures:BTCUSDT" });
```

A connection that does not trade (disabled, read-only, without credentials)
answers `ApiError` with code `not_tradable` (409); a foreign instrument or a
refused size or price is `invalid_request` (400); more than
`meta.limits.commands_per_second` commands is `rate_limited` (429).
[`examples/place-and-cancel.ts`](examples/place-and-cancel.ts) places a resting
limit order far from the market and cancels it.

Trigger orders and leverage go the same way. A `stop_loss` or `take_profit`
is placed on the open position (its side and size come from the position);
a `stop` carries its own `side` and quote `notional`. Triggers are cancelled
and moved by the numeric `id` from `accountOrders().triggers`.

```ts
const sl = await terminal.placeTrigger({ connectionId: 12, instrument, kind: "stop_loss", triggerPrice: "59000" });
const trigger = (await terminal.accountOrders(12)).triggers.find((t) => t.client_id === sl.key)!;
await terminal.amendTrigger({ connectionId: 12, instrument, triggerId: trigger.id, kind: "stop_loss", triggerPrice: "58500" });
await terminal.cancelTrigger({ connectionId: 12, instrument, triggerId: trigger.id });

console.log(await terminal.leverage({ connectionId: 12, instrument })); // not_active until the terminal touched it
await terminal.setLeverage({ connectionId: 12, instrument, leverage: 20 });
await terminal.setMarginMode({ connectionId: 12, instrument, marginMode: "isolated" });
```

The layout — windows, tabs, stacks and charts — is read with `workspace()`
and changed with commands the window applies itself; ids are numbers of the
current run of the terminal, and the `workspace` stream topic sends the
whole layout on every change.

```ts
const opened = await terminal.openStack({ instrument, chart: true, activate: false });
await terminal.setStackInstrument({ widgetId: opened.stacks[0]!, instrument: "binance:futures:ETHUSDT" });
await terminal.closeTab({ windowId: opened.window_id!, tabId: opened.tab_id! });

const majors = await terminal.openTab({ items: [{ instrument, chart: true }, "binance:futures:ETHUSDT"], name: "Majors" });
await terminal.addStacks({ windowId: majors.window_id!, tabId: majors.tab_id!, items: ["binance:futures:SOLUSDT"] });
```

Settings are read as stored (`settings()`), resolved as a stack sees them
(`orderbookSettings()`) and written through the same path as the Settings
App after the terminal's catalogue checked every change (`updateSettings()`).

```ts
await terminal.updateSettings([{ category: "multiview", key: "stack_width_px", value: 300 }]);
```

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
calls every read operation once against a running terminal, the account
reads on the first connection that trades. `examples/account.ts` reads one
connection's account and follows its topics; `examples/place-and-cancel.ts`
is the only example that places an order.

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
