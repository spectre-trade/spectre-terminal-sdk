"""The synchronous HTTP client: :class:`Terminal`.

Built on :mod:`urllib.request` only. Every request carries exactly two
headers of ours — ``Authorization: Bearer <token>`` and ``Accept:
application/json`` — plus ``Content-Type: application/json`` on a request
with a body, never an ``Origin``. Redirects are not followed and
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
from collections.abc import Iterator, Mapping, Sequence
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
    Accepted,
    AccountBalances,
    AccountFills,
    AccountOrders,
    AccountPositions,
    Candles,
    Clusters,
    Connection,
    Health,
    Instrument,
    Intervals,
    Leverage,
    Meta,
    OrderBook,
    OrderbookSettings,
    Page,
    SettingChange,
    Settings,
    SettingsApplied,
    Snapshot,
    TabItem,
    Trades,
    Window,
    Workspace,
    WorkspaceOutcome,
)
from .stream import Stream

__all__ = ["API_VERSION", "Money", "Terminal"]

API_VERSION = "1"
"""The API version this client speaks; checked against ``/v1/meta`` by :meth:`Terminal.discover`."""

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
_UNAUTHORIZED_HINT = (
    "the token may be stale or the Local API may be switched off: "
    "copy a fresh token in Settings App -> General -> Local API"
)

_log = logging.getLogger("spectre_terminal")

Money = Decimal | str | int
"""What :meth:`Terminal.place_order` accepts as a price or amount; sent as a string."""


def _money(value: Money) -> str:
    """A price or amount as the exact decimal string the contract wants; floats are refused."""
    if isinstance(value, (bool, float)):
        raise TypeError(f"money must be Decimal, str or int, not {type(value).__name__}")
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


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

    # --- account (account:read) -------------------------------------------

    def account_orders(self, connection_id: int) -> AccountOrders:
        """``GET /v1/account/orders``: open orders and trigger orders of one connection.

        ``connection_id`` is required: there is no default connection on the
        account operations. An unknown id is ``ApiError`` ``not_found``.
        """
        body = self._get("/account/orders", connection_id=int(connection_id))
        return AccountOrders.from_dict(body)

    def account_positions(self, connection_id: int) -> AccountPositions:
        """``GET /v1/account/positions``: open positions of one connection."""
        body = self._get("/account/positions", connection_id=int(connection_id))
        return AccountPositions.from_dict(body)

    def account_balances(self, connection_id: int) -> AccountBalances:
        """``GET /v1/account/balances``: per currency, the latest balance the exchange sent.

        Balances are accumulated from the moment the API was switched on: a
        currency nothing happened to since then is absent from the list.
        """
        body = self._get("/account/balances", connection_id=int(connection_id))
        return AccountBalances.from_dict(body)

    def account_fills(
        self,
        connection_id: int,
        *,
        limit: int | None = None,
        since_ts: int | None = None,
    ) -> AccountFills:
        """``GET /v1/account/fills``: the connection's latest fills, oldest first.

        ``limit`` is 1-1000 (default 100); ``since_ts`` keeps fills not
        earlier than that exchange time in UTC milliseconds. The buffer is
        the last thousand fills since the API was switched on.
        """
        body = self._get(
            "/account/fills",
            connection_id=int(connection_id),
            limit=limit,
            since_ts=since_ts,
        )
        return AccountFills.from_dict(body)

    # --- trading (trading:write) ------------------------------------------

    def place_order(
        self,
        connection_id: int,
        instrument: str,
        *,
        side: str,
        order_type: str,
        price: Money | None = None,
        size: Money | None = None,
        notional: Money | None = None,
        reduce_only: bool = False,
        post_only: bool = False,
        time_in_force: str | None = None,
        client_key: str | None = None,
    ) -> Accepted:
        """``POST /v1/orders``: place an order the way the window does.

        ``side`` is ``buy`` or ``sell``; ``order_type`` is ``limit`` (needs
        ``price``) or ``market`` (no ``price``); exactly one of ``size`` (base
        coin) and ``notional`` (quote amount) is given. Money is
        :class:`~decimal.Decimal`, ``str`` or ``int`` and travels as a string;
        a ``float`` is refused. ``time_in_force`` is ``gtc``, ``ioc``, ``fok``
        or ``post_only``; absent means the venue's default. ``client_key`` is
        an idempotency key: a repeat with the same key returns the previous
        answer and places nothing.

        The answer is :class:`~spectre_terminal.models.Accepted` — accepted
        by the terminal, not by the exchange; the outcome arrives on
        ``account.orders`` or in :meth:`account_orders`. A connection that
        does not trade is ``ApiError`` ``not_tradable``; a refusal by the
        venue's minimums and steps is ``invalid_request``; faster than
        ``limits.commands_per_second`` is ``rate_limited``.
        """
        if (size is None) == (notional is None):
            raise ValueError("exactly one of size and notional is required")
        body: dict[str, Any] = {
            "connection_id": int(connection_id),
            "instrument": instrument,
            "side": side,
            "type": order_type,
            "reduce_only": bool(reduce_only),
            "post_only": bool(post_only),
        }
        if price is not None:
            body["price"] = _money(price)
        if size is not None:
            body["size"] = _money(size)
        if notional is not None:
            body["notional"] = _money(notional)
        if time_in_force is not None:
            body["time_in_force"] = time_in_force
        if client_key is not None:
            body["client_key"] = client_key
        return Accepted.from_dict(self._send("POST", "/orders", body))

    def cancel_order(self, connection_id: int, instrument: str, order_id: str) -> Accepted:
        """``DELETE /v1/orders/{id}``: cancel one order by terminal key (``t-...``) or exchange id.

        The cancellation goes to the exchange directly; the confirmation
        arrives through the stream. ``Accepted.key`` is ``None``.
        """
        path = "/orders/" + urllib.parse.quote(str(order_id), safe="")
        body = self._send(
            "DELETE", path, None, connection_id=int(connection_id), instrument=instrument
        )
        return Accepted.from_dict(body)

    def cancel_all(self, connection_id: int, instrument: str) -> Accepted:
        """``POST /v1/orders/cancel-all``: cancel every order of the instrument (the space bar)."""
        body = {"connection_id": int(connection_id), "instrument": instrument}
        return Accepted.from_dict(self._send("POST", "/orders/cancel-all", body))

    def close_position(self, connection_id: int, instrument: str) -> Accepted:
        """``POST /v1/positions/close``: close the instrument's position the way the window does.

        On futures a market order for the position size with
        ``close_position``; on spot "cancel all and close" as one atomic
        command. Without an open position — ``ApiError`` ``invalid_request``.
        """
        body = {"connection_id": int(connection_id), "instrument": instrument}
        return Accepted.from_dict(self._send("POST", "/positions/close", body))

    # --- trigger orders (trading:write) -------------------------------------

    def place_trigger(
        self,
        connection_id: int,
        instrument: str,
        *,
        kind: str,
        trigger_price: Money,
        side: str | None = None,
        notional: Money | None = None,
        rule: str | None = None,
        client_key: str | None = None,
    ) -> Accepted:
        """``POST /v1/orders/trigger``: a stop loss, take profit or stop, as the window places them.

        ``kind`` is ``stop_loss`` or ``take_profit`` — placed **on the open
        position** (side, size and rule come from it; without a position
        ``ApiError`` ``invalid_request``) — or ``stop``, which needs ``side``
        (``buy``/``sell``) and ``notional`` (the quote amount) and takes an
        optional ``rule`` (``price_above_or_equal`` or
        ``price_below_or_equal``; absent means above the market for a buy,
        below for a sell). ``client_key`` is an idempotency key as in
        :meth:`place_order`.

        ``Accepted.key`` is the trigger's key (``sl_…``, ``tp_…``,
        ``stop_…``), which shows up as ``client_id`` of the trigger in
        :meth:`account_orders`; cancelling and amending use the numeric
        ``id`` from there. A venue without trigger orders in the terminal is
        ``ApiError`` ``unsupported``.
        """
        if kind == "stop":
            if side is None or notional is None:
                raise ValueError("a stop needs side and notional")
        elif side is not None or notional is not None or rule is not None:
            raise ValueError("side, notional and rule belong to kind='stop' only")
        body: dict[str, Any] = {
            "connection_id": int(connection_id),
            "instrument": instrument,
            "kind": kind,
            "trigger_price": _money(trigger_price),
        }
        if side is not None:
            body["side"] = side
        if notional is not None:
            body["notional"] = _money(notional)
        if rule is not None:
            body["rule"] = rule
        if client_key is not None:
            body["client_key"] = client_key
        return Accepted.from_dict(self._send("POST", "/orders/trigger", body))

    def cancel_trigger(
        self, connection_id: int, instrument: str, trigger_id: int | str
    ) -> Accepted:
        """``DELETE /v1/orders/trigger/{id}``: cancel one trigger by its numeric ``id``.

        The ``id`` is the one from :meth:`account_orders`. ``Accepted.key`` is ``None``.
        """
        path = "/orders/trigger/" + urllib.parse.quote(str(trigger_id), safe="")
        body = self._send(
            "DELETE", path, None, connection_id=int(connection_id), instrument=instrument
        )
        return Accepted.from_dict(body)

    def cancel_all_triggers(self, connection_id: int, instrument: str) -> Accepted:
        """``POST /v1/orders/trigger/cancel-all``: cancel every trigger of the instrument.

        Plain orders stay; they go through :meth:`cancel_all`.
        """
        body = {"connection_id": int(connection_id), "instrument": instrument}
        return Accepted.from_dict(self._send("POST", "/orders/trigger/cancel-all", body))

    def amend_trigger(
        self,
        connection_id: int,
        instrument: str,
        trigger_id: int | str,
        *,
        kind: str,
        trigger_price: Money,
        side: str | None = None,
        rule: str | None = None,
    ) -> Accepted:
        """``PATCH /v1/orders/trigger/{id}``: move a trigger to a new price.

        The window's sequential replacement: the old trigger is cancelled,
        a new one placed. ``kind`` is required (``stop_loss``,
        ``take_profit`` or ``stop``); a ``stop`` also needs ``side`` and
        takes an optional ``rule``. ``Accepted.key`` is ``None``.
        """
        if kind == "stop":
            if side is None:
                raise ValueError("amending a stop needs its side")
        elif side is not None or rule is not None:
            raise ValueError("side and rule belong to kind='stop' only")
        body: dict[str, Any] = {
            "connection_id": int(connection_id),
            "instrument": instrument,
            "kind": kind,
            "trigger_price": _money(trigger_price),
        }
        if side is not None:
            body["side"] = side
        if rule is not None:
            body["rule"] = rule
        path = "/orders/trigger/" + urllib.parse.quote(str(trigger_id), safe="")
        return Accepted.from_dict(self._send("PATCH", path, body))

    # --- leverage and margin mode ---------------------------------------------

    def leverage(self, connection_id: int, instrument: str) -> Leverage:
        """``GET /v1/account/leverage`` (``account:read``): leverage and margin mode.

        Read from the terminal's cache: an instrument the terminal has not
        touched yet is ``ApiError`` ``not_active`` — open it in the window or
        call :meth:`set_leverage`, which is how it enters the cache.
        """
        body = self._get(
            "/account/leverage", connection_id=int(connection_id), instrument=instrument
        )
        return Leverage.from_dict(body)

    def set_leverage(
        self,
        connection_id: int,
        instrument: str,
        *,
        leverage: int | None = None,
        mode: str | None = None,
    ) -> Accepted:
        """``POST /v1/account/leverage`` (``trading:write``): set the leverage as the window does.

        Exactly one of ``leverage`` (an integer of at least 1) or ``mode``
        (``max`` or ``smart``). The answer is ``Accepted`` with ``key``
        ``None``; the applied value shows in :meth:`leverage` after the
        exchange answered.
        """
        if (leverage is None) == (mode is None):
            raise ValueError("exactly one of leverage and mode is required")
        body: dict[str, Any] = {"connection_id": int(connection_id), "instrument": instrument}
        if leverage is not None:
            if isinstance(leverage, bool) or int(leverage) < 1:
                raise ValueError("leverage must be an integer of at least 1")
            body["leverage"] = int(leverage)
        if mode is not None:
            body["mode"] = mode
        return Accepted.from_dict(self._send("POST", "/account/leverage", body))

    def set_margin_mode(self, connection_id: int, instrument: str, margin_mode: str) -> Accepted:
        """``POST /v1/account/margin-mode`` (``trading:write``): ``cross`` or ``isolated``.

        Changing it with an open position is refused by the exchange, as in
        the window; the ``Accepted`` answer does not know that yet.
        """
        body = {
            "connection_id": int(connection_id),
            "instrument": instrument,
            "margin_mode": margin_mode,
        }
        return Accepted.from_dict(self._send("POST", "/account/margin-mode", body))

    # --- workspace --------------------------------------------------------

    def workspace(self) -> Workspace:
        """``GET /v1/workspace`` (``workspace:read``): every window, its tabs, stacks and charts.

        Read from the snapshot the window publishes at every structural
        change, so the call never waits on the window. The ids are internal
        to this run of the terminal.
        """
        return Workspace.from_dict(self._get("/workspace"))

    def workspace_window(self, window_id: int) -> Window:
        """``GET /v1/workspace/windows/{id}``: one window; an unknown id is ``not_found``."""
        return Window.from_dict(self._get(f"/workspace/windows/{int(window_id)}")["data"])

    def open_stack(
        self,
        instrument: str,
        *,
        connection_id: int | None = None,
        chart: bool = False,
        target: str = "new_tab",
        window_id: int | None = None,
        activate: bool = True,
    ) -> WorkspaceOutcome:
        """``POST /v1/workspace/stacks`` (``workspace:write``): a stack in a new tab or window.

        ``target`` is ``new_tab`` (in ``window_id``, or the focused window
        without it) or ``new_window``. ``chart`` opens a chart of the same
        instrument over the stack. ``activate=False`` opens the tab in the
        background; a new window always takes focus. The answer names the
        window, the tab and the new widgets. An instrument the terminal's
        catalogue does not know is ``invalid_request``.
        """
        if target not in ("new_tab", "new_window"):
            raise ValueError("target must be new_tab or new_window")
        body: dict[str, Any] = {
            "instrument": instrument,
            "chart": bool(chart),
            "target": target,
            "activate": bool(activate),
        }
        if connection_id is not None:
            body["connection_id"] = int(connection_id)
        if window_id is not None:
            body["window_id"] = int(window_id)
        return WorkspaceOutcome.from_dict(self._send("POST", "/workspace/stacks", body))

    def open_tab(
        self,
        items: Sequence[TabItem | str],
        *,
        name: str | None = None,
        target: str = "new_tab",
        window_id: int | None = None,
        activate: bool = True,
    ) -> WorkspaceOutcome:
        """``POST /v1/workspace/tabs`` (``workspace:write``): a tab with a column per instrument.

        Each item of ``items`` — a :class:`TabItem` or a bare instrument
        address — becomes a column in list order: a stack and, with
        ``chart``, a chart over it. One to fifty items. ``name`` is the tab
        name (up to 64 characters); without it the terminal names the tab
        after the only instrument or the first one plus a count
        (``BTCUSDT +1``). ``target``, ``window_id`` and ``activate`` are as
        in :meth:`open_stack`. A refusal names the item (``items[1]: …``)
        and nothing reaches the window.
        """
        if target not in ("new_tab", "new_window"):
            raise ValueError("target must be new_tab or new_window")
        body: dict[str, Any] = {
            "items": _tab_items(items),
            "target": target,
            "activate": bool(activate),
        }
        if name is not None:
            body["name"] = name
        if window_id is not None:
            body["window_id"] = int(window_id)
        return WorkspaceOutcome.from_dict(self._send("POST", "/workspace/tabs", body))

    def add_stacks(
        self, window_id: int, tab_id: int, items: Sequence[TabItem | str]
    ) -> WorkspaceOutcome:
        """``POST /v1/workspace/windows/{id}/tabs/{tab}/stacks``: columns after the tab's last one.

        The same ``items`` as :meth:`open_tab`; the tab keeps its name and
        its column widths. No such window or tab is ``not_found``. The
        answer lists only the added ``stacks`` and ``charts``.
        """
        body = {"items": _tab_items(items)}
        return WorkspaceOutcome.from_dict(
            self._send(
                "POST", f"/workspace/windows/{int(window_id)}/tabs/{int(tab_id)}/stacks", body
            )
        )

    def open_multiview(
        self,
        base: str,
        *,
        target: str | None = None,
        window_id: int | None = None,
        activate: bool = True,
    ) -> WorkspaceOutcome:
        """``POST /v1/workspace/multiview`` (``workspace:write``): a coin on every venue.

        The same plan as the window's Multiview button. ``base`` is a coin
        (``BTC``) or a pair (``BTC/USDT``); ``target`` left ``None`` follows
        the Multiview «open as» setting. No cell for the coin is ``not_found``.
        """
        if target is not None and target not in ("new_tab", "new_window"):
            raise ValueError("target must be new_tab, new_window or None")
        body: dict[str, Any] = {"base": base, "activate": bool(activate)}
        if target is not None:
            body["target"] = target
        if window_id is not None:
            body["window_id"] = int(window_id)
        return WorkspaceOutcome.from_dict(self._send("POST", "/workspace/multiview", body))

    def set_stack_instrument(
        self, widget_id: int, instrument: str, *, connection_id: int | None = None
    ) -> WorkspaceOutcome:
        """``PATCH /v1/workspace/stacks/{widget_id}``: another instrument in the stack's group."""
        body: dict[str, Any] = {"instrument": instrument}
        if connection_id is not None:
            body["connection_id"] = int(connection_id)
        return WorkspaceOutcome.from_dict(
            self._send("PATCH", f"/workspace/stacks/{int(widget_id)}", body)
        )

    def close_stack(self, widget_id: int) -> WorkspaceOutcome:
        """``DELETE /v1/workspace/stacks/{widget_id}``: close one stack, as its close button."""
        return WorkspaceOutcome.from_dict(
            self._send("DELETE", f"/workspace/stacks/{int(widget_id)}", None)
        )

    def close_tab(self, window_id: int, tab_id: int) -> WorkspaceOutcome:
        """``DELETE /v1/workspace/windows/{id}/tabs/{tab}``: close a tab.

        The only tab of a window cannot be closed (``invalid_request``).
        """
        return WorkspaceOutcome.from_dict(
            self._send("DELETE", f"/workspace/windows/{int(window_id)}/tabs/{int(tab_id)}", None)
        )

    def activate_tab(self, window_id: int, tab_id: int) -> WorkspaceOutcome:
        """``POST /v1/workspace/windows/{id}/tabs/{tab}/activate``: select the tab.

        The window's focus is untouched; see :meth:`activate_window`.
        """
        return WorkspaceOutcome.from_dict(
            self._send(
                "POST", f"/workspace/windows/{int(window_id)}/tabs/{int(tab_id)}/activate", {}
            )
        )

    def close_window(self, window_id: int) -> WorkspaceOutcome:
        """``DELETE /v1/workspace/windows/{id}``: the main window is ``invalid_request``."""
        return WorkspaceOutcome.from_dict(
            self._send("DELETE", f"/workspace/windows/{int(window_id)}", None)
        )

    def activate_window(self, window_id: int) -> WorkspaceOutcome:
        """``POST /v1/workspace/windows/{id}/activate``: restore and bring to the front."""
        return WorkspaceOutcome.from_dict(
            self._send("POST", f"/workspace/windows/{int(window_id)}/activate", {})
        )

    # --- settings ---------------------------------------------------------

    def settings(
        self,
        *,
        scope: str | None = None,
        category: str | None = None,
        key: str | None = None,
        connection_id: int | None = None,
        instrument: str | None = None,
    ) -> Settings:
        """``GET /v1/settings`` (``settings:read``): rows as stored, no default ladder.

        Without parameters: the global rows without a connection.
        ``instrument`` lists the pair's rows (scope ``order_book``);
        ``connection_id`` the connection's rows. Each row says whether it is
        ``writable`` through :meth:`update_settings`.
        """
        return Settings.from_dict(
            self._get(
                "/settings",
                scope=scope,
                category=category,
                key=key,
                connection_id=None if connection_id is None else int(connection_id),
                instrument=instrument,
            )
        )

    def orderbook_settings(self, connection_id: int, instrument: str) -> OrderbookSettings:
        """``GET /v1/settings/orderbook`` (``settings:read``): stack settings, resolved.

        The ladder the window uses — the pair's row on the connection, the
        connection's default, the pair's row without a connection, the global
        default — with ``resolved_from`` on every key.
        """
        return OrderbookSettings.from_dict(
            self._get(
                "/settings/orderbook", connection_id=int(connection_id), instrument=instrument
            )
        )

    def update_settings(self, changes: Sequence[SettingChange]) -> SettingsApplied:
        """``PATCH /v1/settings`` (``settings:write``): write settings as the Settings App does.

        Every change is checked against the terminal's catalogue first
        (unknown key, wrong type, out of range, wrong shape —
        ``invalid_request`` naming ``changes[i]``, nothing written); leverage
        is ``unsupported`` here (use :meth:`set_leverage`). Then the changes
        are applied in order: the same row, window event and service caches
        as the Settings App. The first failed change stops the list and
        raises; earlier ones stay applied.
        """
        if not changes:
            raise ValueError("changes must not be empty")
        body = {"changes": [change.to_dict() for change in changes]}
        return SettingsApplied.from_dict(self._send("PATCH", "/settings", body))

    def stream(self) -> Stream:
        """A :class:`~spectre_terminal.stream.Stream` for ``/v1/stream``, for ``async with``."""
        return Stream(self.stream_url, self._token, open_timeout=self._timeout)

    # --- transport --------------------------------------------------------

    def _get(self, path: str, **params: Any) -> Mapping[str, Any]:
        """``GET`` ``path`` under ``/v1`` with the non-``None`` ``params`` as the query string."""
        return self._send("GET", path, None, **params)

    def _send(
        self, method: str, path: str, body: Mapping[str, Any] | None, **params: Any
    ) -> Mapping[str, Any]:
        """One request to ``path`` under ``/v1``: ``params`` as the query, ``body`` as JSON."""
        query = {key: value for key, value in params.items() if value is not None}
        url = self.base_url + path
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        _log.debug("%s %s", method, url)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise _error_from_body(error.code, error.read()) from None
        except urllib.error.URLError as error:
            raise TerminalUnreachable(self._unreachable(error.reason)) from None
        except (OSError, http.client.HTTPException) as error:
            raise TerminalUnreachable(self._unreachable(error)) from None
        try:
            decoded = json.loads(raw, parse_float=Decimal)
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


def _tab_items(items: Sequence[TabItem | str]) -> list[dict[str, Any]]:
    """Columns of ``open_tab`` / ``add_stacks`` on the wire.

    A bare instrument address is a stack without a chart.
    """
    if isinstance(items, str) or not items:
        raise ValueError("items must be a non-empty sequence of TabItem or instrument addresses")
    return [
        (item if isinstance(item, TabItem) else TabItem(instrument=str(item))).to_dict()
        for item in items
    ]
