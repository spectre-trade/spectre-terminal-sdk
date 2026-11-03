"""Trading tools: place, cancel, cancel all, close — the same commands the window sends.

These are the only tools that change anything, and they say so in their
annotations (``destructive_hint``, not read-only), so an MCP client may
confirm with the user before each call. Inside the server there is no
confirmation: the Local API toggle in the terminal is the consent and the
kill switch (product decision).

Every answer is "accepted by the terminal", never "filled": the exchange's
outcome shows up in ``open_orders`` and ``recent_fills``. ``place_order``
requires a ``client_key`` so that a retried tool call cannot double an order.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from spectre_terminal.models import Accepted

from ..terminal import TerminalProvider

__all__ = ["TRADING", "register"]

TRADING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)

_CONNECTION = Field(description="Connection id from terminal_status; it must trade (keys, enabled)")
_INSTRUMENT = Field(description="Instrument address exchange:market:symbol")

ACCEPTED_NOTE = (
    "accepted by the terminal, not by the exchange: check open_orders and recent_fills "
    "for the outcome"
)


def accepted_dict(accepted: Accepted) -> dict[str, Any]:
    return {
        "accepted": accepted.accepted,
        "operation_id": accepted.operation_id,
        "key": accepted.key,
        "connection_id": accepted.connection_id,
        "instrument": accepted.instrument,
        "note": ACCEPTED_NOTE,
    }


def register(server: MCPServer, provider: TerminalProvider) -> None:
    @server.tool(name="place_order", annotations=TRADING)
    def place_order(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
        side: Annotated[str, Field(description="buy or sell")],
        order_type: Annotated[str, Field(description="limit (needs price) or market (no price)")],
        client_key: Annotated[
            str,
            Field(
                description=(
                    "Your idempotency key for this intent, e.g. 'rebalance-2026-11-03-1'. "
                    "A retry with the same key returns the previous answer and places nothing."
                )
            ),
        ],
        price: Annotated[str | None, Field(description="Limit price as a decimal string")] = None,
        size: Annotated[
            str | None, Field(description="Amount in the base coin as a decimal string")
        ] = None,
        notional: Annotated[
            str | None, Field(description="Amount in the quote currency as a decimal string")
        ] = None,
        reduce_only: Annotated[bool, Field(description="Only reduce an existing position")] = False,
        post_only: Annotated[bool, Field(description="Reject instead of taking liquidity")] = False,
        time_in_force: Annotated[
            str | None,
            Field(description="gtc, ioc, fok or post_only; the venue's default when omitted"),
        ] = None,
    ) -> dict[str, Any]:
        """Place a limit or market order on a connection. Answers "accepted", not "filled".

        Give exactly one of ``size`` (base coin) or ``notional`` (quote
        amount). Prices and amounts are decimal strings; the terminal checks
        the venue's minimums and steps before sending and refuses with the
        reason. Watch ``open_orders`` for the returned ``key``.
        """
        with provider.call() as terminal:
            accepted = terminal.place_order(
                connection_id,
                instrument,
                side=side,
                order_type=order_type,
                price=price,
                size=size,
                notional=notional,
                reduce_only=reduce_only,
                post_only=post_only,
                time_in_force=time_in_force,
                client_key=client_key,
            )
        return accepted_dict(accepted)

    @server.tool(name="cancel_order", annotations=TRADING)
    def cancel_order(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
        order_id: Annotated[
            str,
            Field(description="The terminal key (t-…) from open_orders or the exchange's order id"),
        ],
    ) -> dict[str, Any]:
        """Cancel one order by the terminal's key or the exchange's id. Answers "accepted"."""
        with provider.call() as terminal:
            accepted = terminal.cancel_order(connection_id, instrument, order_id)
        return accepted_dict(accepted)

    @server.tool(name="cancel_all_orders", annotations=TRADING)
    def cancel_all_orders(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
    ) -> dict[str, Any]:
        """Cancel every open order of the instrument on this connection. Answers "accepted"."""
        with provider.call() as terminal:
            accepted = terminal.cancel_all(connection_id, instrument)
        return accepted_dict(accepted)

    @server.tool(name="close_position", annotations=TRADING)
    def close_position(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
    ) -> dict[str, Any]:
        """Close the instrument's position the way the terminal window does. Answers "accepted".

        Futures: a market order for the whole position. Spot: cancel all and
        sell as one atomic command. Refused when there is no open position.
        """
        with provider.call() as terminal:
            accepted = terminal.close_position(connection_id, instrument)
        return accepted_dict(accepted)
