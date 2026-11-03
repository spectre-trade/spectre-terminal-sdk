"""Trading tools: orders, triggers, position close, leverage — the same commands the window sends.

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

    @server.tool(name="place_trigger", annotations=TRADING)
    def place_trigger(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
        kind: Annotated[
            str,
            Field(
                description=(
                    "stop_loss or take_profit (placed on the open position: its side, size and "
                    "rule come from the position) or stop (your own side and notional)"
                )
            ),
        ],
        trigger_price: Annotated[str, Field(description="Trigger price as a decimal string")],
        client_key: Annotated[
            str,
            Field(
                description=(
                    "Your idempotency key for this intent. A retry with the same key returns "
                    "the previous answer and places nothing."
                )
            ),
        ],
        side: Annotated[str | None, Field(description="stop only: buy or sell")] = None,
        notional: Annotated[
            str | None, Field(description="stop only: amount in the quote currency, decimal string")
        ] = None,
        rule: Annotated[
            str | None,
            Field(
                description=(
                    "stop only: price_above_or_equal or price_below_or_equal; omitted means "
                    "above the market for a buy, below for a sell"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Place a stop loss, take profit or stop the way the window does. Answers "accepted".

        The returned ``key`` (``sl_…``, ``tp_…``, ``stop_…``) shows up as
        ``client_id`` of the trigger in ``open_orders``; cancel or move it by
        the numeric ``id`` from there. Refused without an open position for
        ``stop_loss``/``take_profit``, and with ``unsupported`` on a venue
        without trigger orders in the terminal.
        """
        with provider.call() as terminal:
            accepted = terminal.place_trigger(
                connection_id,
                instrument,
                kind=kind,
                trigger_price=trigger_price,
                side=side,
                notional=notional,
                rule=rule,
                client_key=client_key,
            )
        return accepted_dict(accepted)

    @server.tool(name="cancel_trigger", annotations=TRADING)
    def cancel_trigger(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
        trigger_id: Annotated[
            str, Field(description="The numeric id of the trigger from open_orders")
        ],
    ) -> dict[str, Any]:
        """Cancel one trigger order by its numeric id from ``open_orders``. Answers "accepted"."""
        with provider.call() as terminal:
            accepted = terminal.cancel_trigger(connection_id, instrument, trigger_id)
        return accepted_dict(accepted)

    @server.tool(name="cancel_all_triggers", annotations=TRADING)
    def cancel_all_triggers(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
    ) -> dict[str, Any]:
        """Cancel every trigger order of the instrument; plain orders stay. Answers "accepted"."""
        with provider.call() as terminal:
            accepted = terminal.cancel_all_triggers(connection_id, instrument)
        return accepted_dict(accepted)

    @server.tool(name="amend_trigger", annotations=TRADING)
    def amend_trigger(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
        trigger_id: Annotated[
            str, Field(description="The numeric id of the trigger from open_orders")
        ],
        kind: Annotated[
            str, Field(description="stop_loss, take_profit or stop — the trigger's type")
        ],
        trigger_price: Annotated[str, Field(description="New trigger price as a decimal string")],
        side: Annotated[str | None, Field(description="stop only: buy or sell")] = None,
        rule: Annotated[
            str | None,
            Field(description="stop only: price_above_or_equal or price_below_or_equal"),
        ] = None,
    ) -> dict[str, Any]:
        """Move a trigger to a new price (cancel, then place). Answers "accepted"."""
        with provider.call() as terminal:
            accepted = terminal.amend_trigger(
                connection_id,
                instrument,
                trigger_id,
                kind=kind,
                trigger_price=trigger_price,
                side=side,
                rule=rule,
            )
        return accepted_dict(accepted)

    @server.tool(name="set_leverage", annotations=TRADING)
    def set_leverage(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
        leverage: Annotated[
            int | None,
            Field(description="Leverage as an integer of at least 1; or give mode", ge=1),
        ] = None,
        mode: Annotated[
            str | None, Field(description="max or smart (the terminal's modes); or give leverage")
        ] = None,
    ) -> dict[str, Any]:
        """Set the leverage of a futures instrument the way the window does. Answers "accepted".

        Exactly one of ``leverage`` and ``mode``. Read the applied value with
        ``leverage`` after the exchange answered.
        """
        with provider.call() as terminal:
            accepted = terminal.set_leverage(
                connection_id, instrument, leverage=leverage, mode=mode
            )
        return accepted_dict(accepted)

    @server.tool(name="set_margin_mode", annotations=TRADING)
    def set_margin_mode(
        connection_id: Annotated[int, _CONNECTION],
        instrument: Annotated[str, _INSTRUMENT],
        margin_mode: Annotated[str, Field(description="cross or isolated")],
    ) -> dict[str, Any]:
        """Set the margin mode of a futures instrument. Answers "accepted".

        The exchange refuses the change while a position is open, as in the
        window; the accepted answer does not know that yet.
        """
        with provider.call() as terminal:
            accepted = terminal.set_margin_mode(connection_id, instrument, margin_mode)
        return accepted_dict(accepted)
