# spectre-terminal-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an AI agent — Claude
Code, Claude Desktop, Cursor, any MCP client — read market data from a
running [Spectre Terminal](https://spectre.trade) on the same machine, and
trade through it. Thin, stdio; built on the `spectre-terminal` Python client.

```bash
pip install spectre-terminal-mcp
```

## Setup

Switch the Local API on in the terminal (**Settings App → General → Local
API**) and copy the token. Then register the server with your client:

Claude Code:

```bash
claude mcp add spectre-terminal -e SPECTRE_LOCAL_API_TOKEN=spt_… -- spectre-terminal-mcp
```

Claude Desktop (`claude_desktop_config.json`), Cursor and others:

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

The server finds the port through the terminal's `instance.json` and reads
the token from the environment only. It starts even when the terminal is not
running; the first tool call then answers `terminal_unreachable`.

## Tools

| Tool | Answers |
| --- | --- |
| `terminal_status` | version, health, stream topics, every connection with id, exchange, market, state |
| `find_instrument` | the exact `exchange:market:symbol` for a coin or symbol, best match first |
| `market_snapshot` | last price, best bid and ask with spread, mark, 24h change and volume |
| `order_book_top` | top N levels per side, volumes, imbalance |
| `recent_trades_summary` | buy and sell volume, delta, VWAP, range, largest print over the last N trades |
| `cluster_summary` | the newest buckets: volume by side, delta, VWAP, the busiest price levels |
| `candles` | OHLCV rows for an interval |
| `account_overview` | balances, positions with PnL, open order counts of one connection |
| `open_orders` | open orders and triggers with the terminal's `key` and the exchange id |
| `recent_fills` | the latest fills with buy and sell volume totals |
| `place_order` | places a limit or market order; needs a `client_key`; answers "accepted" |
| `cancel_order` | cancels one order by key or exchange id |
| `cancel_all_orders` | cancels every order of an instrument |
| `close_position` | closes a position the way the window does |
| `leverage` | leverage, its maximum, the terminal's mode and the margin mode of a futures instrument |
| `place_trigger` | places a stop loss or take profit on the open position, or a stop; needs a `client_key` |
| `cancel_trigger`, `amend_trigger`, `cancel_all_triggers` | cancel, move or clear trigger orders by their numeric id |
| `set_leverage`, `set_margin_mode` | leverage (a number, or `max`/`smart`) and `cross`/`isolated` |
| `workspace` | every window with its tabs, stacks and charts; the ids the commands below take |
| `open_stack`, `open_multiview` | a stack (with a chart if asked) in a new tab or window; a coin on every venue of «Exchange layout» |
| `set_stack_instrument`, `close_stack` | re-point or close one stack by `widget_id` |
| `close_tab`, `activate_tab`, `close_window`, `activate_window` | tabs by window and tab id, windows by id; the main window and a window's only tab never close |
| `settings`, `orderbook_settings` | settings rows as stored; a stack's settings resolved the way the stack sees them, with the level each came from |
| `update_settings` | writes settings through the Settings App's own path after the terminal checked each change |

Read tools are read-only and idempotent and say so in their annotations; the
ten trading tools, the eight workspace commands and `update_settings` are
annotated as destructive, so an MCP client may ask the user before each call. Trading answers mean "accepted by the terminal", not
"filled": the outcome is read from `open_orders` and `recent_fills`.
Prices and sizes are decimal strings; times are UTC milliseconds plus an ISO
twin. Errors start with a stable code (`unauthorized`, `not_found`,
`unsupported`, `rate_limited`, `terminal_unreachable`, …) followed by a
human message. See [docs/mcp.md](../docs/mcp.md).

## Development

```bash
cd mcp
python3 -m venv .venv
.venv/bin/pip install -e ../python -e '.[dev]'
.venv/bin/pytest -q
SPECTRE_LOCAL_API_TOKEN=spt_… .venv/bin/python examples/smoke.py   # against a running terminal
```
