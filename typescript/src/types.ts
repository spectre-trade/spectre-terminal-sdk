/**
 * The DTOs of Local API v1, as interfaces.
 *
 * Field names are the wire names (snake_case), exactly as in the contract's
 * fixtures. Money is a decimal string and stays a string; timestamps are
 * integer UTC milliseconds. Within v1 the contract only grows: a response may
 * carry fields that are not listed here, and a client must ignore them.
 *
 * @module
 */

/**
 * A decimal number as the terminal sends it: `"67000.10"` stays `"67000.10"`.
 * Never convert it with `Number()` — bring a decimal library if you need
 * arithmetic.
 */
export type Decimal = string;

/** UTC milliseconds since the epoch, an integer. */
export type Timestamp = number;

/** Instrument address: `exchange:market:symbol`, exchange in lower case. */
export type InstrumentAddress = string;

/** Trade side. */
export type Side = "buy" | "sell";

/** A string type that keeps literal-union autocompletion while accepting any string. */
type OpenString = string & Record<never, never>;

/** Token scopes known to v1. New scopes may appear within v1. */
export type Scope = "market:read" | "connections:read" | "account:read" | "trading:write" | OpenString;

/** Market topics: `instrument` is required on subscribe, `connection_id` is chosen by the general rule. */
export type MarketTopic = "trades" | "ticker" | "mark_price" | "book.top" | "clusters";

/** Account topics: `connection_id` is required on subscribe, `instrument` is not used. */
export type AccountTopic = "account.orders" | "account.positions" | "account.balances" | "account.fills";

/** Stream topics known to v1. */
export type Topic = MarketTopic | AccountTopic;

/** Error codes of the contract. New codes may appear within v1. */
export type ErrorCode =
  | "unauthorized"
  | "forbidden"
  | "forbidden_scope"
  | "not_found"
  | "invalid_request"
  | "unsupported"
  | "not_active"
  | "rate_limited"
  | "not_tradable"
  | "unavailable"
  | OpenString;

/** `status.state` of a connection. */
export type ConnectionState = "disabled" | "enabled" | "connecting" | "connected" | "failed";

/** Order type: `limit` needs a price, `market` takes none. */
export type OrderType = "limit" | "market";

/** Status of an open order. */
export type OrderStatus = "pending" | "open" | "partially_filled";

/** Kind of a trigger order. */
export type TriggerType = "stop_loss" | "take_profit" | "stop";

/** When a trigger fires. */
export type TriggerRule = "price_above_or_equal" | "price_below_or_equal";

/** Status of a trigger order. */
export type TriggerStatus = "open" | "finished" | "inactive" | "invalid";

/** Side of a position. */
export type PositionSide = "long" | "short";

/** Time in force of a placed order; absent — the venue's default. */
export type TimeInForce = "gtc" | "ioc" | "fok" | "post_only";

/** The error envelope every non-2xx response carries. */
export interface ErrorEnvelope {
  error: {
    code: ErrorCode;
    message: string;
  };
}

/** Lists are wrapped as `{ data: [...] }`. */
export interface List<T> {
  data: T[];
}

// ---------------------------------------------------------------------------
// /v1/meta, /v1/health

/** Limits printed by `/v1/meta`. */
export interface Limits {
  ws_connections_per_token: number;
  subscriptions_per_connection: number;
  api_only_instruments: number;
  exchange_subscriptions_per_second: number;
  /**
   * Trading commands per second per listener. Absent on terminals older
   * than the writing stage of the Local API.
   */
  commands_per_second?: number;
}

/** `GET /v1/meta`. */
export interface Meta {
  /** `"1"` for this contract. */
  api_version: string;
  app_version: string;
  build_hash: string;
  build_env: string;
  /** Enabled build features, as one string. */
  features: string;
  /** Scopes granted to the token used for the request. */
  scopes: Scope[];
  limits: Limits;
  /** Empty when the terminal was built without the market-data tap. */
  topics: Topic[];
}

/** `GET /v1/health`. */
export interface Health {
  status: string;
  uptime_ms: number;
  /** Open stream connections. */
  clients: number;
  /** Pairs the hub holds. */
  streams: number;
  /** Pairs opened only for the API. */
  api_only_instruments: number;
  /** Events the hub did not accept from the market-data loop. */
  dropped_events: number;
  /** Frames that did not fit into client queues. */
  dropped_frames: number;
  /** Clients closed with code 4008. */
  overflow_closes: number;
  /** `false` when the build has no market-data tap. */
  stream_available: boolean;
}

// ---------------------------------------------------------------------------
// /v1/connections

/** The last record of a connection's history. */
export interface ConnectionEvent {
  /** A code from the same feed the Settings App shows. */
  code: string;
  ts: Timestamp;
}

/** Connection status derived from the toggle and the history feed. */
export interface ConnectionStatus {
  state: ConnectionState;
  /** Absent when the connection has no history record in this session. */
  last_event?: ConnectionEvent;
}

/** A terminal connection. Carries no secrets: no keys, no address, no mask. */
export interface Connection {
  id: number;
  /** Exchange name in lower case, as in instrument addresses. */
  exchange: string;
  /** `spot`, `futures`, … */
  market: string;
  label: string;
  enabled: boolean;
  /** A connection without credentials, created by the terminal for market data. */
  read_only: boolean;
  has_credentials: boolean;
  proxy_bound: boolean;
  status: ConnectionStatus;
}

// ---------------------------------------------------------------------------
// /v1/instruments

/** An instrument of the exchange catalogue. */
export interface Instrument {
  instrument: InstrumentAddress;
  exchange: string;
  market: string;
  symbol: string;
  base: string;
  quote: string;
  /** As the exchange reported it: `active`, `inactive`, … */
  status: string;
  /** `null` when the exchange did not report it. */
  tick_size: Decimal | null;
  lot_size: Decimal | null;
  min_size: Decimal | null;
  contract_value: Decimal | null;
}

/** One page of `GET /v1/instruments`. */
export interface InstrumentsPage {
  exchange: string;
  market: string;
  data: Instrument[];
  /** Pass as `cursor` for the next page; `null` on the last page. */
  next_cursor: string | null;
}

// ---------------------------------------------------------------------------
// /v1/market/candles, /v1/market/intervals

/** A candle; `ts` is the bar open, `volume` is in the base coin. */
export interface Candle {
  ts: Timestamp;
  open: Decimal;
  high: Decimal;
  low: Decimal;
  close: Decimal;
  volume: Decimal;
  quote_volume: Decimal;
  closed: boolean;
}

/** `GET /v1/market/candles`. */
export interface Candles {
  instrument: InstrumentAddress;
  connection_id: number;
  interval: string;
  data: Candle[];
}

/** An interval the terminal knows; `duration_ms` is nominal (30 days for `1M`). */
export interface Interval {
  id: string;
  duration_ms: number;
}

/** `GET /v1/market/intervals`. */
export interface Intervals {
  candles: Interval[];
  clusters: Interval[];
}

// ---------------------------------------------------------------------------
// /v1/market/trades, /snapshot, /orderbook, /clusters

/** A trade. `ts` is when it passed through the terminal. */
export interface Trade {
  /** Exchange trade id; always `null` in v1. */
  id: string | null;
  price: Decimal;
  qty: Decimal;
  side: Side;
  ts: Timestamp;
  exchange_ts: Timestamp;
}

/** `GET /v1/market/trades`, oldest to newest. */
export interface Trades {
  instrument: InstrumentAddress;
  connection_id: number;
  data: Trade[];
}

/** A book level as `[price, size]`. */
export type Level = [price: Decimal, size: Decimal];

/** The 24h ticker. */
export interface Ticker {
  price: Decimal;
  change_24h_pct: Decimal | null;
  volume_24h: Decimal;
  high_24h: Decimal | null;
  low_24h: Decimal | null;
  best_bid: Decimal | null;
  best_ask: Decimal | null;
  ts: Timestamp;
}

/** Mark price, the `data` of a `mark_price` event. */
export interface MarkPrice {
  mark_price: Decimal;
  ts: Timestamp;
}

/** `GET /v1/market/snapshot`: the latest the hub knows about the pair. */
export interface Snapshot {
  instrument: InstrumentAddress;
  connection_id: number;
  ts: Timestamp;
  /** From the hub's book; `null` until a book snapshot has arrived. */
  best_bid: Level | null;
  best_ask: Level | null;
  last_trade: Trade | null;
  mark_price: Decimal | null;
  ticker: Ticker | null;
}

/** Top of the book: bids from the best downwards, asks from the best upwards. */
export interface BookTop {
  ts: Timestamp;
  depth: number;
  bids: Level[];
  asks: Level[];
}

/** `GET /v1/market/orderbook`. */
export interface Orderbook extends BookTop {
  instrument: InstrumentAddress;
  connection_id: number;
}

/** One price level of a cluster bucket. */
export interface ClusterLevel {
  price: Decimal;
  volume: Decimal;
  buy_volume: Decimal;
  sell_volume: Decimal;
  buy_trades: number;
  sell_trades: number;
}

/** A cluster bucket; `levels` run from the lowest price to the highest. */
export interface ClusterBucket {
  interval: string;
  /** Bucket start. */
  ts: Timestamp;
  end_ts: Timestamp;
  volume: Decimal;
  buy_volume: Decimal;
  sell_volume: Decimal;
  trades: number;
  /** `null` for a bucket without trades. */
  vwap: Decimal | null;
  min_price: Decimal | null;
  max_price: Decimal | null;
  completed: boolean;
  /** `0` for a bucket from history without a trade time. */
  last_trade_ts: Timestamp;
  levels: ClusterLevel[];
}

/** `GET /v1/market/clusters`, oldest to newest, at most ten buckets. */
export interface Clusters {
  instrument: InstrumentAddress;
  connection_id: number;
  /** The interval selected for the instrument in the terminal. */
  interval: string;
  ts: Timestamp;
  data: ClusterBucket[];
}

// ---------------------------------------------------------------------------
// /v1/account/*

/** An open order of a connection. */
export interface Order {
  /** The terminal's order key (`t-…`); `null` while unknown. */
  key: string | null;
  /** The exchange's order id; `null` while unknown. */
  exchange_id: string | null;
  instrument: InstrumentAddress;
  side: Side;
  type: OrderType;
  price: Decimal;
  /** In the base coin. */
  size: Decimal;
  filled: Decimal;
  remaining: Decimal;
  /** The quote amount the trader entered; `null` for an order from an exchange snapshot. */
  notional: Decimal | null;
  status: OrderStatus;
  created_ts: Timestamp;
}

/** A trigger order (stop loss, take profit, stop) of a connection. */
export interface TriggerOrder {
  id: string;
  instrument: InstrumentAddress;
  type: TriggerType;
  trigger_price: Decimal;
  rule: TriggerRule;
  size: Decimal | null;
  notional: Decimal | null;
  status: TriggerStatus;
  /** The order placed when the trigger fires; `null` when unknown. */
  order_type: string | null;
  client_id: string | null;
  created_ts: Timestamp | null;
}

/** `GET /v1/account/orders`: open orders and trigger orders of one connection. */
export interface AccountOrders {
  connection_id: number;
  data: Order[];
  triggers: TriggerOrder[];
}

/** An open position. */
export interface Position {
  instrument: InstrumentAddress;
  side: PositionSide;
  /** In the base coin; on MOEX in lots. */
  size: Decimal;
  /** Base units per lot. */
  lot_size: Decimal;
  entry_price: Decimal;
  /** In the quote. */
  notional: Decimal;
  /** As the terminal computes it. */
  unrealized_pnl: Decimal;
  /** The terminal's mark: best bid for a long, best ask for a short; `null` until the first book tick. */
  mark_price: Decimal | null;
}

/** `GET /v1/account/positions`. */
export interface AccountPositions {
  connection_id: number;
  data: Position[];
}

/** The latest balance of one currency, as the exchange reported it. */
export interface Balance {
  currency: string;
  total: Decimal;
  /** `null` when the venue does not report it. */
  available: Decimal | null;
  locked: Decimal | null;
  /** Exchange time where there is one, otherwise the receive time. */
  ts: Timestamp;
}

/** `GET /v1/account/balances`: currencies that changed since the API was switched on. */
export interface AccountBalances {
  connection_id: number;
  data: Balance[];
}

/** A fill of the connection's own order. */
export interface Fill {
  trade_id: string;
  order_id: string;
  instrument: InstrumentAddress;
  side: Side;
  price: Decimal;
  qty: Decimal;
  fee: Decimal;
  fee_currency: string;
  /** `long` / `short` on hedged venues, otherwise `null`. */
  position_side: PositionSide | null;
  ts: Timestamp;
}

/** `GET /v1/account/fills`, oldest to newest. */
export interface AccountFills {
  connection_id: number;
  data: Fill[];
}

// ---------------------------------------------------------------------------
// POST /v1/orders, DELETE /v1/orders/{id}, POST /v1/orders/cancel-all, POST /v1/positions/close

/** The body of `POST /v1/orders` as sent on the wire. */
export interface PlaceOrderRequest {
  connection_id: number;
  instrument: InstrumentAddress;
  side: Side;
  type: OrderType;
  /** Required for `limit`, absent for `market`. */
  price?: Decimal;
  /** Amount in the base coin; exactly one of `size` and `notional`. */
  size?: Decimal;
  /** The quote amount; exactly one of `size` and `notional`. */
  notional?: Decimal;
  reduce_only?: boolean;
  post_only?: boolean;
  time_in_force?: TimeInForce;
  /** Idempotency key: a repeat with the same key returns the previous answer. */
  client_key?: string;
}

/** The body of `POST /v1/orders/cancel-all`, `POST /v1/orders/trigger/cancel-all` and `POST /v1/positions/close`. */
export interface InstrumentCommandRequest {
  connection_id: number;
  instrument: InstrumentAddress;
}

/**
 * The body of `POST /v1/orders/trigger`. `stop_loss` and `take_profit` are
 * placed on the open position (side, size and rule come from it); a `stop`
 * carries its own `side`, `notional` and optional `rule`.
 */
export interface PlaceTriggerRequest {
  connection_id: number;
  instrument: InstrumentAddress;
  kind: TriggerType;
  trigger_price: Decimal;
  /** `stop` only. */
  side?: Side;
  /** `stop` only: the quote amount. */
  notional?: Decimal;
  /** `stop` only; absent means above the market for a buy, below for a sell. */
  rule?: TriggerRule;
  /** Idempotency key, as for `POST /v1/orders`. */
  client_key?: string;
}

/** The body of `PATCH /v1/orders/trigger/{id}`: a new trigger price. */
export interface AmendTriggerRequest {
  connection_id: number;
  instrument: InstrumentAddress;
  kind: TriggerType;
  trigger_price: Decimal;
  /** `stop` only. */
  side?: Side;
  /** `stop` only. */
  rule?: TriggerRule;
}

/** The terminal's leverage mode of an instrument, not the exchange's. */
export type LeverageMode = "manual" | "max" | "smart";

/** Margin mode of a futures instrument. */
export type MarginMode = "cross" | "isolated";

/**
 * `GET /v1/account/leverage`: leverage and margin mode of one futures
 * instrument, from the terminal's cache. An instrument the terminal has not
 * touched yet answers `409 not_active`.
 */
export interface Leverage {
  connection_id: number;
  instrument: InstrumentAddress;
  leverage: number;
  max_leverage: number;
  mode: LeverageMode;
  margin_mode: MarginMode;
}

/** The body of `POST /v1/account/leverage`: exactly one of `leverage` and `mode`. */
export interface SetLeverageRequest {
  connection_id: number;
  instrument: InstrumentAddress;
  /** An integer of at least 1. */
  leverage?: number;
  mode?: "max" | "smart";
}

/** The body of `POST /v1/account/margin-mode`. */
export interface SetMarginModeRequest {
  connection_id: number;
  instrument: InstrumentAddress;
  margin_mode: MarginMode;
}

/**
 * The answer of every trading command: accepted **by the terminal**, not by
 * the exchange. The exchange's confirmation, fill or rejection arrives
 * through `account.orders` in the stream or `GET /v1/account/orders`.
 */
export interface Accepted {
  accepted: boolean;
  /** The operation in the terminal's operations file. */
  operation_id: string;
  /**
   * The terminal's key under which the order (`t-…`) or trigger (`sl_…`,
   * `tp_…`, `stop_…`) appears in `account.orders`; `null` for cancellations,
   * amendments and leverage.
   */
  key: string | null;
  connection_id: number;
  instrument: InstrumentAddress;
}

// ---------------------------------------------------------------------------
// /v1/stream

/** Parameters of a `book.top` subscription; other topics take none. Wire names. */
export interface BookTopParams {
  /** 1–200, default 50. */
  depth?: number;
  /** Conflation interval, at least 50, default 100. */
  interval_ms?: number;
}

/** A `subscribe` request as sent on the wire. */
export interface SubscribeRequest {
  type: "subscribe";
  request_id: string;
  topic: Topic;
  /** Required for market topics, omitted for `account.*`. */
  instrument?: InstrumentAddress;
  /** Chosen by the general rule for market topics, required for `account.*`. */
  connection_id?: number;
  params?: BookTopParams;
}

/** An `unsubscribe` request as sent on the wire. */
export interface UnsubscribeRequest {
  type: "unsubscribe";
  request_id: string;
  sub: string;
}

/** Server reply to `subscribe`. */
export interface SubscribedFrame {
  type: "subscribed";
  request_id?: string;
  /** Subscription id, `"{stream}:{topic}"` (`"{connection}:account.<topic>"`); pass it to `unsubscribe`. */
  sub: string;
  connection_id: number;
}

/** Server reply to `unsubscribe`. */
export interface UnsubscribedFrame {
  type: "unsubscribed";
  request_id?: string;
  sub: string;
}

/**
 * An `error` frame: with `request_id` it answers a request, with `sub` and no
 * `request_id` it says the server removed that subscription.
 */
export interface ErrorFrame {
  type: "error";
  request_id?: string;
  sub?: string;
  code: ErrorCode;
  message: string;
}

/** An `event` frame as it arrives, before the client tags it with its topic. */
export interface EventFrame<T = unknown> {
  type: "event";
  sub: string;
  /** Event number within the subscription; grows by one for `trades`. */
  seq: number;
  ts: Timestamp;
  data: T;
}

/** A `gap` frame: events `from_seq`..`to_seq` of a `trades` subscription were lost. */
export interface Gap {
  type: "gap";
  sub: string;
  from_seq: number;
  to_seq: number;
  reason: string;
}

/** The server removed a subscription (an `error` frame with `sub`, no `request_id`). */
export interface SubscriptionError {
  type: "error";
  sub: string;
  code: ErrorCode;
  message: string;
}

/** What `subscribe` resolves with: the `subscribed` frame plus what was asked for. */
export interface Subscribed extends SubscribedFrame {
  topic: Topic;
  /** Absent for `account.*` subscriptions. */
  instrument?: InstrumentAddress;
}

/** `data` of an `account.orders` event: orders and triggers of one instrument after a change. */
export interface OrdersUpdate {
  instrument: InstrumentAddress;
  orders: Order[];
  triggers: TriggerOrder[];
}

/** `data` of an `account.positions` event; a close arrives as `position: null`. */
export interface PositionUpdate {
  instrument: InstrumentAddress;
  position: Position | null;
}

/** Every event the client can tag by topic; `topic` is read from `sub` (the part after the first colon). */
export interface TradesEvent extends EventFrame<Trade[]> {
  topic: "trades";
}

export interface TickerEvent extends EventFrame<Ticker> {
  topic: "ticker";
}

export interface MarkPriceEvent extends EventFrame<MarkPrice> {
  topic: "mark_price";
}

export interface BookTopEvent extends EventFrame<BookTop> {
  topic: "book.top";
}

export interface ClustersEvent extends EventFrame<ClusterBucket> {
  topic: "clusters";
}

export interface AccountOrdersEvent extends EventFrame<OrdersUpdate> {
  topic: "account.orders";
}

export interface AccountPositionsEvent extends EventFrame<PositionUpdate> {
  topic: "account.positions";
}

export interface AccountBalancesEvent extends EventFrame<Balance> {
  topic: "account.balances";
}

export interface AccountFillsEvent extends EventFrame<Fill> {
  topic: "account.fills";
}

/**
 * An event of a topic this client version does not know (the contract may add
 * topics within v1). `topic` is `undefined`; the raw topic name is the part of
 * `sub` after the colon.
 */
export interface UnknownTopicEvent extends EventFrame<unknown> {
  topic: undefined;
}

/** An event frame, discriminated by `topic`. */
export type Event =
  | TradesEvent
  | TickerEvent
  | MarkPriceEvent
  | BookTopEvent
  | ClustersEvent
  | AccountOrdersEvent
  | AccountPositionsEvent
  | AccountBalancesEvent
  | AccountFillsEvent
  | UnknownTopicEvent;

/** What iterating a {@link Stream} yields, in arrival order. */
export type StreamFrame = Event | Gap | SubscriptionError;
