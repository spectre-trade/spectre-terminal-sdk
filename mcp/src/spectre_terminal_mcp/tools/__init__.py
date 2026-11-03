"""Tool registration: one module per family, one function per tool.

Every tool is read-only and idempotent, and says so in its annotations, so an
MCP client can call it without asking the user for confirmation.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from ..terminal import TerminalProvider
from . import instruments, market, status

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
