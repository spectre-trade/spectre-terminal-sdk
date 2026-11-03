"""Live check of the MCP server against a running terminal.

Spawns ``python -m spectre_terminal_mcp`` over stdio exactly as an MCP client
would, lists the tools and calls each one for ``INSTRUMENT``, printing one
``PASS``/``FAIL`` line per tool. Needs ``SPECTRE_LOCAL_API_TOKEN`` in the
environment; the token is passed to the child process and never printed.

    python examples/smoke.py [exchange:market:SYMBOL]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

INSTRUMENT = sys.argv[1] if len(sys.argv) > 1 else "binance:futures:ETHUSDT"

CALLS: list[tuple[str, dict[str, Any], str]] = [
    ("terminal_status", {}, "app_version"),
    ("find_instrument", {"query": INSTRUMENT.rsplit(":", 1)[-1][:3]}, "matches"),
    ("market_snapshot", {"instrument": INSTRUMENT}, "last_price"),
    ("order_book_top", {"instrument": INSTRUMENT, "depth": 5}, "imbalance"),
    ("recent_trades_summary", {"instrument": INSTRUMENT, "limit": 100}, "vwap"),
    ("cluster_summary", {"instrument": INSTRUMENT, "buckets": 2, "top_levels": 3}, "interval"),
    ("candles", {"instrument": INSTRUMENT, "interval": "1m", "limit": 5}, "rows"),
]


def brief(name: str, data: dict[str, Any]) -> str:
    if name == "terminal_status":
        return f"app {data['app_version']}, {len(data['connections'])} connections"
    if name == "find_instrument":
        first = data["matches"][0]["instrument"] if data["matches"] else "none"
        return f"{data['total_found']} found, first {first}"
    if name == "market_snapshot":
        return f"last {data['last_price']} bid {data['best_bid']} ask {data['best_ask']}"
    if name == "order_book_top":
        return f"spread {data['spread']} ({data['spread_bps']} bps), imbalance {data['imbalance']}"
    if name == "recent_trades_summary":
        return f"{data['count']} trades, delta {data.get('delta')}, vwap {data.get('vwap')}"
    if name == "cluster_summary":
        return f"{data['interval']}, {len(data['buckets'])} of {data['buckets_available']} buckets"
    if name == "candles":
        last_close = data["rows"][-1][5] if data["rows"] else "-"
        return f"{len(data['rows'])} rows, last close {last_close}"
    if name == "account_overview":
        return f"{len(data['balances'])} balances, {len(data['positions'])} positions"
    if name == "open_orders":
        return f"{len(data['orders'])} orders, {len(data['triggers'])} triggers"
    if name == "recent_fills":
        return f"{data['count']} fills"
    return json.dumps(data)[:80]


async def main() -> int:
    if not os.environ.get("SPECTRE_LOCAL_API_TOKEN"):
        print("FAIL setup: SPECTRE_LOCAL_API_TOKEN is not set")
        return 1
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "spectre_terminal_mcp"], env=dict(os.environ)
    )
    failures = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = sorted(tool.name for tool in listed.tools)
            print(f"PASS list_tools: {len(names)} tools: {', '.join(names)}")
            status = await session.call_tool("terminal_status", {})
            tradable = next(
                (
                    c["id"]
                    for c in (status.structured_content or {}).get("connections", [])
                    if c.get("enabled") and not c.get("read_only")
                ),
                None,
            )
            calls = list(CALLS)
            if tradable is None:
                print("SKIP account tools: no trading connection")
            else:
                calls += [
                    ("account_overview", {"connection_id": tradable}, "balances"),
                    ("open_orders", {"connection_id": tradable}, "orders"),
                    ("recent_fills", {"connection_id": tradable, "limit": 5}, "fills"),
                ]
            for name, arguments, key in calls:
                started = time.monotonic()
                result = await session.call_tool(name, arguments)
                elapsed = (time.monotonic() - started) * 1000
                if getattr(result, "is_error", False):
                    failures += 1
                    text = result.content[0].text if result.content else "?"
                    print(f"FAIL {name}: {text} ({elapsed:.0f} ms)")
                    continue
                data = result.structured_content or {}
                if key not in data:
                    failures += 1
                    print(f"FAIL {name}: no '{key}' in answer ({elapsed:.0f} ms)")
                    continue
                print(f"PASS {name}: {brief(name, data)} ({elapsed:.0f} ms)")
    print(f"{'ALL PASS' if failures == 0 else f'{failures} FAILED'} for {INSTRUMENT}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
