"""Account tools: overview, open orders, recent fills — one connection each."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ..summaries import account_overview, fills_summary, open_orders_summary
from ..terminal import TerminalProvider

__all__ = ["register"]

_CONNECTION = Field(
    description="Connection id from terminal_status (required: one account at a time)"
)


def register(server: MCPServer, provider: TerminalProvider) -> None:
    from . import READ_ONLY

    @server.tool(name="account_overview", annotations=READ_ONLY)
    def account_overview_tool(
        connection_id: Annotated[int, _CONNECTION],
    ) -> dict[str, Any]:
        """Balances, open positions with PnL and how many orders are open, for one connection.

        The cheapest way to answer "what is this account holding". Balances
        and fills are what the terminal has accumulated since its API was
        switched on; positions and orders are live state.
        """
        with provider.call() as terminal:
            balances = terminal.account_balances(connection_id)
            positions = terminal.account_positions(connection_id)
            orders = terminal.account_orders(connection_id)
        return account_overview(balances, positions, orders)

    @server.tool(name="open_orders", annotations=READ_ONLY)
    def open_orders(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[
            str | None,
            Field(description="Only this instrument (exchange:market:symbol); all when omitted"),
        ] = None,
    ) -> dict[str, Any]:
        """Open orders and trigger orders of a connection, with the key and exchange id of each.

        Use the ``key`` (``t-…``) to cancel an order placed through the API,
        and to recognise it after ``place_order``.
        """
        with provider.call() as terminal:
            orders = terminal.account_orders(connection_id)
        return open_orders_summary(orders, instrument)

    @server.tool(name="recent_fills", annotations=READ_ONLY)
    def recent_fills(
        connection_id: Annotated[int, _CONNECTION],
        limit: Annotated[int, Field(ge=1, le=200, description="Newest fills to return")] = 20,
        since_ts: Annotated[
            int | None, Field(description="Only fills at or after this UTC millisecond timestamp")
        ] = None,
    ) -> dict[str, Any]:
        """The latest fills of a connection, oldest first, with buy and sell volume totals.

        Fills are kept by the terminal since its API was switched on (the
        last 1000 per connection); older history is not available here.
        """
        with provider.call() as terminal:
            fills = terminal.account_fills(connection_id, limit=limit, since_ts=since_ts)
        return fills_summary(fills)
