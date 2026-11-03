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
export type Scope = "market:read" | "connections:read" | OpenString;

/** Stream topics known to v1. */
export type Topic = "trades" | "ticker" | "mark_price" | "book.top" | "clusters";

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
  | "unavailable"
  | OpenString;

/** `status.state` of a connection. */
export type ConnectionState = "disabled" | "enabled" | "connecting" | "connected" | "failed";

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
  instrument: InstrumentAddress;
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
  /** Subscription id, `"{stream}:{topic}"`; pass it to `unsubscribe`. */
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
  instrument: InstrumentAddress;
}

/** Every event the client can tag by topic; `topic` is read from `sub`. */
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
  | UnknownTopicEvent;

/** What iterating a {@link Stream} yields, in arrival order. */
export type StreamFrame = Event | Gap | SubscriptionError;
