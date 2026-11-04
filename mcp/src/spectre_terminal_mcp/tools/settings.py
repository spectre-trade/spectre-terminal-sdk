"""Settings tools: read the terminal's settings and write them as the Settings App does.

``settings`` and ``orderbook_settings`` are read-only. ``update_settings``
writes through the same path as the terminal's own settings window — the
same row, the same window event, the same service caches — after the
terminal checked every change against its catalogue, so a wrong key, type
or shape is refused before anything is written. Annotated destructive like
the trading tools: an MCP client may confirm with the user first.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from spectre_terminal.models import OrderbookSettings, SettingChange, SettingRow

from ..terminal import TerminalProvider

__all__ = ["SETTINGS_WRITE", "register"]

SETTINGS_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

_INSTRUMENT = Field(description="Instrument address exchange:market:symbol")


def row_dict(row: SettingRow) -> dict[str, Any]:
    data: dict[str, Any] = {
        "scope": row.scope,
        "scope_id": row.scope_id,
        "connection_id": row.connection_id,
        "category": row.category,
        "key": row.key,
        "value": row.value,
    }
    if row.writable is not None:
        data["writable"] = row.writable
    return data


def orderbook_dict(book: OrderbookSettings) -> dict[str, Any]:
    return {
        "connection_id": book.connection_id,
        "instrument": book.instrument,
        "data": {
            category: {
                key: {
                    "value": item.value,
                    "resolved_from": item.resolved_from,
                    "writable": item.writable,
                }
                for key, item in keys.items()
            }
            for category, keys in book.data.items()
        },
        "note": "resolved_from names the level the value came from: instrument, connection, "
        "app_instrument or global",
    }


def register(server: MCPServer, provider: TerminalProvider) -> None:
    @server.tool(name="settings", annotations=READ_ONLY)
    def settings(
        scope: Annotated[
            str | None, Field(default=None, description="global (default) or order_book")
        ] = None,
        category: Annotated[str | None, Field(default=None, description="Category filter")] = None,
        key: Annotated[str | None, Field(default=None, description="Key filter")] = None,
        connection_id: Annotated[
            int | None, Field(default=None, description="The connection's rows; else app-wide")
        ] = None,
        instrument: Annotated[
            str | None, Field(default=None, description="The pair's rows (scope order_book)")
        ] = None,
    ) -> dict[str, Any]:
        """Settings rows as stored, with whether each is writable through update_settings.

        Without arguments: the terminal-wide rows (multiview, chart, sounds,
        hotkeys, …). The settings of one stack, resolved the way the stack
        sees them, are ``orderbook_settings``.
        """
        with provider.call() as terminal:
            rows = terminal.settings(
                scope=scope,
                category=category,
                key=key,
                connection_id=connection_id,
                instrument=instrument,
            )
        return {"data": [row_dict(row) for row in rows.data]}

    @server.tool(name="orderbook_settings", annotations=READ_ONLY)
    def orderbook_settings(
        connection_id: Annotated[int, Field(description="Connection id from terminal_status")],
        instrument: Annotated[str, _INSTRUMENT],
    ) -> dict[str, Any]:
        """The stack settings of one instrument as its stack on the connection sees them.

        Every key names the level it was resolved from: the pair's own row,
        the connection's default, the pair's row without a connection, or
        the global default.
        """
        with provider.call() as terminal:
            return orderbook_dict(terminal.orderbook_settings(connection_id, instrument))

    @server.tool(name="update_settings", annotations=SETTINGS_WRITE)
    def update_settings(
        changes: Annotated[
            list[dict[str, Any]],
            Field(
                description=(
                    "Changes in order; each has category, key, value and optionally scope "
                    "(global or order_book), instrument and connection_id"
                )
            ),
        ],
    ) -> dict[str, Any]:
        """Write settings the way the terminal's settings window does.

        A change with ``instrument`` writes the pair's row; ``scope``
        ``order_book`` with ``connection_id`` the connection's default; neither
        the global default. Every change is checked first — unknown key,
        wrong type, out of range, wrong shape — and refused by index with
        nothing written; leverage is refused (use ``set_leverage``). The
        first failed change stops the list; earlier ones stay applied.
        """
        parsed = []
        for change in changes:
            parsed.append(
                SettingChange(
                    category=str(change["category"]),
                    key=str(change["key"]),
                    value=change.get("value"),
                    scope=change.get("scope"),
                    instrument=change.get("instrument"),
                    connection_id=change.get("connection_id"),
                )
            )
        with provider.call() as terminal:
            applied = terminal.update_settings(parsed)
        return {"applied": applied.applied}
