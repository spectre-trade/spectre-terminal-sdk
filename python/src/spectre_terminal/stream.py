"""The WebSocket client for ``/v1/stream``: :class:`Stream`.

Built on the ``websockets`` package. The token travels in the handshake
header only; pings are answered by the library. Replies to ``subscribe`` and
``unsubscribe`` are matched to their requests by ``request_id`` in
:class:`FrameRouter`, a pure helper without a socket; everything else —
events, gaps, subscription errors — reaches ``async for`` in arrival order.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus, InvalidURI

from .errors import (
    ApiError,
    SpectreTerminalError,
    StreamClosed,
    StreamRequestError,
    TerminalUnreachable,
)
from .models import Event, Gap, Subscribed, SubscriptionError, Unsubscribed

try:  # websockets >= 13: the new asyncio implementation
    from websockets.asyncio.client import connect as _ws_connect

    _HEADERS_KWARG = "additional_headers"
except ImportError:  # pragma: no cover - websockets 12
    from websockets.client import connect as _ws_connect  # type: ignore[no-redef]

    _HEADERS_KWARG = "extra_headers"

__all__ = ["CLOSE_RAISES", "FrameRouter", "Reply", "Stream", "is_account_topic"]

ACCOUNT_TOPIC_PREFIX = "account."


def is_account_topic(topic: str) -> bool:
    """``True`` for ``account.*`` topics: they subscribe by ``connection_id``, not by instrument."""
    return topic.startswith(ACCOUNT_TOPIC_PREFIX)


WORKSPACE_TOPIC = "workspace"
"""The layout topic: one per terminal, subscribed without instrument or connection."""


CLOSE_RAISES = frozenset({1001, 1006, 4008, 4029})
"""Close codes that end iteration with :class:`~spectre_terminal.errors.StreamClosed`.

``1001`` — the API was switched off or the token reissued; ``4008`` — this
client was too slow; ``4029`` — the per-token connection limit; ``1006`` —
the connection dropped without a close frame.
"""

_log = logging.getLogger("spectre_terminal")


def _supports_kwarg(name: str) -> bool:
    try:
        return name in inspect.signature(_ws_connect.__init__).parameters
    except (TypeError, ValueError):  # pragma: no cover - exotic builds
        return False


_SUPPORTS_PROXY = _supports_kwarg("proxy")


@dataclass(frozen=True)
class Reply:
    """A frame that answers one of our requests, paired by ``request_id``."""

    request_id: str
    frame: Mapping[str, Any]


class FrameRouter:
    """Pairs stream replies with the requests that caused them and types every other frame.

    Pure bookkeeping, no socket: :meth:`open_request` hands out a fresh
    ``request_id`` and remembers it; :meth:`route` classifies an incoming
    frame as a :class:`Reply` to a remembered request, an
    :class:`~spectre_terminal.models.Event`,
    :class:`~spectre_terminal.models.Gap` or
    :class:`~spectre_terminal.models.SubscriptionError`, or ``None`` for a
    frame to ignore (an unknown type, or a reply to a request that is no
    longer pending).
    """

    def __init__(self, prefix: str = "r") -> None:
        self._prefix = prefix
        self._counter = 0
        self._pending: set[str] = set()

    @property
    def pending(self) -> frozenset[str]:
        """Request ids still waiting for a reply."""
        return frozenset(self._pending)

    def open_request(self) -> str:
        """A new unique ``request_id``, remembered until its reply is routed or it is closed."""
        self._counter += 1
        request_id = f"{self._prefix}{self._counter}"
        self._pending.add(request_id)
        return request_id

    def close_request(self, request_id: str) -> None:
        """Forget a request (its sender gave up); a late reply is then ignored."""
        self._pending.discard(request_id)

    def route(self, frame: Mapping[str, Any]) -> Reply | Event | Gap | SubscriptionError | None:
        """Classify one decoded frame.

        A frame carrying a pending ``request_id`` is a :class:`Reply`,
        whatever its type — the server answers an ``unsubscribe`` of an
        unknown subscription with an ``error`` that carries both
        ``request_id`` and ``sub``. An ``error`` with ``sub`` and no
        ``request_id`` is the server removing a subscription.
        """
        request_id = frame.get("request_id")
        if request_id is not None and request_id in self._pending:
            self._pending.discard(request_id)
            return Reply(str(request_id), frame)
        kind = frame.get("type")
        if kind == "event":
            return Event.from_dict(frame)
        if kind == "gap":
            return Gap.from_dict(frame)
        if kind == "error" and request_id is None and frame.get("sub") is not None:
            return SubscriptionError.from_dict(frame)
        return None


_Frame = Event | Gap | SubscriptionError


class Stream:
    """One connection to ``/v1/stream``.

    Use it as an async context manager (or :meth:`connect` / :meth:`close`):
    :meth:`subscribe` and :meth:`unsubscribe` send requests and wait for
    their replies while ``async for frame in stream`` yields
    :class:`~spectre_terminal.models.Event`,
    :class:`~spectre_terminal.models.Gap` and
    :class:`~spectre_terminal.models.SubscriptionError` in arrival order.
    Iteration ends when the connection closes; a server close with a code in
    :data:`CLOSE_RAISES` raises :class:`~spectre_terminal.errors.StreamClosed`
    so the caller notices, and :attr:`close_code` / :attr:`close_reason` keep
    what the server said.

    Frames are buffered up to ``max_pending`` while the caller is not
    iterating; past that the client stops reading the socket, which is how
    the terminal learns a client is slow (``gap`` frames, then close ``4008``).

    Args:
        url: ``ws://127.0.0.1:<port>/v1/stream``; :meth:`Terminal.stream` builds it.
        token: the bearer token for the handshake header.
        open_timeout: seconds to wait for the handshake.
        request_timeout: seconds to wait for a reply to ``subscribe`` /
            ``unsubscribe``; ``None`` waits until the reply or the close.
        max_pending: frames buffered ahead of the iterator.
        max_size: largest frame accepted, in bytes.
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        open_timeout: float = 10.0,
        request_timeout: float | None = None,
        max_pending: int = 1000,
        max_size: int | None = 16 * 1024 * 1024,
    ) -> None:
        self._url = url
        self._token = token
        self._open_timeout = open_timeout
        self._request_timeout = request_timeout
        self._max_pending = max(1, int(max_pending))
        self._max_size = max_size
        self._ws: Any = None
        self._reader: asyncio.Task[None] | None = None
        self._router = FrameRouter()
        self._waiters: dict[str, asyncio.Future[Mapping[str, Any]]] = {}
        self._frames: deque[_Frame] = deque()
        self._has_frames = asyncio.Event()
        self._has_space = asyncio.Event()
        self._ended = False
        self._closing = False
        self._close_code: int | None = None
        self._close_reason: str | None = None

    def __repr__(self) -> str:
        return f"Stream(url={self._url!r}, connected={self.connected})"

    # --- state ------------------------------------------------------------

    @property
    def url(self) -> str:
        """The stream URL."""
        return self._url

    @property
    def connected(self) -> bool:
        """``True`` between a successful handshake and the close."""
        return self._ws is not None and not self._ended

    @property
    def close_code(self) -> int | None:
        """The WebSocket close code once the connection has closed, else ``None``."""
        return self._close_code

    @property
    def close_reason(self) -> str | None:
        """The close reason once the connection has closed, else ``None``."""
        return self._close_reason

    # --- lifecycle --------------------------------------------------------

    async def __aenter__(self) -> Stream:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> Stream:
        """Open the connection. Called by ``async with``; a no-op when already open."""
        if self._ws is not None:
            return self
        kwargs: dict[str, Any] = {
            _HEADERS_KWARG: {"Authorization": f"Bearer {self._token}"},
            "open_timeout": self._open_timeout,
            "max_size": self._max_size,
        }
        if _SUPPORTS_PROXY:
            kwargs["proxy"] = None  # loopback only: never through an environment proxy
        try:
            self._ws = await _ws_connect(self._url, **kwargs)
        except InvalidStatus as error:
            raise _handshake_error(error) from None
        except InvalidURI as error:
            raise SpectreTerminalError(f"bad stream URL: {error}") from None
        except InvalidHandshake as error:
            raise SpectreTerminalError(f"stream handshake failed: {error}") from None
        except (OSError, TimeoutError, asyncio.TimeoutError) as error:
            raise TerminalUnreachable(
                f"cannot reach the stream at {self._url}: {error or 'timed out'} "
                "(is the terminal running with the Local API switched on?)"
            ) from None
        self._has_space.set()
        self._reader = asyncio.ensure_future(self._read())
        return self

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close the connection and wait for the server to complete the handshake."""
        self._closing = True
        self._has_space.set()
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.close(code, reason)
        except ConnectionClosed:  # pragma: no cover - already closed underneath
            pass
        if self._reader is not None:
            try:
                await asyncio.wait_for(self._reader, timeout=5)
            except asyncio.TimeoutError:  # pragma: no cover - a reader stuck on a dead socket
                self._reader.cancel()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - the reader records its own failure
                pass

    # --- requests ---------------------------------------------------------

    async def subscribe(
        self,
        topic: str,
        instrument: str | None = None,
        *,
        connection_id: int | None = None,
        **params: Any,
    ) -> Subscribed:
        """Subscribe to ``topic`` and wait for the server's reply.

        ``topic`` is one of ``/v1/meta``'s ``topics``. Market topics
        (``trades``, ``ticker``, ``mark_price``, ``book.top``, ``clusters``)
        need ``instrument``; ``connection_id`` is optional and chosen by the
        general rule without it. Account topics (``account.orders``,
        ``account.positions``, ``account.balances``, ``account.fills``) need
        ``connection_id`` and take no instrument: the request carries none.
        ``workspace`` takes neither: the layout is one per terminal, and the
        first frame is the current snapshot. ``params`` matter only for
        ``book.top`` (``depth`` 1-200, ``interval_ms`` >= 50); other topics
        ignore them. The reply names the subscription id and the connection
        (``None`` for ``workspace``); an ``error`` reply raises
        :class:`~spectre_terminal.errors.StreamRequestError`.
        """
        account = is_account_topic(topic)
        workspace = topic == WORKSPACE_TOPIC
        if account and connection_id is None:
            raise ValueError(f"{topic} needs connection_id: account topics have no default")
        if not account and not workspace and instrument is None:
            raise ValueError(f"{topic} needs an instrument")
        request: dict[str, Any] = {"type": "subscribe", "topic": topic}
        if instrument is not None and not account and not workspace:
            request["instrument"] = instrument
        if connection_id is not None and not workspace:
            request["connection_id"] = int(connection_id)
        request["params"] = dict(params)
        frame = await self._request(request)
        if frame.get("type") == "subscribed":
            return Subscribed.from_dict(frame)
        raise _request_error(frame)

    async def unsubscribe(self, sub: Subscribed | str) -> Unsubscribed:
        """Remove a subscription by its :class:`~spectre_terminal.models.Subscribed` or its id.

        Unknown subscription ids are answered with ``not_found`` and raise
        :class:`~spectre_terminal.errors.StreamRequestError`.
        """
        sub_id = sub.sub if isinstance(sub, Subscribed) else str(sub)
        frame = await self._request({"type": "unsubscribe", "sub": sub_id})
        if frame.get("type") == "unsubscribed":
            return Unsubscribed.from_dict(frame)
        raise _request_error(frame)

    async def _request(self, request: dict[str, Any]) -> Mapping[str, Any]:
        if self._ws is None:
            raise SpectreTerminalError("the stream is not connected: use 'async with'")
        if self._ended:
            raise StreamClosed(self._close_code, self._close_reason)
        request_id = self._router.open_request()
        request["request_id"] = request_id
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[Mapping[str, Any]] = loop.create_future()
        self._waiters[request_id] = waiter
        try:
            await self._ws.send(json.dumps(request, separators=(",", ":")))
            return await asyncio.wait_for(waiter, timeout=self._request_timeout)
        except ConnectionClosed:
            raise StreamClosed(self._ws.close_code, self._ws.close_reason) from None
        except asyncio.TimeoutError:
            raise StreamRequestError(
                "timeout", f"no reply to {request['type']} within {self._request_timeout} s"
            ) from None
        finally:
            self._waiters.pop(request_id, None)
            self._router.close_request(request_id)

    # --- iteration --------------------------------------------------------

    def __aiter__(self) -> Stream:
        return self

    async def __anext__(self) -> _Frame:
        while not self._frames:
            if self._ended:
                self._finish()
            self._has_frames.clear()
            await self._has_frames.wait()
        frame = self._frames.popleft()
        self._has_space.set()
        return frame

    def _finish(self) -> None:
        """Iteration is over: quiet for a close we asked for or a normal one, loud otherwise."""
        if not self._closing and self._close_code in CLOSE_RAISES:
            raise StreamClosed(self._close_code, self._close_reason)
        raise StopAsyncIteration

    async def _read(self) -> None:
        ws = self._ws
        try:
            while True:
                raw = await ws.recv()
                frame = _decode(raw)
                if frame is None:
                    continue
                try:
                    routed = self._router.route(frame)
                except (KeyError, TypeError, ValueError, ArithmeticError) as error:
                    _log.warning("stream frame %r not understood: %s", frame.get("type"), error)
                    continue
                if routed is None:
                    _log.debug("stream frame %r ignored", frame.get("type"))
                elif isinstance(routed, Reply):
                    waiter = self._waiters.pop(routed.request_id, None)
                    if waiter is not None and not waiter.done():
                        waiter.set_result(routed.frame)
                else:
                    await self._buffer(routed)
        except ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as error:  # pragma: no cover - transport failure
            _log.warning("stream reader stopped: %s", error)
        finally:
            self._close_code = ws.close_code
            self._close_reason = ws.close_reason
            self._ended = True
            closed = StreamClosed(self._close_code, self._close_reason)
            for waiter in self._waiters.values():
                if not waiter.done():
                    waiter.set_exception(closed)
            self._waiters.clear()
            self._has_frames.set()

    async def _buffer(self, frame: _Frame) -> None:
        while len(self._frames) >= self._max_pending and not self._closing:
            self._has_space.clear()
            await self._has_space.wait()
        self._frames.append(frame)
        self._has_frames.set()


def _decode(raw: str | bytes) -> dict[str, Any] | None:
    try:
        frame = json.loads(raw, parse_float=Decimal)
    except ValueError:
        _log.warning("stream frame is not JSON")
        return None
    if not isinstance(frame, dict):
        _log.warning("stream frame is not an object")
        return None
    return frame


def _request_error(frame: Mapping[str, Any]) -> StreamRequestError:
    if frame.get("type") == "error":
        return StreamRequestError(
            str(frame.get("code") or "unknown"), str(frame.get("message") or "")
        )
    return StreamRequestError("unknown", f"unexpected reply of type {frame.get('type')!r}")


def _handshake_error(error: InvalidStatus) -> SpectreTerminalError:
    """A rejected handshake: the contract's envelope when the body carries one."""
    response = error.response
    status = int(response.status_code)
    body = bytes(response.body or b"")
    try:
        envelope = json.loads(body.decode("utf-8", errors="replace"))
        detail = envelope["error"]
        code = str(detail["code"])
        message = str(detail.get("message") or "")
    except (ValueError, KeyError, TypeError):
        return ApiError("unknown", f"the stream handshake was rejected with HTTP {status}", status)
    if code == "unauthorized":
        message = (
            f"{message} (the token may be stale or the Local API may be switched off: "
            "copy a fresh token in Settings App -> General -> Local API)"
        )
    return ApiError(code, message, status)
