# MCP server

`spectre-terminal-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io)
server that lets an AI agent — Claude Code, Claude Desktop, Cursor, any MCP
client — read what the terminal sees. It is a thin package on top of the
Python client: stdio transport, read-only, no state of its own. Source:
[`mcp/`](../mcp/).

## Setup

```bash
pip install spectre-terminal-mcp
```

Switch the Local API on in the terminal (**Settings App → General → Local
API**) and copy the token. Then register the server with your client.

Claude Code:

```bash
claude mcp add spectre-terminal -e SPECTRE_LOCAL_API_TOKEN=spt_… -- spectre-terminal-mcp
```

Claude Desktop (`claude_desktop_config.json`), Cursor and other clients that
take a JSON config:

```json
{
  "mcpServers": {
    "spectre-terminal": {
      "command": "spectre-terminal-mcp",
      "env": { "SPECTRE_LOCAL_API_TOKEN": "spt_…" }
    }
  }
}
```

The server finds the port through the terminal's `instance.json` like the
clients do, and reads the token from the environment only. It starts even
when the terminal is not running: the first tool call then answers
`terminal_unreachable`, and the next call discovers the terminal again.

## Tools

Tools are designed for a model, not as a mirror of the HTTP endpoints: short
answers, one call per question, no thousand-row payloads in the context.
Every tool is read-only and idempotent and says so in its annotations, so
clients can call them without asking the user each time.

| Tool | Arguments | Answers |
| --- | --- | --- |
| `terminal_status` | — | terminal version, API health, stream topics, limits, every connection with `id`, `exchange`, `market`, `state` |
| `find_instrument` | `query`, optional `exchange`, `market`, `connection_id`, `limit` (10) | matching instruments best first: exact symbol, then exact base coin, then a base behind a numeric prefix (`1000PEPE`), then prefixes; USDT, USD and USDC quotes first |
| `market_snapshot` | `instrument`, optional `connection_id` | last price and side, best bid and ask with spread in price and bps, mark price, 24h change, volume, high and low |
| `order_book_top` | `instrument`, `depth` (10, ≤ 50), optional `connection_id` | top levels per side as `[price, size]`, bid and ask volume, `imbalance` = (bids − asks) / (bids + asks), spread, mid |
| `recent_trades_summary` | `instrument`, `limit` (200, ≤ 1000), optional `connection_id` | count by side, buy and sell volume, delta, VWAP, low and high, first and last price, time span, the largest print |
| `cluster_summary` | `instrument`, `buckets` (3, ≤ 10), `top_levels` (5, ≤ 20), optional `connection_id` | newest buckets at the terminal's interval: volume by side, delta, VWAP, range, trades, the busiest price levels |
| `candles` | `instrument`, `interval` (`1m`), `limit` (50, ≤ 500), optional `end`, `connection_id` | OHLCV bars as compact rows under a `columns` header, oldest first |

Every tool that takes an instrument names the connection it used in the
answer. Prices and sizes are decimal strings and should be kept as strings;
timestamps are UTC milliseconds with an ISO twin (`ts` and `time`).

### Cold instruments

An instrument that is not open in a terminal window is subscribed at the
exchange on the first call (up to 3 s) and held for 30 s afterwards.
`market_snapshot` waits once for the fields to fill instead of answering with
nulls; `cluster_summary` waits once for the history seed when the terminal
answers `not_active`. Bursts over the terminal's limits (50 instruments only
for the API, 5 new exchange subscriptions per second) come back as
`rate_limited`.

### Errors

A failed call is an MCP tool error whose text starts with a stable code and
continues with a human message:

| Code | Meaning |
| --- | --- |
| `terminal_unreachable` | the terminal is not running or its Local API is switched off |
| `token_missing` | `SPECTRE_LOCAL_API_TOKEN` is not set for the server |
| `local_api_disabled` | `instance.json` says the API is off |
| `incompatible_terminal` | the terminal speaks another API version |
| `unauthorized`, `not_found`, `invalid_request`, `unsupported`, `not_active`, `rate_limited`, `unavailable` | the contract's own codes, see [errors](errors.md) |

The token never appears in any message.

## What it does not do

- No writing: no orders, no settings, no windows. The API has no write path
  in v1, and a trading tool for an agent needs a product decision on
  confirmation first.
- No streaming: MCP tools are request and response. An agent that needs live
  data polls `market_snapshot`; a program that needs live data uses the SDK
  stream.
- No secrets: the server never sees exchange keys, and it reads the token
  from the environment only.

## Development

```bash
cd mcp
python3 -m venv .venv
.venv/bin/pip install -e ../python -e '.[dev]'
.venv/bin/pytest -q                                            # against the contract fixtures
SPECTRE_LOCAL_API_TOKEN=spt_… .venv/bin/python examples/smoke.py   # against a running terminal, over stdio
```
