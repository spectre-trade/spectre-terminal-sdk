"""Exceptions raised by the client.

Every exception derives from :class:`SpectreTerminalError`, so ``except
SpectreTerminalError`` catches anything this package raises on purpose. No
exception ever carries the token in its message or attributes.
"""

from __future__ import annotations

__all__ = [
    "ApiError",
    "IncompatibleTerminal",
    "LocalApiDisabled",
    "SpectreTerminalError",
    "StreamClosed",
    "StreamRequestError",
    "TerminalUnreachable",
    "TokenMissing",
]


class SpectreTerminalError(Exception):
    """Base class of every error raised by ``spectre_terminal``."""


class ApiError(SpectreTerminalError):
    """The terminal answered a request with an error envelope.

    ``code`` is the stable code from the contract (``unauthorized``,
    ``not_found``, ``invalid_request``, ``unsupported``, ``not_active``,
    ``rate_limited``, ``unavailable``, ...); ``message`` is the human-readable
    text that came with it; ``status`` is the HTTP status. A non-JSON error
    body yields ``code="unknown"`` with the body text as the message.
    """

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class TerminalUnreachable(SpectreTerminalError):
    """No terminal answered on the loopback port: connection refused or timed out."""


class LocalApiDisabled(SpectreTerminalError):
    """``instance.json`` says the terminal is running but its Local API is off."""


class TokenMissing(SpectreTerminalError):
    """No token was given and ``SPECTRE_LOCAL_API_TOKEN`` is not set."""


class IncompatibleTerminal(SpectreTerminalError):
    """The terminal serves an API version this client does not support."""

    def __init__(self, api_version: str, supported: str) -> None:
        super().__init__(
            f"the terminal serves API version {api_version!r}, this client supports {supported!r}"
        )
        self.api_version = api_version
        self.supported = supported


class StreamRequestError(SpectreTerminalError):
    """The stream answered a ``subscribe`` or ``unsubscribe`` request with an error frame."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class StreamClosed(SpectreTerminalError):
    """The server closed the stream with a code the caller must notice.

    ``1001`` — the API was switched off or the token was reissued; ``4008`` —
    this client was too slow to read; ``4029`` — the per-token connection
    limit; ``1006`` — the connection dropped without a close frame.
    """

    def __init__(self, code: int | None, reason: str | None) -> None:
        super().__init__(f"stream closed by the server: code {code}, reason {reason or ''!r}")
        self.code = code
        self.reason = reason
