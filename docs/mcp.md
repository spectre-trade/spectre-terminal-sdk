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
| `account_overview` | `connection_id` | balances, open positions with PnL, and the count of open orders and triggers per instrument |
| `open_orders` | `connection_id`, optional `instrument` | open orders and trigger orders, the terminal's `key` and the exchange id for each |
| `recent_fills` | `connection_id`, `limit` (20, ≤ 200), optional `since_ts` | the latest fills, newest last, with a buy/sell volume total |
| `leverage` | `connection_id`, `instrument` | leverage, its maximum, the terminal's mode (`manual`, `max`, `smart`) and the margin mode of a futures instrument; `not_active` until the terminal touched the instrument |

Trading tools, **not** read-only (annotated `destructive_hint`, so an MCP
client may ask the user before each call):

| Tool | Arguments | Does |
| --- | --- | --- |
| `place_order` | `connection_id`, `instrument`, `side`, `type`, optional `price`, `size` or `notional`, `reduce_only`, `post_only`, `time_in_force`, `client_key` | places a limit or market order; answers with the terminal's order `key` |
| `cancel_order` | `connection_id`, `instrument`, `order_id` | cancels one order by terminal key or exchange id |
| `cancel_all_orders` | `connection_id`, `instrument` | cancels every order of the instrument |
| `close_position` | `connection_id`, `instrument` | closes the instrument's position the way the window does |
| `place_trigger` | `connection_id`, `instrument`, `kind`, `trigger_price`, `client_key`; for `stop`: `side`, `notional`, optional `rule` | a stop loss or take profit on the open position, or a stop; answers with the trigger's key |
| `cancel_trigger` | `connection_id`, `instrument`, `trigger_id` | cancels one trigger by the numeric id from `open_orders` |
| `amend_trigger` | `connection_id`, `instrument`, `trigger_id`, `kind`, `trigger_price`; for `stop`: `side`, optional `rule` | moves a trigger to a new price (cancel, then place) |
| `cancel_all_triggers` | `connection_id`, `instrument` | cancels every trigger of the instrument; plain orders stay |
| `set_leverage` | `connection_id`, `instrument`, `leverage` or `mode` (`max`, `smart`) | sets the leverage the way the window does |
| `set_margin_mode` | `connection_id`, `instrument`, `margin_mode` (`cross`, `isolated`) | sets the margin mode; refused by the exchange while a position is open |

Every trading answer is `accepted`, not filled: the exchange's outcome shows
up in `open_orders` and `recent_fills`. The model is told so in the tool
descriptions, and `place_order` requires `client_key` so that a retried call
never doubles an order.

Workspace tools — the layout the terminal shows. `workspace` is read-only;
the commands are annotated as destructive like trading:

| Tool | Arguments | Does |
| --- | --- | --- |
| `workspace` | — | every window with its tabs, stacks and charts, and the ids the commands take; ids change with every run of the terminal |
| `open_stack` | `instrument`, optional `connection_id`, `chart`, `target` (`new_tab`, `new_window`), `window_id`, `activate` | a stack in a new tab or window, with a chart if asked; answers the new ids |
| `open_tab` | `items` (each `instrument`, optional `connection_id`, `chart`), optional `name`, `target`, `window_id`, `activate` | one tab with several instruments, a column each, in a new tab or window |
| `add_stacks` | `window_id`, `tab_id`, `items` | the same columns added after the last column of an existing tab |
| `open_multiview` | `base`, optional `target`, `window_id`, `activate` | a coin on every venue of «Exchange layout», as the Multiview button |
| `set_stack_instrument` | `widget_id`, `instrument`, optional `connection_id` | another instrument in the stack and the charts that follow it |
| `close_stack` | `widget_id` | closes one stack |
| `close_tab`, `activate_tab` | `window_id`, `tab_id` | closes or selects a tab; the only tab of a window never closes |
| `close_window`, `activate_window` | `window_id` | closes a window or brings it to the front; the main window never closes |

Settings tools — `settings` and `orderbook_settings` are read-only,
`update_settings` is annotated as destructive:

| Tool | Arguments | Does |
| --- | --- | --- |
| `settings` | optional `scope`, `category`, `key`, `connection_id`, `instrument` | rows as stored, each with `writable` |
| `orderbook_settings` | `connection_id`, `instrument` | a stack's settings as the stack sees them, `resolved_from` on every key |
| `update_settings` | `changes`: a list of `{category, key, value, scope?, instrument?, connection_id?}` | writes through the Settings App's path after the terminal checked every change; refuses by index, leverage is refused |

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

- No settings and no windows. Of trading, no grid moves and no MOEX. There
  is no confirmation inside the server: the Local API toggle in the terminal
  is the consent and the kill switch (product decision); MCP clients that
  confirm destructive tools do so on their own.
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
