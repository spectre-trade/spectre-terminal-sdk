# MCP server

> **Planned.** The package `spectre-terminal-mcp` is not published yet. This
> page records the design so that the first version is built against it.

`spectre-terminal-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io)
server that lets an AI agent — Claude Code, Claude Desktop, Cursor, any MCP
client — read what the terminal sees. It is a thin package on top of the
Python client: stdio transport, read-only, no state of its own.

## Setup (planned)

```bash
pip install spectre-terminal-mcp
```

Claude Code:

```bash
claude mcp add spectre-terminal -e SPECTRE_LOCAL_API_TOKEN=spt_… -- spectre-terminal-mcp
```

Claude Desktop (`claude_desktop_config.json`):

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

The server finds the port through `instance.json` like the clients do.

## Tools

Tools are designed for a model, not as a mirror of the HTTP endpoints: short
answers, one call per question, no thousand-row payloads in the context.

| Tool | Answers | Source |
| --- | --- | --- |
| `terminal_status` | is the terminal running, which version, which connections are enabled | `/v1/meta`, `/v1/connections` |
| `find_instrument` | the exact instrument address for a coin on a venue and market | `/v1/instruments` with `q` |
| `market_snapshot` | last price, best bid and ask, 24h change and volume, mark price | `/v1/market/snapshot` |
| `order_book_top` | the top N levels and the imbalance between them | `/v1/market/orderbook` |
| `recent_trades_summary` | buy and sell volume, VWAP, number of trades over the last N trades or seconds | `/v1/market/trades`, aggregated locally |
| `cluster_summary` | the last buckets: volume by side, VWAP, the price levels with the most volume | `/v1/market/clusters`, trimmed |
| `candles` | OHLCV for an interval and a bounded number of bars | `/v1/market/candles` |

Every tool takes an instrument address and an optional `connection_id`, and
every answer names the connection it used. Errors come back as the contract's
error codes with the human message.

## What it will not do

- No writing: no orders, no settings, no windows. The API has no write path
  in v1, and a trading tool for an agent needs a product decision on
  confirmation first.
- No streaming: MCP tools are request and response. An agent that needs live
  data polls `market_snapshot`; a program that needs live data uses the SDK
  stream.
- No secrets: the server never sees exchange keys, and it reads the token
  from the environment only.
