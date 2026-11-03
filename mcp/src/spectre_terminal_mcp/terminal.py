"""The terminal behind the tools: discovered lazily, errors turned into tool errors.

The server must start even when the terminal is not running — the agent
then gets a clear error from the first tool call instead of a dead server —
so discovery happens on first use and is retried after a connection failure.
The token is never part of any message: the client already keeps it out of
its exceptions, and this module adds nothing but the error code.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from mcp.server.mcpserver.exceptions import ToolError
from spectre_terminal import Terminal
from spectre_terminal.errors import (
    ApiError,
    IncompatibleTerminal,
    LocalApiDisabled,
    SpectreTerminalError,
    TerminalUnreachable,
    TokenMissing,
)

__all__ = ["TerminalProvider", "tool_error"]

_SETTINGS_HINT = "Settings App -> General -> Local API"


def tool_error(error: SpectreTerminalError) -> ToolError:
    """Map a client error to a :class:`ToolError` the agent can act on.

    The text starts with a stable code (the contract's error code for
    :class:`ApiError`, a snake_case name for client-side errors) so that a
    model can branch on it, followed by the human message.
    """
    if isinstance(error, ApiError):
        return ToolError(f"{error.code}: {error.message}")
    if isinstance(error, TerminalUnreachable):
        return ToolError(
            "terminal_unreachable: Spectre Terminal is not running or its Local API is "
            f"switched off ({_SETTINGS_HINT})"
        )
    if isinstance(error, LocalApiDisabled):
        return ToolError(f"local_api_disabled: switch the Local API on in {_SETTINGS_HINT}")
    if isinstance(error, TokenMissing):
        return ToolError(
            "token_missing: set SPECTRE_LOCAL_API_TOKEN for the MCP server; copy the token "
            f"in {_SETTINGS_HINT}"
        )
    if isinstance(error, IncompatibleTerminal):
        return ToolError(f"incompatible_terminal: {error}")
    return ToolError(f"{type(error).__name__}: {error}")


class TerminalProvider:
    """Hands out one :class:`Terminal`, built on first use.

    Args:
        factory: how to build the client; :meth:`Terminal.discover` by
            default (port from ``instance.json``, token from the environment).
    """

    def __init__(self, factory: Callable[[], Terminal] = Terminal.discover) -> None:
        self._factory = factory
        self._terminal: Terminal | None = None
        self._lock = threading.Lock()

    def get(self) -> Terminal:
        """The cached client, or a fresh one; raises :class:`ToolError` when it cannot be built."""
        with self._lock:
            if self._terminal is None:
                try:
                    self._terminal = self._factory()
                except SpectreTerminalError as error:
                    raise tool_error(error) from None
            return self._terminal

    def reset(self) -> None:
        """Forget the client so the next call discovers the terminal again."""
        with self._lock:
            self._terminal = None

    @contextmanager
    def call(self) -> Iterator[Terminal]:
        """``with provider.call() as terminal:`` — client errors become tool errors.

        An unreachable terminal drops the cached client: the terminal may
        have been restarted, and the next call should discover it anew.
        """
        terminal = self.get()
        try:
            yield terminal
        except TerminalUnreachable as error:
            self.reset()
            raise tool_error(error) from None
        except SpectreTerminalError as error:
            raise tool_error(error) from None
