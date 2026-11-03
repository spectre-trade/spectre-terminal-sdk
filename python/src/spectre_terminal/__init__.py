"""Python client for the Local API of Spectre Terminal.

    from spectre_terminal import Terminal

    terminal = Terminal.discover()
    for connection in terminal.connections():
        print(connection.id, connection.exchange, connection.market, connection.status.state)

The public surface is :class:`Terminal` (HTTP), :class:`Stream` (WebSocket),
the models of :mod:`spectre_terminal.models`, the errors of
:mod:`spectre_terminal.errors` and the discovery helpers of
:mod:`spectre_terminal.discovery`. Importing the package touches no network.
"""

from __future__ import annotations

from .client import API_VERSION, Terminal
from .discovery import DEFAULT_HOST, DEFAULT_PORT, TOKEN_ENV, instance_path, read_port
from .errors import (
    ApiError,
    IncompatibleTerminal,
    LocalApiDisabled,
    SpectreTerminalError,
    StreamClosed,
    StreamRequestError,
    TerminalUnreachable,
    TokenMissing,
)
from .models import (
    BookTop,
    Candle,
    Candles,
    Cluster,
    ClusterLevel,
    Clusters,
    Connection,
    ConnectionStatus,
    Event,
    Gap,
    Health,
    Instrument,
    Interval,
    Intervals,
    LastEvent,
    Level,
    Limits,
    MarkPrice,
    Meta,
    OrderBook,
    Page,
    Snapshot,
    Subscribed,
    SubscriptionError,
    Ticker,
    Trade,
    Trades,
    Unsubscribed,
)
from .stream import Stream

__version__ = "0.1.0"

__all__ = [
    "API_VERSION",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "TOKEN_ENV",
    "ApiError",
    "BookTop",
    "Candle",
    "Candles",
    "Cluster",
    "ClusterLevel",
    "Clusters",
    "Connection",
    "ConnectionStatus",
    "Event",
    "Gap",
    "Health",
    "IncompatibleTerminal",
    "Instrument",
    "Interval",
    "Intervals",
    "LastEvent",
    "Level",
    "Limits",
    "LocalApiDisabled",
    "MarkPrice",
    "Meta",
    "OrderBook",
    "Page",
    "Snapshot",
    "SpectreTerminalError",
    "Stream",
    "StreamClosed",
    "StreamRequestError",
    "Subscribed",
    "SubscriptionError",
    "Terminal",
    "TerminalUnreachable",
    "Ticker",
    "TokenMissing",
    "Trade",
    "Trades",
    "Unsubscribed",
    "__version__",
    "instance_path",
    "read_port",
]
