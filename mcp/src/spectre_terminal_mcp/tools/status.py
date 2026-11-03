"""``terminal_status``: is the terminal there, and what is connected."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from ..summaries import status_summary
from ..terminal import TerminalProvider

__all__ = ["register"]


def register(server: MCPServer, provider: TerminalProvider) -> None:
    from . import READ_ONLY

    @server.tool(name="terminal_status", annotations=READ_ONLY)
    def terminal_status() -> dict[str, Any]:
        """Check that Spectre Terminal is running and list its exchange connections.

        Returns the terminal version, API health, the stream topics it
        serves, the limits that matter for an agent, and every connection
        with its id, exchange, market and state. Call this first when a
        session starts or when another tool reports the terminal unreachable.
        """
        with provider.call() as terminal:
            return status_summary(terminal.meta(), terminal.health(), terminal.connections())
