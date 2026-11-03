"""The MCP server: one :class:`MCPServer` with the read-only tools registered.

``spectre-terminal-mcp`` (or ``python -m spectre_terminal_mcp``) runs it over
stdio, which is what Claude Code, Claude Desktop and Cursor expect. Nothing
is logged to stdout: stdout is the protocol channel.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import __version__
from .terminal import TerminalProvider
from .tools import register_tools

__all__ = ["build_server", "main"]

INSTRUCTIONS = """\
Read-only view of a running Spectre Terminal on this machine: exchange
connections, instrument catalogue, last price and top of book, recent trades,
volume clusters and candles — the same data the trader sees in the terminal.

Instruments are addressed as "exchange:market:symbol" in the exchange's own
spelling, for example "binance:futures:BTCUSDT" or "okx:futures:ETH-USDT-SWAP".
When unsure of the spelling, call find_instrument first. Prices and sizes are
decimal strings; keep them as strings. Times are UTC milliseconds with an ISO
twin. Nothing here places orders or changes the terminal.
"""


def build_server(provider: TerminalProvider | None = None) -> MCPServer:
    """Assemble the server; ``provider`` is injected by tests, discovered otherwise."""
    server = MCPServer(
        name="spectre-terminal",
        title="Spectre Terminal",
        version=__version__,
        instructions=INSTRUCTIONS,
    )
    register_tools(server, provider or TerminalProvider())
    return server


def main() -> None:
    """Console entry point: serve over stdio until the client goes away."""
    build_server().run("stdio")
