"""The synchronous HTTP client: :class:`Terminal`.

Built on :mod:`urllib.request` only. Every request carries exactly two
headers of ours — ``Authorization: Bearer <token>`` and ``Accept:
application/json`` — never an ``Origin``. Redirects are not followed and
environment proxies are ignored: the client talks to the loopback interface
and nothing else.
"""

from __future__ import annotations

import http.client
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Any

from . import discovery
from .errors import (
    ApiError,
    IncompatibleTerminal,
    SpectreTerminalError,
    TerminalUnreachable,
    TokenMissing,
)
from .models import (
    Candles,
    Clusters,
    Connection,
    Health,
    Instrument,
    Intervals,
    Meta,
    OrderBook,
    Page,
    Snapshot,
    Trades,
)
from .stream import Stream

__all__ = ["API_VERSION", "Terminal"]

API_VERSION = "1"
"""The API version this client speaks; checked against ``/v1/meta`` by :meth:`Terminal.discover`."""

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
_UNAUTHORIZED_HINT = (
    "the token may be stale or the Local API may be switched off: "
    "copy a fresh token in Settings App -> General -> Local API"
)

_log = logging.getLogger("spectre_terminal")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: the only legitimate peer is the loopback listener."""

    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _error_from_body(status: int, body: bytes) -> ApiError:
    """The contract's error envelope as :class:`ApiError`; anything else is ``unknown``."""
    text = body.decode("utf-8", errors="replace")
    try:
        envelope = json.loads(text)
        error = envelope["error"]
        code = str(error["code"])
        message = str(error.get("message") or "")
    except (ValueError, KeyError, TypeError):
        return ApiError("unknown", text.strip() or http.client.responses.get(status, ""), status)
    if code == "unauthorized":
        message = f"{message} ({_UNAUTHORIZED_HINT})" if message else _UNAUTHORIZED_HINT
    return ApiError(code, message, status)


class Terminal:
    """A running Spectre Terminal, reached over its Local API on the loopback interface.

    All methods are synchronous and return the typed models of
    :mod:`spectre_terminal.models`. Errors are subclasses of
    :class:`~spectre_terminal.errors.SpectreTerminalError`: the terminal's
    own refusals as :class:`~spectre_terminal.errors.ApiError`, an absent
    terminal as :class:`~spectre_terminal.errors.TerminalUnreachable`.

    Args:
        token: the token copied from Settings App -> General -> Local API.
        port: the listener port, ``48180`` unless the terminal was started
            with ``SPECTRE_LOCAL_API_PORT``; :meth:`discover` reads it from
            ``instance.json``.
        host: ``127.0.0.1`` or ``localhost``; anything else is refused.
        timeout: seconds to wait for a response. Cold market operations can
            take up to 3 s while the terminal opens a stream at the exchange.
    """

    def __init__(
        self,
        token: str,
        *,
        port: int = discovery.DEFAULT_PORT,
        host: str = discovery.DEFAULT_HOST,
        timeout: float = 10.0,
    ) -> None:
        if not token or not token.strip():
            raise TokenMissing("the token must not be empty")
        if host not in _LOOPBACK_HOSTS:
            raise ValueError("host must be 127.0.0.1 or localhost: the Local API is loopback-only")
        self._token = token.strip()
        self._host = host
        self._port = int(port)
        self._timeout = float(timeout)
        self._opener = urllib.request.build_opener(_NoRedirect(), urllib.request.ProxyHandler({}))

    def __repr__(self) -> str:
        return f"Terminal(host={self._host!r}, port={self._port})"

    # --- construction -----------------------------------------------------

    @classmethod
    def discover(cls, token: str | None = None, *, port: int | None = None) -> Terminal:
        """Build a client from the environment and verify the terminal speaks API v1.

        The token is ``token`` or ``SPECTRE_LOCAL_API_TOKEN``; without either
        :class:`~spectre_terminal.errors.TokenMissing` is raised. The port is
        ``port``, else ``local_api_port`` from the terminal's ``instance.json``
        (see :mod:`spectre_terminal.discovery`), else ``48180``. Then
        ``/v1/meta`` is read once: a terminal serving another API version
        raises :class:`~spectre_terminal.errors.IncompatibleTerminal`; a stale
        token or an API that is switched off raises
        :class:`~spectre_terminal.errors.ApiError` with code ``unauthorized``.
        """
        token = token or discovery.token_from_env()
        if not token:
            raise TokenMissing(
                f"no token: pass it to Terminal.discover() or set {discovery.TOKEN_ENV}; "
                "copy it in Settings App -> General -> Local API -> Copy token"
            )
        if port is None:
            port = discovery.read_port() or discovery.DEFAULT_PORT
        terminal = cls(token, port=port)
        meta = terminal.meta()
        if meta.api_version != API_VERSION:
            raise IncompatibleTerminal(meta.api_version, API_VERSION)
        return terminal

    # --- addressing -------------------------------------------------------

    @property
    def host(self) -> str:
        """The loopback host the client talks to."""
        return self._host

    @property
    def port(self) -> int:
        """The listener port."""
        return self._port

    @property
    def base_url(self) -> str:
        """``http://<host>:<port>/v1``."""
        return f"http://{self._host}:{self._port}/v1"

    @property
    def stream_url(self) -> str:
        """``ws://<host>:<port>/v1/stream``."""
        return f"ws://{self._host}:{self._port}/v1/stream"

    # --- operations -------------------------------------------------------

    def meta(self) -> Meta:
        """``GET /v1/meta``: API version, build, token scopes, limits, stream topics."""
        return Meta.from_dict(self._get("/meta"))

    def health(self) -> Health:
        """``GET /v1/health``: listener uptime and the market-data hub counters."""
        return Health.from_dict(self._get("/health"))

    def connections(self) -> list[Connection]:
        """``GET /v1/connections``: every connection of the terminal (``connections:read``)."""
        body = self._get("/connections")
        return [Connection.from_dict(item) for item in body.get("data") or ()]

    def connection(self, id: int) -> Connection:
        """``GET /v1/connections/{id}``: one connection; ``not_found`` if there is no such id."""
        return Connection.from_dict(self._get(f"/connections/{int(id)}"))

    def instruments(
        self,
        *,
        connection_id: int | None = None,
        exchange: str | None = None,
        market: str | None = None,
        q: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Instrument]:
        """``GET /v1/instruments``: one page of the catalogue of an exchange and market.

        Name the pair by ``connection_id`` or by ``exchange`` and ``market``
        (one of the two is required). ``q`` filters by a case-insensitive
        substring of the symbol or the base coin; ``limit`` is 1-2000
        (default 500); ``cursor`` is the ``next_cursor`` of the previous page.
        """
        body = self._get(
            "/instruments",
            connection_id=connection_id,
            exchange=exchange,
            market=market,
            q=q,
            limit=limit,
            cursor=cursor,
        )
        return Page.of_instruments(body)

    def iter_instruments(
        self,
        *,
        connection_id: int | None = None,
        exchange: str | None = None,
        market: str | None = None,
        q: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Iterator[Instrument]:
        """Every instrument of the catalogue, following ``next_cursor`` page by page.

        Same parameters as :meth:`instruments`; ``cursor`` is where to start.
        """
        while True:
            page = self.instruments(
                connection_id=connection_id,
                exchange=exchange,
                market=market,
                q=q,
                limit=limit,
                cursor=cursor,
            )
            yield from page.data
            if page.next_cursor is None or page.next_cursor == cursor:
                return
            cursor = page.next_cursor

    def intervals(self) -> Intervals:
        """``GET /v1/market/intervals``: the candle and cluster intervals the terminal knows."""
        return Intervals.from_dict(self._get("/market/intervals"))

    def candles(
        self,
        instrument: str,
        interval: str,
        *,
        limit: int | None = None,
        end: int | None = None,
        connection_id: int | None = None,
    ) -> Candles:
        """``GET /v1/market/candles``: bar history by the path the chart in the window uses.

        ``interval`` is a code from :meth:`intervals` (``1m``, ``5m``, ...);
        ``limit`` is up to 2000 (default 500); ``end`` is the right boundary
        in UTC milliseconds (default now). The exchange not answering is
        ``ApiError`` ``unavailable``.
        """
        body = self._get(
            "/market/candles",
            instrument=instrument,
            interval=interval,
            limit=limit,
            end=end,
            connection_id=connection_id,
        )
        return Candles.from_dict(body)

    def trades(
        self,
        instrument: str,
        *,
        limit: int | None = None,
        since_ts: int | None = None,
        connection_id: int | None = None,
    ) -> Trades:
        """``GET /v1/market/trades``: the latest trades of the instrument, oldest first.

        ``limit`` is 1-1000 (default 100); ``since_ts`` drops trades received
        before that UTC millisecond. A cold instrument waits for data up to
        3 s; 3 s without a trade is an honestly empty list.
        """
        body = self._get(
            "/market/trades",
            instrument=instrument,
            limit=limit,
            since_ts=since_ts,
            connection_id=connection_id,
        )
        return Trades.from_dict(body)

    def snapshot(self, instrument: str, *, connection_id: int | None = None) -> Snapshot:
        """``GET /v1/market/snapshot``: best bid and ask, last trade, mark price and ticker."""
        body = self._get("/market/snapshot", instrument=instrument, connection_id=connection_id)
        return Snapshot.from_dict(body)

    def orderbook(
        self,
        instrument: str,
        *,
        depth: int | None = None,
        connection_id: int | None = None,
    ) -> OrderBook:
        """``GET /v1/market/orderbook``: the top ``depth`` levels (1-200, default 50) of the book.

        No full book within 3 s is ``ApiError`` ``unavailable``: an empty
        book would look like an empty market.
        """
        body = self._get(
            "/market/orderbook",
            instrument=instrument,
            depth=depth,
            connection_id=connection_id,
        )
        return OrderBook.from_dict(body)

    def clusters(self, instrument: str, *, connection_id: int | None = None) -> Clusters:
        """``GET /v1/market/clusters``: the latest cluster buckets at the terminal's interval.

        An instrument not open in the window is computed on request and its
        history is seeded from the backend; if the seed takes longer than 3 s
        the answer is ``ApiError`` ``not_active`` and a retry a few seconds
        later finds the clusters.
        """
        body = self._get("/market/clusters", instrument=instrument, connection_id=connection_id)
        return Clusters.from_dict(body)

    def stream(self) -> Stream:
        """A :class:`~spectre_terminal.stream.Stream` for ``/v1/stream``, for ``async with``."""
        return Stream(self.stream_url, self._token, open_timeout=self._timeout)

    # --- transport --------------------------------------------------------

    def _get(self, path: str, **params: Any) -> Mapping[str, Any]:
        """``GET`` ``path`` under ``/v1`` with the non-``None`` ``params`` as the query string."""
        query = {key: value for key, value in params.items() if value is not None}
        url = self.base_url + path
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        _log.debug("GET %s", url)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            raise _error_from_body(error.code, error.read()) from None
        except urllib.error.URLError as error:
            raise TerminalUnreachable(self._unreachable(error.reason)) from None
        except (OSError, http.client.HTTPException) as error:
            raise TerminalUnreachable(self._unreachable(error)) from None
        try:
            decoded = json.loads(body, parse_float=Decimal)
        except ValueError:
            raise SpectreTerminalError(
                f"the terminal answered {path} with a non-JSON body"
            ) from None
        if not isinstance(decoded, dict):
            raise SpectreTerminalError(f"the terminal answered {path} with a non-object body")
        return decoded

    def _unreachable(self, cause: object) -> str:
        return (
            f"cannot reach Spectre Terminal at {self._host}:{self._port}: {cause} "
            "(is the terminal running with the Local API switched on?)"
        )
