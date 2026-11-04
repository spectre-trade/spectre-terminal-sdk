# Spectre Terminal SDK

Clients for the **Local API** of [Spectre Terminal](https://spectre.trade):
read connections, the instrument catalogue, trades, order books, clusters,
candles and the account from a running terminal on the same machine, and
trade through it, over HTTP and WebSocket on `127.0.0.1`.

> **Status: pre-release.** The Local API ships with the next terminal
> release. Until then this repository is private and the packages are not
> published.

| Package | Language | Install | Requires |
| --- | --- | --- | --- |
| `spectre-terminal` | Python | `pip install spectre-terminal` | Python 3.10+ |
| `@spectre-trade/terminal` | TypeScript / JavaScript | `npm install @spectre-trade/terminal` | Node 22+ |
| `spectre-terminal-mcp` | MCP server for AI agents | `pip install spectre-terminal-mcp` | Python 3.10+ |

## Before you start

1. Open the terminal's **Settings App → General** and switch **Local API** on.
2. Press **Copy token** and keep it in the `SPECTRE_LOCAL_API_TOKEN`
   environment variable. The token is a secret: it grants everything the
   terminal window can do, including placing orders.

The clients find the port on their own (`instance.json` next to the
terminal's database, default `48180`). See [docs/discovery.md](docs/discovery.md).

## Quick start

### Python

```python
from spectre_terminal import Terminal

terminal = Terminal.discover()          # port from instance.json, token from SPECTRE_LOCAL_API_TOKEN

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

### TypeScript

```ts
import { Terminal } from "@spectre-trade/terminal";

const terminal = await Terminal.discover();

const { data: connections } = await terminal.connections();
console.log(connections.map((c) => `${c.id} ${c.exchange}:${c.market} ${c.status.state}`));

const snapshot = await terminal.snapshot("binance:futures:BTCUSDT");
console.log(snapshot.best_bid, snapshot.best_ask);

const stream = await terminal.stream();
await stream.subscribe({ topic: "trades", instrument: "binance:futures:BTCUSDT" });
for await (const frame of stream) {
  console.log(frame);
}
```

More runnable examples: [`python/examples/`](python/examples/),
[`typescript/examples/`](typescript/examples/).

### AI agents

```bash
pip install spectre-terminal-mcp
claude mcp add spectre-terminal -e SPECTRE_LOCAL_API_TOKEN=spt_… -- spectre-terminal-mcp
```

Seven read-only tools — status, instrument lookup, snapshot, order book
top, trades summary, clusters, candles — shaped for a model's context. See
[docs/mcp.md](docs/mcp.md).

## Documentation

- [Getting started](docs/getting-started.md) — enable the API, get a token, first request
- [Discovery](docs/discovery.md) — where the port and the token come from
- [Authentication](docs/authentication.md) — token, scopes, `401`/`403`, reissue
- [Market data](docs/market-data.md) — catalogue, candles, snapshot, order book, clusters
- [Account](docs/account.md) — orders, positions, balances, fills, and their stream topics
- [Trading](docs/trading.md) — placing and cancelling orders, closing positions
- [Workspace](docs/workspace.md) — windows, tabs, stacks and charts: reading the layout, opening and closing
- [Settings](docs/settings.md) — the settings table, a stack's resolved settings, writing as the Settings App does
- [Streaming](docs/streaming.md) — `/v1/stream`: subscriptions, gaps, conflation, close codes
- [Errors](docs/errors.md) — the error envelope and every code
- [Compatibility](docs/compatibility.md) — terminal × API × SDK matrix
- [MCP](docs/mcp.md) — the MCP server for Claude Code, Claude Desktop, Cursor
- [Contract v1](contract/contract-v1.md) — the authoritative description of the API,
  copied verbatim from the terminal repository

## Money and time

Prices and sizes are decimal **strings** on the wire and stay exact in the
clients: `decimal.Decimal` in Python, `string` in TypeScript (bring your own
decimal library; `Number` would lose precision). Timestamps are integer UTC
milliseconds.

## Compatibility

The clients talk to API **v1**. Every client checks `/v1/meta` on connect and
fails with a clear error when the terminal is older than it supports. Unknown
fields in responses are ignored, so a newer terminal keeps working with an
older client. See [docs/compatibility.md](docs/compatibility.md).

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for the layout, the tests and how the
contract copy is updated, and [SECURITY.md](SECURITY.md) for reporting a
vulnerability. The decisions behind this repository are summarised in
[CONTEXT.md](CONTEXT.md).

## License

[MIT](LICENSE).
