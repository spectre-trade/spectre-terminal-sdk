"""Tool registration: one module per family, one function per tool.

Read tools are read-only and idempotent and say so in their annotations;
the trading tools say the opposite (`tools/trading.py`), so an MCP client
can tell them apart and confirm with the user if it wants to.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from ..terminal import TerminalProvider
from . import account, instruments, market, status, trading

__all__ = ["READ_ONLY", "register_tools"]

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def register_tools(server: MCPServer, provider: TerminalProvider) -> None:
    """Register every tool on ``server`` against ``provider``."""
    status.register(server, provider)
    instruments.register(server, provider)
    market.register(server, provider)
    account.register(server, provider)
    trading.register(server, provider)
