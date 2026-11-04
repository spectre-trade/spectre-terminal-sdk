"""Typed views of every response and stream frame of Local API v1.

Field names are the JSON keys of the contract, one to one. Money arrives as
decimal strings and is kept exact as :class:`decimal.Decimal`; timestamps are
``int`` UTC milliseconds; JSON ``null`` is ``None``. Every ``from_dict``
ignores keys it does not know, as the contract requires of clients, so a
newer terminal never breaks an older client.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Generic, NamedTuple, TypeVar

__all__ = [
    "Accepted",
    "AccountBalances",
    "AccountFills",
    "AccountOrders",
    "AccountPositions",
    "Balance",
    "BookTop",
    "Candle",
    "Candles",
    "Cluster",
    "ClusterLevel",
    "Clusters",
    "Connection",
    "ConnectionStatus",
    "Event",
    "Fill",
    "Gap",
    "Health",
    "Instrument",
    "Interval",
    "Intervals",
    "LastEvent",
    "Level",
    "Limits",
    "MarkPrice",
    "Meta",
    "Order",
    "OrderBook",
    "OrdersUpdate",
    "Page",
    "Position",
    "PositionUpdate",
    "Snapshot",
    "Subscribed",
    "SubscriptionError",
    "Ticker",
    "Trade",
    "Trades",
    "TriggerOrder",
    "Unsubscribed",
    "CellPosition",
    "Chart",
    "Stack",
    "Tab",
    "Window",
    "Workspace",
    "WorkspaceOutcome",
]

T = TypeVar("T")


def _decimal(value: Any) -> Decimal:
    """A money string to ``Decimal``. Numbers are accepted too, via their text."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else _decimal(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


class Level(NamedTuple):
    """One order-book level, the ``[price, size]`` pair of the contract."""

    price: Decimal
    size: Decimal

    @classmethod
    def from_pair(cls, pair: Sequence[Any]) -> Level:
        """Build a level from a ``[price, size]`` JSON array."""
        return cls(_decimal(pair[0]), _decimal(pair[1]))


def _optional_level(pair: Sequence[Any] | None) -> Level | None:
    return None if pair is None else Level.from_pair(pair)


def _levels(pairs: Sequence[Sequence[Any]] | None) -> list[Level]:
    return [Level.from_pair(pair) for pair in pairs or ()]


# --- /v1/meta, /v1/health -------------------------------------------------


@dataclass(frozen=True)
class Limits:
    """Ceilings of the stream and of trading, as printed by ``/v1/meta``.

    ``commands_per_second`` is the trading-command rate per listener,
    ``workspace_commands_per_second`` the workspace-command rate; each is
    ``0`` for a terminal older than the stage that added the limit, which
    prints none because it accepts no such commands.
    """

    ws_connections_per_token: int
    subscriptions_per_connection: int
    api_only_instruments: int
    exchange_subscriptions_per_second: int
    commands_per_second: int = 0
    workspace_commands_per_second: int = 0

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Limits:
        return cls(
            ws_connections_per_token=int(d["ws_connections_per_token"]),
            subscriptions_per_connection=int(d["subscriptions_per_connection"]),
            api_only_instruments=int(d["api_only_instruments"]),
            exchange_subscriptions_per_second=int(d["exchange_subscriptions_per_second"]),
            commands_per_second=int(d.get("commands_per_second") or 0),
            workspace_commands_per_second=int(d.get("workspace_commands_per_second") or 0),
        )


@dataclass(frozen=True)
class Meta:
    """``GET /v1/meta``: API version, terminal build, token scopes, limits, stream topics.

    ``topics`` is empty when the terminal was built without the market-data
    tap; the stream and the market operations then answer ``unsupported``.
    """

    api_version: str
    app_version: str
    build_hash: str
    build_env: str
    features: str
    scopes: list[str]
    limits: Limits
    topics: list[str]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Meta:
        return cls(
            api_version=str(d["api_version"]),
            app_version=str(d["app_version"]),
            build_hash=str(d["build_hash"]),
            build_env=str(d["build_env"]),
            features=str(d["features"]),
            scopes=[str(scope) for scope in d.get("scopes") or ()],
            limits=Limits.from_dict(d["limits"]),
            topics=[str(topic) for topic in d.get("topics") or ()],
        )


@dataclass(frozen=True)
class Health:
    """``GET /v1/health``: listener state and the market-data hub counters."""

    status: str
    uptime_ms: int
    clients: int
    streams: int
    api_only_instruments: int
    dropped_events: int
    dropped_frames: int
    overflow_closes: int
    stream_available: bool

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Health:
        return cls(
            status=str(d["status"]),
            uptime_ms=int(d["uptime_ms"]),
            clients=int(d["clients"]),
            streams=int(d["streams"]),
            api_only_instruments=int(d["api_only_instruments"]),
            dropped_events=int(d["dropped_events"]),
            dropped_frames=int(d["dropped_frames"]),
            overflow_closes=int(d["overflow_closes"]),
            stream_available=bool(d["stream_available"]),
        )


# --- /v1/connections --------------------------------------------------------


@dataclass(frozen=True)
class LastEvent:
    """The last record of the connection history: a stage or error code and its time."""

    code: str
    ts: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> LastEvent:
        return cls(code=str(d["code"]), ts=int(d["ts"]))


@dataclass(frozen=True)
class ConnectionStatus:
    """Connection state: ``disabled``, ``enabled``, ``connecting``, ``connected`` or ``failed``.

    ``last_event`` is ``None`` when the connection has no history yet.
    """

    state: str
    last_event: LastEvent | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ConnectionStatus:
        last_event = d.get("last_event")
        return cls(
            state=str(d["state"]),
            last_event=None if last_event is None else LastEvent.from_dict(last_event),
        )


@dataclass(frozen=True)
class Connection:
    """One of the terminal's exchange connections. Carries no secrets, not even masked."""

    id: int
    exchange: str
    market: str
    label: str
    enabled: bool
    read_only: bool
    has_credentials: bool
    proxy_bound: bool
    status: ConnectionStatus

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Connection:
        return cls(
            id=int(d["id"]),
            exchange=str(d["exchange"]),
            market=str(d["market"]),
            label=str(d["label"]),
            enabled=bool(d["enabled"]),
            read_only=bool(d["read_only"]),
            has_credentials=bool(d["has_credentials"]),
            proxy_bound=bool(d["proxy_bound"]),
            status=ConnectionStatus.from_dict(d["status"]),
        )


# --- /v1/instruments --------------------------------------------------------


@dataclass(frozen=True)
class Instrument:
    """A catalogue entry. Steps and minimums are ``None`` when the exchange did not report them."""

    instrument: str
    exchange: str
    market: str
    symbol: str
    base: str
    quote: str
    status: str
    tick_size: Decimal | None
    lot_size: Decimal | None
    min_size: Decimal | None
    contract_value: Decimal | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Instrument:
        return cls(
            instrument=str(d["instrument"]),
            exchange=str(d["exchange"]),
            market=str(d["market"]),
            symbol=str(d["symbol"]),
            base=str(d["base"]),
            quote=str(d["quote"]),
            status=str(d["status"]),
            tick_size=_optional_decimal(d.get("tick_size")),
            lot_size=_optional_decimal(d.get("lot_size")),
            min_size=_optional_decimal(d.get("min_size")),
            contract_value=_optional_decimal(d.get("contract_value")),
        )


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page of a list: ``data`` plus the ``next_cursor`` for the following page.

    ``exchange`` and ``market`` name the pair the page was listed for.
    ``next_cursor`` is ``None`` on the last page.
    """

    data: list[T]
    next_cursor: str | None
    exchange: str
    market: str

    @classmethod
    def of_instruments(cls, d: Mapping[str, Any]) -> Page[Instrument]:
        """Parse a ``GET /v1/instruments`` response."""
        return Page(
            data=[Instrument.from_dict(item) for item in d.get("data") or ()],
            next_cursor=_optional_str(d.get("next_cursor")),
            exchange=str(d["exchange"]),
            market=str(d["market"]),
        )


# --- /v1/market/intervals, /v1/market/candles --------------------------------


@dataclass(frozen=True)
class Interval:
    """An interval code the terminal knows and its nominal length."""

    id: str
    duration_ms: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Interval:
        return cls(id=str(d["id"]), duration_ms=int(d["duration_ms"]))


@dataclass(frozen=True)
class Intervals:
    """``GET /v1/market/intervals``: candle and cluster intervals."""

    candles: list[Interval]
    clusters: list[Interval]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Intervals:
        return cls(
            candles=[Interval.from_dict(item) for item in d.get("candles") or ()],
            clusters=[Interval.from_dict(item) for item in d.get("clusters") or ()],
        )


@dataclass(frozen=True)
class Candle:
    """One bar. ``ts`` is the bar open; ``volume`` is in the base coin."""

    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    closed: bool

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Candle:
        return cls(
            ts=int(d["ts"]),
            open=_decimal(d["open"]),
            high=_decimal(d["high"]),
            low=_decimal(d["low"]),
            close=_decimal(d["close"]),
            volume=_decimal(d["volume"]),
            quote_volume=_decimal(d["quote_volume"]),
            closed=bool(d["closed"]),
        )


@dataclass(frozen=True)
class Candles:
    """``GET /v1/market/candles``: bars of one instrument and the connection they came through."""

    instrument: str
    connection_id: int
    interval: str
    data: list[Candle]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Candles:
        return cls(
            instrument=str(d["instrument"]),
            connection_id=int(d["connection_id"]),
            interval=str(d["interval"]),
            data=[Candle.from_dict(item) for item in d.get("data") or ()],
        )


# --- /v1/market/trades, /snapshot, /orderbook ---------------------------------


@dataclass(frozen=True)
class Trade:
    """One trade. ``ts`` is when it passed through the terminal, ``exchange_ts`` the exchange time.

    ``id`` is always ``None`` in v1.
    """

    id: str | None
    price: Decimal
    qty: Decimal
    side: str
    ts: int
    exchange_ts: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Trade:
        return cls(
            id=_optional_str(d.get("id")),
            price=_decimal(d["price"]),
            qty=_decimal(d["qty"]),
            side=str(d["side"]),
            ts=int(d["ts"]),
            exchange_ts=int(d["exchange_ts"]),
        )


@dataclass(frozen=True)
class Trades:
    """``GET /v1/market/trades``: the latest trades of one instrument, oldest first."""

    instrument: str
    connection_id: int
    data: list[Trade]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Trades:
        return cls(
            instrument=str(d["instrument"]),
            connection_id=int(d["connection_id"]),
            data=[Trade.from_dict(item) for item in d.get("data") or ()],
        )


@dataclass(frozen=True)
class Ticker:
    """The 24h ticker. Fields the exchange does not report are ``None``.

    ``best_bid`` and ``best_ask`` here are prices from the ticker feed, not
    book levels; the book's top is on :class:`Snapshot`.
    """

    price: Decimal
    change_24h_pct: Decimal | None
    volume_24h: Decimal | None
    high_24h: Decimal | None
    low_24h: Decimal | None
    best_bid: Decimal | None
    best_ask: Decimal | None
    ts: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Ticker:
        return cls(
            price=_decimal(d["price"]),
            change_24h_pct=_optional_decimal(d.get("change_24h_pct")),
            volume_24h=_optional_decimal(d.get("volume_24h")),
            high_24h=_optional_decimal(d.get("high_24h")),
            low_24h=_optional_decimal(d.get("low_24h")),
            best_bid=_optional_decimal(d.get("best_bid")),
            best_ask=_optional_decimal(d.get("best_ask")),
            ts=int(d["ts"]),
        )


@dataclass(frozen=True)
class MarkPrice:
    """A ``mark_price`` stream frame: the mark price and its time."""

    mark_price: Decimal
    ts: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> MarkPrice:
        return cls(mark_price=_decimal(d["mark_price"]), ts=int(d["ts"]))


@dataclass(frozen=True)
class Snapshot:
    """``GET /v1/market/snapshot``: the latest the hub knows about one instrument.

    ``best_bid`` and ``best_ask`` are :class:`Level` pairs from the hub's
    book, ``None`` until a book snapshot has arrived. The other fields are
    ``None`` until their data has arrived.
    """

    instrument: str
    connection_id: int
    ts: int
    best_bid: Level | None
    best_ask: Level | None
    last_trade: Trade | None
    mark_price: Decimal | None
    ticker: Ticker | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Snapshot:
        last_trade = d.get("last_trade")
        ticker = d.get("ticker")
        return cls(
            instrument=str(d["instrument"]),
            connection_id=int(d["connection_id"]),
            ts=int(d["ts"]),
            best_bid=_optional_level(d.get("best_bid")),
            best_ask=_optional_level(d.get("best_ask")),
            last_trade=None if last_trade is None else Trade.from_dict(last_trade),
            mark_price=_optional_decimal(d.get("mark_price")),
            ticker=None if ticker is None else Ticker.from_dict(ticker),
        )


@dataclass(frozen=True)
class BookTop:
    """The top of the book: bids from the best downwards, asks from the best upwards.

    This is the ``data`` of a ``book.top`` stream frame; :class:`OrderBook`
    adds the instrument and the connection for the HTTP operation.
    """

    ts: int
    depth: int
    bids: list[Level]
    asks: list[Level]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> BookTop:
        return cls(
            ts=int(d["ts"]),
            depth=int(d["depth"]),
            bids=_levels(d.get("bids")),
            asks=_levels(d.get("asks")),
        )


@dataclass(frozen=True)
class OrderBook(BookTop):
    """``GET /v1/market/orderbook``: the top of one instrument's book."""

    instrument: str
    connection_id: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> OrderBook:
        return cls(
            ts=int(d["ts"]),
            depth=int(d["depth"]),
            bids=_levels(d.get("bids")),
            asks=_levels(d.get("asks")),
            instrument=str(d["instrument"]),
            connection_id=int(d["connection_id"]),
        )


# --- /v1/market/clusters ----------------------------------------------------


@dataclass(frozen=True)
class ClusterLevel:
    """Volume traded at one price inside a cluster bucket."""

    price: Decimal
    volume: Decimal
    buy_volume: Decimal
    sell_volume: Decimal
    buy_trades: int
    sell_trades: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ClusterLevel:
        return cls(
            price=_decimal(d["price"]),
            volume=_decimal(d["volume"]),
            buy_volume=_decimal(d["buy_volume"]),
            sell_volume=_decimal(d["sell_volume"]),
            buy_trades=int(d["buy_trades"]),
            sell_trades=int(d["sell_trades"]),
        )


@dataclass(frozen=True)
class Cluster:
    """One cluster bucket: totals, price range and every level from the lowest price up.

    ``last_trade_ts`` is ``0`` for a bucket seeded from history without a
    trade time. ``vwap``, ``min_price`` and ``max_price`` are ``None`` for a
    bucket without trades.
    """

    interval: str
    ts: int
    end_ts: int
    volume: Decimal
    buy_volume: Decimal
    sell_volume: Decimal
    trades: int
    vwap: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None
    completed: bool
    last_trade_ts: int
    levels: list[ClusterLevel]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Cluster:
        return cls(
            interval=str(d["interval"]),
            ts=int(d["ts"]),
            end_ts=int(d["end_ts"]),
            volume=_decimal(d["volume"]),
            buy_volume=_decimal(d["buy_volume"]),
            sell_volume=_decimal(d["sell_volume"]),
            trades=int(d["trades"]),
            vwap=_optional_decimal(d.get("vwap")),
            min_price=_optional_decimal(d.get("min_price")),
            max_price=_optional_decimal(d.get("max_price")),
            completed=bool(d["completed"]),
            last_trade_ts=int(d["last_trade_ts"]),
            levels=[ClusterLevel.from_dict(item) for item in d.get("levels") or ()],
        )


@dataclass(frozen=True)
class Clusters:
    """``GET /v1/market/clusters``: the latest buckets of one instrument, oldest first.

    ``interval`` is the one selected for the instrument in the terminal.
    """

    instrument: str
    connection_id: int
    interval: str
    ts: int
    data: list[Cluster]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Clusters:
        return cls(
            instrument=str(d["instrument"]),
            connection_id=int(d["connection_id"]),
            interval=str(d["interval"]),
            ts=int(d["ts"]),
            data=[Cluster.from_dict(item) for item in d.get("data") or ()],
        )


# --- /v1/account/* ------------------------------------------------------------


@dataclass(frozen=True)
class Order:
    """An open order of a connection: ``pending``, ``open`` or ``partially_filled``.

    ``key`` is the terminal's order key (``t-...``), ``exchange_id`` the
    exchange's id; either is ``None`` while unknown. ``size``, ``filled`` and
    ``remaining`` are in the base coin; ``notional`` is the quote amount the
    trader entered, ``None`` for an order that came from an exchange
    snapshot. The JSON key ``type`` is :attr:`order_type` here.
    """

    key: str | None
    exchange_id: str | None
    instrument: str
    side: str
    order_type: str
    price: Decimal | None
    size: Decimal
    filled: Decimal
    remaining: Decimal
    notional: Decimal | None
    status: str
    created_ts: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Order:
        return cls(
            key=_optional_str(d.get("key")),
            exchange_id=_optional_str(d.get("exchange_id")),
            instrument=str(d["instrument"]),
            side=str(d["side"]),
            order_type=str(d["type"]),
            price=_optional_decimal(d.get("price")),
            size=_decimal(d["size"]),
            filled=_decimal(d["filled"]),
            remaining=_decimal(d["remaining"]),
            notional=_optional_decimal(d.get("notional")),
            status=str(d["status"]),
            created_ts=int(d["created_ts"]),
        )


@dataclass(frozen=True)
class TriggerOrder:
    """A trigger order: ``stop_loss``, ``take_profit`` or ``stop`` (:attr:`trigger_type`).

    ``rule`` is ``price_above_or_equal`` or ``price_below_or_equal``;
    ``status`` is ``open``, ``finished``, ``inactive`` or ``invalid``.
    ``size``, ``notional``, ``order_type``, ``client_id`` and ``created_ts``
    are ``None`` when the venue did not report them.
    """

    id: str
    instrument: str
    trigger_type: str
    trigger_price: Decimal
    rule: str
    size: Decimal | None
    notional: Decimal | None
    status: str
    order_type: str | None
    client_id: str | None
    created_ts: int | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> TriggerOrder:
        return cls(
            id=str(d["id"]),
            instrument=str(d["instrument"]),
            trigger_type=str(d["type"]),
            trigger_price=_decimal(d["trigger_price"]),
            rule=str(d["rule"]),
            size=_optional_decimal(d.get("size")),
            notional=_optional_decimal(d.get("notional")),
            status=str(d["status"]),
            order_type=_optional_str(d.get("order_type")),
            client_id=_optional_str(d.get("client_id")),
            created_ts=_optional_int(d.get("created_ts")),
        )


@dataclass(frozen=True)
class AccountOrders:
    """``GET /v1/account/orders``: open orders and trigger orders of one connection."""

    connection_id: int
    data: list[Order]
    triggers: list[TriggerOrder]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> AccountOrders:
        return cls(
            connection_id=int(d["connection_id"]),
            data=[Order.from_dict(item) for item in d.get("data") or ()],
            triggers=[TriggerOrder.from_dict(item) for item in d.get("triggers") or ()],
        )


@dataclass(frozen=True)
class Position:
    """An open position. ``size`` is in the base coin (lots on MOEX, ``lot_size`` base units each).

    ``notional`` is in the quote; ``unrealized_pnl`` and ``mark_price`` are
    the terminal's own (best bid for a long, best ask for a short), ``None``
    until the first book tick.
    """

    instrument: str
    side: str
    size: Decimal
    lot_size: Decimal | None
    entry_price: Decimal | None
    notional: Decimal | None
    unrealized_pnl: Decimal | None
    mark_price: Decimal | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Position:
        return cls(
            instrument=str(d["instrument"]),
            side=str(d["side"]),
            size=_decimal(d["size"]),
            lot_size=_optional_decimal(d.get("lot_size")),
            entry_price=_optional_decimal(d.get("entry_price")),
            notional=_optional_decimal(d.get("notional")),
            unrealized_pnl=_optional_decimal(d.get("unrealized_pnl")),
            mark_price=_optional_decimal(d.get("mark_price")),
        )


@dataclass(frozen=True)
class AccountPositions:
    """``GET /v1/account/positions``: open positions of one connection."""

    connection_id: int
    data: list[Position]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> AccountPositions:
        return cls(
            connection_id=int(d["connection_id"]),
            data=[Position.from_dict(item) for item in d.get("data") or ()],
        )


@dataclass(frozen=True)
class Balance:
    """The latest balance of one currency.

    ``available`` and ``locked`` are ``None`` when the venue does not report
    them; ``ts`` is the exchange time where there is one, otherwise the
    receive time.
    """

    currency: str
    total: Decimal
    available: Decimal | None
    locked: Decimal | None
    ts: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Balance:
        return cls(
            currency=str(d["currency"]),
            total=_decimal(d["total"]),
            available=_optional_decimal(d.get("available")),
            locked=_optional_decimal(d.get("locked")),
            ts=int(d["ts"]),
        )


@dataclass(frozen=True)
class AccountBalances:
    """``GET /v1/account/balances``: per currency, the latest value since the API came on."""

    connection_id: int
    data: list[Balance]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> AccountBalances:
        return cls(
            connection_id=int(d["connection_id"]),
            data=[Balance.from_dict(item) for item in d.get("data") or ()],
        )


@dataclass(frozen=True)
class Fill:
    """One execution. ``position_side`` is ``long``/``short`` on hedged venues, else ``None``."""

    trade_id: str | None
    order_id: str | None
    instrument: str
    side: str
    price: Decimal
    qty: Decimal
    fee: Decimal | None
    fee_currency: str | None
    position_side: str | None
    ts: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Fill:
        return cls(
            trade_id=_optional_str(d.get("trade_id")),
            order_id=_optional_str(d.get("order_id")),
            instrument=str(d["instrument"]),
            side=str(d["side"]),
            price=_decimal(d["price"]),
            qty=_decimal(d["qty"]),
            fee=_optional_decimal(d.get("fee")),
            fee_currency=_optional_str(d.get("fee_currency")),
            position_side=_optional_str(d.get("position_side")),
            ts=int(d["ts"]),
        )


@dataclass(frozen=True)
class AccountFills:
    """``GET /v1/account/fills``: the connection's latest fills, oldest first."""

    connection_id: int
    data: list[Fill]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> AccountFills:
        return cls(
            connection_id=int(d["connection_id"]),
            data=[Fill.from_dict(item) for item in d.get("data") or ()],
        )


# --- POST /v1/orders, DELETE /v1/orders/{id}, cancel-all, positions/close ---------


@dataclass(frozen=True)
class Accepted:
    """A trading command was accepted **by the terminal**, not yet by the exchange.

    ``operation_id`` names the operation in the terminal's operations file;
    ``key`` is the order key (``t-...``) under which the order will appear
    in ``account.orders``, ``None`` for a cancellation. The exchange's
    confirmation, fill or rejection arrives through the stream.
    """

    accepted: bool
    operation_id: str
    key: str | None
    connection_id: int
    instrument: str

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Accepted:
        return cls(
            accepted=bool(d["accepted"]),
            operation_id=str(d["operation_id"]),
            key=_optional_str(d.get("key")),
            connection_id=int(d["connection_id"]),
            instrument=str(d["instrument"]),
        )


@dataclass(frozen=True)
class Leverage:
    """``GET /v1/account/leverage``: leverage and margin mode of one futures instrument.

    Read from the terminal's cache, which the window's instrument selection
    and :meth:`~spectre_terminal.Terminal.set_leverage` fill; an instrument
    the terminal has not touched yet is ``ApiError`` ``not_active``. ``mode``
    is the terminal's leverage mode (``manual``, ``max``, ``smart``), not the
    exchange's; ``margin_mode`` is ``cross`` or ``isolated``.
    """

    connection_id: int
    instrument: str
    leverage: int
    max_leverage: int
    mode: str
    margin_mode: str

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Leverage:
        return cls(
            connection_id=int(d["connection_id"]),
            instrument=str(d["instrument"]),
            leverage=int(d["leverage"]),
            max_leverage=int(d["max_leverage"]),
            mode=str(d["mode"]),
            margin_mode=str(d["margin_mode"]),
        )


# --- workspace -------------------------------------------------------------------


@dataclass(frozen=True)
class CellPosition:
    """A cell of a tab's grid: column left to right, row top to bottom, cell within the row."""

    column: int
    row: int
    cell: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CellPosition:
        return cls(column=int(d["column"]), row=int(d["row"]), cell=int(d["cell"]))


def _optional_position(value: Mapping[str, Any] | None) -> CellPosition | None:
    return None if value is None else CellPosition.from_dict(value)


@dataclass(frozen=True)
class Stack:
    """A stack — order book with its trade tape and clusters — inside a tab.

    ``widget_id`` is global for this run of the terminal. ``instrument`` and
    ``connection_id`` are ``None`` while the stack is ``empty``; ``position``
    is ``None`` for a stack hidden inside a stack group.
    """

    widget_id: int
    instrument: str | None
    connection_id: int | None
    empty: bool
    frozen: bool
    position: CellPosition | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Stack:
        return cls(
            widget_id=int(d["widget_id"]),
            instrument=_optional_str(d.get("instrument")),
            connection_id=_optional_int(d.get("connection_id")),
            empty=bool(d["empty"]),
            frozen=bool(d["frozen"]),
            position=_optional_position(d.get("position")),
        )


@dataclass(frozen=True)
class Chart:
    """A chart inside a tab.

    ``owner_widget_id`` is the stack the chart follows, ``None`` when standalone.
    """

    widget_id: int
    instrument: str | None
    connection_id: int | None
    interval: str
    owner_widget_id: int | None
    position: CellPosition | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Chart:
        return cls(
            widget_id=int(d["widget_id"]),
            instrument=_optional_str(d.get("instrument")),
            connection_id=_optional_int(d.get("connection_id")),
            interval=str(d["interval"]),
            owner_widget_id=_optional_int(d.get("owner_widget_id")),
            position=_optional_position(d.get("position")),
        )


@dataclass(frozen=True)
class Tab:
    """A tab of a window: ``id`` is numbered per window from 1, exactly one tab is ``active``."""

    id: int
    name: str
    active: bool
    stacks: list[Stack]
    charts: list[Chart]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Tab:
        return cls(
            id=int(d["id"]),
            name=str(d["name"]),
            active=bool(d["active"]),
            stacks=[Stack.from_dict(item) for item in d.get("stacks") or ()],
            charts=[Chart.from_dict(item) for item in d.get("charts") or ()],
        )


@dataclass(frozen=True)
class Window:
    """A terminal window; ``main`` cannot be closed through the API.

    ``chart_window`` is a torn-off chart window. The geometry is in logical
    screen pixels; ``monitor`` is the OS's monitor name or ``None``.
    """

    id: int
    main: bool
    chart_window: bool
    focused: bool
    x: int
    y: int
    width: int
    height: int
    maximized: bool
    monitor: str | None
    tabs: list[Tab]

    @property
    def active_tab(self) -> Tab | None:
        return next((tab for tab in self.tabs if tab.active), None)

    def tab(self, tab_id: int) -> Tab | None:
        return next((tab for tab in self.tabs if tab.id == tab_id), None)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Window:
        geometry = d["geometry"]
        return cls(
            id=int(d["id"]),
            main=bool(d["main"]),
            chart_window=bool(d["chart_window"]),
            focused=bool(d["focused"]),
            x=int(geometry["x"]),
            y=int(geometry["y"]),
            width=int(geometry["width"]),
            height=int(geometry["height"]),
            maximized=bool(geometry["maximized"]),
            monitor=_optional_str(d.get("monitor")),
            tabs=[Tab.from_dict(item) for item in d.get("tabs") or ()],
        )


@dataclass(frozen=True)
class Workspace:
    """``GET /v1/workspace`` and the ``workspace`` stream topic: every window, by ascending id.

    The ids are internal numbers of this run of the terminal: do not keep
    them across restarts, read them again.
    """

    windows: list[Window]

    @property
    def main(self) -> Window | None:
        return next((window for window in self.windows if window.main), None)

    def window(self, window_id: int) -> Window | None:
        return next((window for window in self.windows if window.id == window_id), None)

    def stack(self, widget_id: int) -> Stack | None:
        for window in self.windows:
            for tab in window.tabs:
                for stack in tab.stacks:
                    if stack.widget_id == widget_id:
                        return stack
        return None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Workspace:
        data = d.get("data", d)
        return cls(windows=[Window.from_dict(item) for item in data.get("windows") or ()])


@dataclass(frozen=True)
class WorkspaceOutcome:
    """What the window did for a workspace command.

    For an opening: the window, the new tab and its ``stacks`` and
    ``charts`` in column order. For closing and activating: the touched
    ids, the rest ``None`` or empty.
    """

    window_id: int | None
    tab_id: int | None
    stacks: list[int]
    charts: list[int]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> WorkspaceOutcome:
        return cls(
            window_id=_optional_int(d.get("window_id")),
            tab_id=_optional_int(d.get("tab_id")),
            stacks=[int(item) for item in d.get("stacks") or ()],
            charts=[int(item) for item in d.get("charts") or ()],
        )


# --- account stream payloads ----------------------------------------------------


@dataclass(frozen=True)
class OrdersUpdate:
    """An ``account.orders`` frame: orders and triggers of **one instrument** after a change."""

    instrument: str
    orders: list[Order]
    triggers: list[TriggerOrder]

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> OrdersUpdate:
        return cls(
            instrument=str(d["instrument"]),
            orders=[Order.from_dict(item) for item in d.get("orders") or ()],
            triggers=[TriggerOrder.from_dict(item) for item in d.get("triggers") or ()],
        )


@dataclass(frozen=True)
class PositionUpdate:
    """An ``account.positions`` frame: one instrument's position; a close is ``position=None``."""

    instrument: str
    position: Position | None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PositionUpdate:
        position = d.get("position")
        return cls(
            instrument=str(d["instrument"]),
            position=None if position is None else Position.from_dict(position),
        )


# --- /v1/stream frames ------------------------------------------------------


def topic_of(sub: str) -> str:
    """The topic of a subscription id: ``"7:book.top"`` -> ``"book.top"``.

    Market subscriptions are ``"{stream}:{topic}"``, account ones
    ``"{connection}:account.<topic>"``: ``"12:account.fills"`` -> ``"account.fills"``.
    The ``workspace`` subscription has no stream or connection: its id is the
    topic itself.
    """
    head, sep, topic = sub.partition(":")
    return topic if sep else head


@dataclass(frozen=True)
class Subscribed:
    """Reply to ``subscribe``: the subscription id and the connection chosen for it.

    ``connection_id`` is ``None`` for ``workspace``: the layout has no connection.
    """

    sub: str
    connection_id: int | None
    request_id: str | None = None

    @property
    def topic(self) -> str:
        """The topic part of ``sub``."""
        return topic_of(self.sub)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Subscribed:
        return cls(
            sub=str(d["sub"]),
            connection_id=_optional_int(d.get("connection_id")),
            request_id=_optional_str(d.get("request_id")),
        )


@dataclass(frozen=True)
class Unsubscribed:
    """Reply to ``unsubscribe``."""

    sub: str
    request_id: str | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Unsubscribed:
        return cls(sub=str(d["sub"]), request_id=_optional_str(d.get("request_id")))


def parse_event_data(topic: str, data: Any) -> Any:
    """Type the ``data`` of an ``event`` frame by its topic.

    ``trades`` -> ``list[Trade]``, ``ticker`` -> :class:`Ticker`,
    ``mark_price`` -> :class:`MarkPrice`, ``book.top`` -> :class:`BookTop`,
    ``clusters`` -> :class:`Cluster`, ``account.orders`` ->
    :class:`OrdersUpdate`, ``account.positions`` -> :class:`PositionUpdate`,
    ``account.balances`` -> :class:`Balance`, ``account.fills`` ->
    :class:`Fill`, ``workspace`` -> :class:`Workspace`. A topic this client
    does not know is passed through as decoded JSON, so a newer terminal
    still streams.
    """
    if topic == "trades":
        return [Trade.from_dict(item) for item in data or ()]
    if topic == "ticker":
        return Ticker.from_dict(data)
    if topic == "mark_price":
        return MarkPrice.from_dict(data)
    if topic == "book.top":
        return BookTop.from_dict(data)
    if topic == "clusters":
        return Cluster.from_dict(data)
    if topic == "account.orders":
        return OrdersUpdate.from_dict(data)
    if topic == "account.positions":
        return PositionUpdate.from_dict(data)
    if topic == "account.balances":
        return Balance.from_dict(data)
    if topic == "account.fills":
        return Fill.from_dict(data)
    if topic == "workspace":
        return Workspace.from_dict(data)
    return data


@dataclass(frozen=True)
class Event:
    """A data frame of a subscription.

    ``seq`` grows by one for ``trades``; for conflated topics gaps in the
    numbering are normal. ``data`` is typed by the topic, see
    :func:`parse_event_data`.
    """

    sub: str
    seq: int
    ts: int
    data: Any

    @property
    def topic(self) -> str:
        """The topic part of ``sub``."""
        return topic_of(self.sub)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Event:
        sub = str(d["sub"])
        return cls(
            sub=sub,
            seq=int(d["seq"]),
            ts=int(d["ts"]),
            data=parse_event_data(topic_of(sub), d.get("data")),
        )


@dataclass(frozen=True)
class Gap:
    """Events ``from_seq``..``to_seq`` of a ``trades`` subscription were lost.

    Arrives before the first frame after the loss; the trades can be re-read
    with ``Terminal.trades(..., since_ts=...)``.
    """

    sub: str
    from_seq: int
    to_seq: int
    reason: str

    @property
    def topic(self) -> str:
        """The topic part of ``sub``."""
        return topic_of(self.sub)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Gap:
        return cls(
            sub=str(d["sub"]),
            from_seq=int(d["from_seq"]),
            to_seq=int(d["to_seq"]),
            reason=str(d.get("reason") or ""),
        )


@dataclass(frozen=True)
class SubscriptionError:
    """The server removed a subscription: the venue refused or the pair could not be subscribed.

    A new ``subscribe`` starts it again.
    """

    sub: str
    code: str
    message: str

    @property
    def topic(self) -> str:
        """The topic part of ``sub``."""
        return topic_of(self.sub)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> SubscriptionError:
        return cls(
            sub=str(d["sub"]),
            code=str(d["code"]),
            message=str(d.get("message") or ""),
        )
