"""Workspace tools: what the terminal shows and the commands that change it.

``workspace`` is read-only: the layout the window publishes at every
structural change. The rest open, close and select tabs, stacks and windows
through the same paths a click takes, with no confirmation inside the
terminal (the Local API toggle is the consent), so they are annotated
``destructive_hint`` like the trading tools. Ids are internal numbers of the
current run: read them from ``workspace`` first, never from memory.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from spectre_terminal.models import Window, Workspace, WorkspaceOutcome

from ..terminal import TerminalProvider

__all__ = ["WORKSPACE_WRITE", "register"]

WORKSPACE_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

_WINDOW = Field(description="Window id from the workspace tool")
_TAB = Field(description="Tab id from the workspace tool; tabs are numbered per window")
_WIDGET = Field(description="Stack widget_id from the workspace tool")
_TARGET = Field(
    default="new_tab",
    description="new_tab (in window_id, or the focused window) or new_window",
)
_ACTIVATE = Field(
    default=True,
    description="False opens the tab in the background; a new window always takes focus",
)


def window_dict(window: Window) -> dict[str, Any]:
    return {
        "id": window.id,
        "main": window.main,
        "chart_window": window.chart_window,
        "focused": window.focused,
        "geometry": {
            "x": window.x,
            "y": window.y,
            "width": window.width,
            "height": window.height,
            "maximized": window.maximized,
        },
        "monitor": window.monitor,
        "tabs": [
            {
                "id": tab.id,
                "name": tab.name,
                "active": tab.active,
                "stacks": [
                    {
                        "widget_id": stack.widget_id,
                        "instrument": stack.instrument,
                        "connection_id": stack.connection_id,
                        "empty": stack.empty,
                        "frozen": stack.frozen,
                    }
                    for stack in tab.stacks
                ],
                "charts": [
                    {
                        "widget_id": chart.widget_id,
                        "instrument": chart.instrument,
                        "interval": chart.interval,
                        "owner_widget_id": chart.owner_widget_id,
                    }
                    for chart in tab.charts
                ],
            }
            for tab in window.tabs
        ],
    }


def workspace_dict(workspace: Workspace) -> dict[str, Any]:
    return {
        "windows": [window_dict(window) for window in workspace.windows],
        "note": "ids are internal to this run of the terminal: read them here, do not keep them",
    }


def outcome_dict(outcome: WorkspaceOutcome) -> dict[str, Any]:
    return {
        "window_id": outcome.window_id,
        "tab_id": outcome.tab_id,
        "stacks": outcome.stacks,
        "charts": outcome.charts,
    }


def register(server: MCPServer, provider: TerminalProvider) -> None:
    @server.tool(name="workspace", annotations=READ_ONLY)
    def workspace() -> dict[str, Any]:
        """Every window of the terminal with its tabs, stacks (order books) and charts.

        The main window cannot be closed; tabs are numbered per window;
        stack and chart widget ids are global. Read this before any
        workspace command: the ids change with every run of the terminal.
        """
        with provider.call() as terminal:
            return workspace_dict(terminal.workspace())

    @server.tool(name="open_stack", annotations=WORKSPACE_WRITE)
    def open_stack(
        instrument: Annotated[str, Field(description="Instrument address exchange:market:symbol")],
        connection_id: Annotated[
            int | None, Field(default=None, description="Connection; the general rule picks one")
        ] = None,
        chart: Annotated[
            bool, Field(default=False, description="Open a chart over the stack")
        ] = False,
        target: Annotated[str, _TARGET] = "new_tab",
        window_id: Annotated[
            int | None, Field(default=None, description="Window for the new tab")
        ] = None,
        activate: Annotated[bool, _ACTIVATE] = True,
    ) -> dict[str, Any]:
        """Open a stack of the instrument in a new tab or a new window, optionally with a chart.

        Answers the window, the new tab and the new widget ids. An instrument
        the terminal's catalogue does not know is ``invalid_request``.
        """
        with provider.call() as terminal:
            outcome = terminal.open_stack(
                instrument,
                connection_id=connection_id,
                chart=chart,
                target=target,
                window_id=window_id,
                activate=activate,
            )
        return outcome_dict(outcome)

    @server.tool(name="open_multiview", annotations=WORKSPACE_WRITE)
    def open_multiview(
        base: Annotated[str, Field(description="Coin (BTC) or pair (BTC/USDT)")],
        target: Annotated[
            str | None,
            Field(
                default=None, description="new_tab or new_window; None follows the terminal setting"
            ),
        ] = None,
        window_id: Annotated[
            int | None, Field(default=None, description="Window for the new tab")
        ] = None,
        activate: Annotated[bool, _ACTIVATE] = True,
    ) -> dict[str, Any]:
        """Open a coin on every venue of «Exchange layout», as the Multiview button does.

        ``not_found`` when no enabled row of the layout lists the coin.
        """
        with provider.call() as terminal:
            outcome = terminal.open_multiview(
                base, target=target, window_id=window_id, activate=activate
            )
        return outcome_dict(outcome)

    @server.tool(name="set_stack_instrument", annotations=WORKSPACE_WRITE)
    def set_stack_instrument(
        widget_id: Annotated[int, _WIDGET],
        instrument: Annotated[str, Field(description="Instrument address exchange:market:symbol")],
        connection_id: Annotated[
            int | None, Field(default=None, description="Connection; the general rule picks one")
        ] = None,
    ) -> dict[str, Any]:
        """Switch a stack (and the charts that follow it) to another instrument."""
        with provider.call() as terminal:
            outcome = terminal.set_stack_instrument(
                widget_id, instrument, connection_id=connection_id
            )
        return outcome_dict(outcome)

    @server.tool(name="close_stack", annotations=WORKSPACE_WRITE)
    def close_stack(widget_id: Annotated[int, _WIDGET]) -> dict[str, Any]:
        """Close one stack, as its close button does. A chart widget id is ``invalid_request``."""
        with provider.call() as terminal:
            return outcome_dict(terminal.close_stack(widget_id))

    @server.tool(name="close_tab", annotations=WORKSPACE_WRITE)
    def close_tab(
        window_id: Annotated[int, _WINDOW], tab_id: Annotated[int, _TAB]
    ) -> dict[str, Any]:
        """Close a tab of a window. The only tab of a window cannot be closed."""
        with provider.call() as terminal:
            return outcome_dict(terminal.close_tab(window_id, tab_id))

    @server.tool(name="activate_tab", annotations=WORKSPACE_WRITE)
    def activate_tab(
        window_id: Annotated[int, _WINDOW], tab_id: Annotated[int, _TAB]
    ) -> dict[str, Any]:
        """Select a tab in its window; the window's focus is untouched (see activate_window)."""
        with provider.call() as terminal:
            return outcome_dict(terminal.activate_tab(window_id, tab_id))

    @server.tool(name="close_window", annotations=WORKSPACE_WRITE)
    def close_window(window_id: Annotated[int, _WINDOW]) -> dict[str, Any]:
        """Close a window. The main window is refused: closing it would quit the terminal."""
        with provider.call() as terminal:
            return outcome_dict(terminal.close_window(window_id))

    @server.tool(name="activate_window", annotations=WORKSPACE_WRITE)
    def activate_window(window_id: Annotated[int, _WINDOW]) -> dict[str, Any]:
        """Restore a window if it is minimised and bring it to the front."""
        with provider.call() as terminal:
            return outcome_dict(terminal.activate_window(window_id))
