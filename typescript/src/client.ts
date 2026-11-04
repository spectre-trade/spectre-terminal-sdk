/**
 * The REST client of Local API v1.
 *
 * {@link Terminal} wraps the global `fetch` (Node 22+). Every request carries
 * `Authorization: Bearer <token>` and `Accept: application/json` (writes add
 * `Content-Type: application/json`), nothing else; redirects are refused and
 * each request has a timeout. The token lives in a private field and never
 * appears in errors, `JSON.stringify` or `util.inspect` output.
 *
 * @module
 */

import { DEFAULT_PORT, readPort, tokenFromEnv } from "./discovery.ts";
import {
  ApiError,
  IncompatibleTerminalError,
  TerminalUnreachableError,
  TokenMissingError,
} from "./errors.ts";
import { Stream } from "./stream.ts";
import type {
  Accepted,
  AccountBalances,
  AccountFills,
  AccountOrders,
  AccountPositions,
  AmendTriggerRequest,
  Candles,
  Clusters,
  Connection,
  Decimal,
  Health,
  Instrument,
  InstrumentAddress,
  InstrumentCommandRequest,
  InstrumentsPage,
  Intervals,
  Leverage,
  List,
  MarginMode,
  Meta,
  OpenMultiviewRequest,
  OpenStackRequest,
  OpenTarget,
  Orderbook,
  OrderbookSettings,
  OrderType,
  PlaceOrderRequest,
  PlaceTriggerRequest,
  SetLeverageRequest,
  SetMarginModeRequest,
  SettingChange,
  Settings,
  SettingsApplied,
  Side,
  Snapshot,
  StackInstrumentRequest,
  TimeInForce,
  Trades,
  TriggerRule,
  TriggerType,
  UpdateSettingsRequest,
  Workspace,
  WorkspaceOutcome,
  WorkspaceWindow,
} from "./types.ts";

/** The API version this client speaks. */
export const SUPPORTED_API_VERSION = "1";

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_TIMEOUT_MS = 10_000;
const INSPECT = Symbol.for("nodejs.util.inspect.custom");

/** Constructor options of {@link Terminal}. */
export interface TerminalOptions {
  /** The bearer token from Settings App → General → Local API → Copy token. */
  token: string;
  /** Default 48180. */
  port?: number;
  /** `127.0.0.1` or `localhost`; the API refuses any other `Host`. Default `127.0.0.1`. */
  host?: string;
  /** Per-request timeout; default 10 000. Cold market calls may take up to 3 s. */
  timeoutMs?: number;
}

/** Options of {@link Terminal.discover}. */
export interface DiscoverOptions {
  /** Overrides `SPECTRE_LOCAL_API_TOKEN`. */
  token?: string;
  /** Overrides `instance.json`. */
  port?: number;
  host?: string;
  timeoutMs?: number;
  /** Read this file instead of the OS-specific `instance.json` path (tests). */
  instancePath?: string;
}

/** Options of {@link Terminal.instruments}: `connectionId` or `exchange` + `market` is required. */
export interface InstrumentsOptions {
  connectionId?: number;
  exchange?: string;
  market?: string;
  /** Substring of the symbol or the base coin, case-insensitive. */
  q?: string;
  /** 1–2000, default 500. */
  limit?: number;
  /** `next_cursor` of the previous page. */
  cursor?: string;
}

/** Options of {@link Terminal.candles}. */
export interface CandlesOptions {
  /** A code from `/v1/market/intervals`: `1m`, `5m`, … */
  interval: string;
  /** Up to 2000, default 500. */
  limit?: number;
  /** Right boundary, UTC milliseconds; default now. */
  end?: number;
  connectionId?: number;
}

/** Options of {@link Terminal.trades}. */
export interface TradesOptions {
  /** 1–1000 latest, default 100. */
  limit?: number;
  /** Not earlier than this receive time, UTC milliseconds. */
  sinceTs?: number;
  connectionId?: number;
}

/** Options of operations that take only the source connection. */
export interface ConnectionOptions {
  connectionId?: number;
}

/** Options of {@link Terminal.orderbook}. */
export interface OrderbookOptions {
  /** 1–200, default 50. */
  depth?: number;
  connectionId?: number;
}

/** Options of {@link Terminal.accountFills}. */
export interface AccountFillsOptions {
  /** 1–1000 latest, default 100. */
  limit?: number;
  /** Not earlier than this exchange time, UTC milliseconds. */
  sinceTs?: number;
}

/**
 * Options of {@link Terminal.placeOrder}. Money is passed as decimal strings
 * and sent as given; the terminal checks the venue's minimums and steps and
 * answers `invalid_request` with the reason.
 */
export interface PlaceOrderOptions {
  /** The trading connection; there is no default. */
  connectionId: number;
  instrument: InstrumentAddress;
  side: Side;
  /** `limit` needs `price`, `market` takes none. */
  type: OrderType;
  price?: Decimal;
  /** Amount in the base coin; exactly one of `size` and `notional`. */
  size?: Decimal;
  /** The quote amount; exactly one of `size` and `notional`. */
  notional?: Decimal;
  /** Default `false`. */
  reduceOnly?: boolean;
  /** Default `false`. */
  postOnly?: boolean;
  /** Absent — the venue's default. */
  timeInForce?: TimeInForce;
  /**
   * Idempotency key: a repeat with the same key returns the previous answer
   * and does not duplicate the order (the terminal remembers the last thousand).
   */
  clientKey?: string;
}

/** Options of {@link Terminal.cancelOrder}. */
export interface CancelOrderOptions {
  connectionId: number;
  instrument: InstrumentAddress;
  /** The terminal key (`t-…`) or the exchange's order id. */
  orderId: string;
}

/** Options of {@link Terminal.cancelAll}, {@link Terminal.cancelAllTriggers}, {@link Terminal.closePosition} and {@link Terminal.leverage}. */
export interface InstrumentCommandOptions {
  connectionId: number;
  instrument: InstrumentAddress;
}

/** Options of {@link Terminal.placeTrigger}. */
export interface PlaceTriggerOptions {
  connectionId: number;
  instrument: InstrumentAddress;
  /** `stop_loss` and `take_profit` go on the open position; `stop` is its own order. */
  kind: TriggerType;
  triggerPrice: Decimal;
  /** `stop` only. */
  side?: Side;
  /** `stop` only: the quote amount. */
  notional?: Decimal;
  /** `stop` only; absent means above the market for a buy, below for a sell. */
  rule?: TriggerRule;
  /** Idempotency key, as for {@link Terminal.placeOrder}. */
  clientKey?: string;
}

/** Options of {@link Terminal.cancelTrigger}. */
export interface CancelTriggerOptions {
  connectionId: number;
  instrument: InstrumentAddress;
  /** The numeric `id` of the trigger from `accountOrders().triggers`. */
  triggerId: string | number;
}

/** Options of {@link Terminal.amendTrigger}. */
export interface AmendTriggerOptions {
  connectionId: number;
  instrument: InstrumentAddress;
  /** The numeric `id` of the trigger from `accountOrders().triggers`. */
  triggerId: string | number;
  kind: TriggerType;
  triggerPrice: Decimal;
  /** `stop` only. */
  side?: Side;
  /** `stop` only. */
  rule?: TriggerRule;
}

/** Options of {@link Terminal.setLeverage}: exactly one of `leverage` and `mode`. */
export interface SetLeverageOptions {
  connectionId: number;
  instrument: InstrumentAddress;
  /** An integer of at least 1. */
  leverage?: number;
  mode?: "max" | "smart";
}

/** Options of {@link Terminal.setMarginMode}. */
export interface SetMarginModeOptions {
  connectionId: number;
  instrument: InstrumentAddress;
  marginMode: MarginMode;
}

/** Options of {@link Terminal.workspaceWindow}, {@link Terminal.closeWindow} and {@link Terminal.activateWindow}. */
export interface WindowOptions {
  windowId: number;
}

/** Options of {@link Terminal.closeTab} and {@link Terminal.activateTab}: tabs are numbered per window. */
export interface TabOptions {
  windowId: number;
  tabId: number;
}

/** Options of {@link Terminal.closeStack}. */
export interface StackOptions {
  widgetId: number;
}

/** Options of {@link Terminal.openStack}. */
export interface OpenStackOptions {
  instrument: InstrumentAddress;
  /** Chosen by the general rule when omitted. */
  connectionId?: number;
  /** A chart of the same instrument over the stack. */
  chart?: boolean;
  /** `new_tab` (default) or `new_window`. */
  target?: OpenTarget;
  /** The window for a new tab; the focused window when omitted. */
  windowId?: number;
  /** `false` opens the tab in the background; a new window always takes focus. */
  activate?: boolean;
}

/** Options of {@link Terminal.openMultiview}. */
export interface OpenMultiviewOptions {
  /** A coin (`BTC`) or a pair (`BTC/USDT`). */
  base: string;
  /** Omitted: the Multiview «open as» setting decides. */
  target?: OpenTarget;
  windowId?: number;
  activate?: boolean;
}

/** Options of {@link Terminal.setStackInstrument}. */
export interface StackInstrumentOptions {
  widgetId: number;
  instrument: InstrumentAddress;
  connectionId?: number;
}

/** Options of {@link Terminal.settings}: all optional filters. */
export interface SettingsOptions {
  /** `global` (default) or `order_book`. */
  scope?: "global" | "order_book";
  category?: string;
  key?: string;
  /** The connection's rows; without it the rows without a connection. */
  connectionId?: number;
  /** The pair's rows (scope `order_book`). */
  instrument?: InstrumentAddress;
}

/** Options of {@link Terminal.stream}. */
export interface StreamOptions {
  /** Handshake timeout; defaults to the client's `timeoutMs`. */
  timeoutMs?: number;
}

type Query = Record<string, string | number | undefined>;

type Method = "GET" | "POST" | "DELETE" | "PATCH";

interface RequestOptions {
  query?: Query;
  /** Serialised as JSON; `undefined` properties are left out. */
  body?: object;
}

/**
 * A client of one running terminal.
 *
 * Construct it with a token, or let {@link Terminal.discover} find the port
 * and the token and verify the API version. All methods are `async` and
 * throw {@link ApiError} for a non-2xx answer and
 * {@link TerminalUnreachableError} when there is no answer.
 */
export class Terminal {
  readonly host: string;
  readonly port: number;
  readonly timeoutMs: number;
  /** `http://127.0.0.1:48180/v1/` — the token is not part of it. */
  readonly baseUrl: string;
  readonly #token: string;

  constructor(options: TerminalOptions) {
    if (typeof options.token !== "string" || options.token === "") {
      throw new TokenMissingError();
    }
    this.#token = options.token;
    this.host = options.host ?? DEFAULT_HOST;
    this.port = options.port ?? DEFAULT_PORT;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.baseUrl = `http://${authority(this.host, this.port)}/v1/`;
  }

  /**
   * Find the terminal and check it: the token from `options.token` or
   * `SPECTRE_LOCAL_API_TOKEN` (else {@link TokenMissingError}), the port from
   * `options.port` or `instance.json` (else 48180; {@link LocalApiDisabledError}
   * when the file says the API is off), then one `GET /v1/meta`. An
   * `api_version` other than `"1"` is {@link IncompatibleTerminalError}; an
   * `unauthorized` answer is an {@link ApiError} whose message says the token
   * may be stale or the API switched off.
   */
  static async discover(options: DiscoverOptions = {}): Promise<Terminal> {
    const token = options.token ?? tokenFromEnv();
    if (token === undefined || token === "") {
      throw new TokenMissingError();
    }
    const port =
      options.port ??
      (await readPort(options.instancePath === undefined ? {} : { instancePath: options.instancePath })) ??
      DEFAULT_PORT;
    const terminal = new Terminal({
      token,
      port,
      host: options.host,
      timeoutMs: options.timeoutMs,
    });

    let meta: Meta;
    try {
      meta = await terminal.meta();
    } catch (error) {
      if (error instanceof ApiError && error.code === "unauthorized") {
        throw new ApiError(
          error.code,
          `${error.detail}. The token may be stale (reissued in the Settings App) or the Local API may be switched off; copy the current token from Settings App → General → Local API.`,
          error.status,
          { cause: error },
        );
      }
      throw error;
    }
    if (meta.api_version !== SUPPORTED_API_VERSION) {
      throw new IncompatibleTerminalError(meta.api_version, meta.app_version);
    }
    return terminal;
  }

  /** `GET /v1/meta`: API version, build, token scopes, limits, stream topics. */
  meta(): Promise<Meta> {
    return this.#get<Meta>("meta");
  }

  /** `GET /v1/health`. */
  health(): Promise<Health> {
    return this.#get<Health>("health");
  }

  /** `GET /v1/connections` (`connections:read`). */
  connections(): Promise<List<Connection>> {
    return this.#get<List<Connection>>("connections");
  }

  /** `GET /v1/connections/{id}` (`connections:read`); `not_found` for an unknown id. */
  connection(id: number): Promise<Connection> {
    return this.#get<Connection>(`connections/${encodeURIComponent(String(id))}`);
  }

  /**
   * `GET /v1/instruments` (`market:read`): one page of the catalogue of an
   * exchange and market, by `connectionId` or `exchange` + `market`. Follow
   * `next_cursor` by hand or use {@link iterInstruments}.
   */
  instruments(options: InstrumentsOptions): Promise<InstrumentsPage> {
    return this.#get<InstrumentsPage>("instruments", {
      connection_id: options.connectionId,
      exchange: options.exchange,
      market: options.market,
      q: options.q,
      limit: options.limit,
      cursor: options.cursor,
    });
  }

  /** Every instrument matching the options, page after page. */
  async *iterInstruments(options: InstrumentsOptions): AsyncGenerator<Instrument, void, undefined> {
    let cursor = options.cursor;
    for (;;) {
      const page = await this.instruments({ ...options, cursor });
      yield* page.data;
      if (page.next_cursor === null || page.next_cursor === undefined || page.next_cursor === cursor) {
        return;
      }
      cursor = page.next_cursor;
    }
  }

  /** `GET /v1/market/intervals` (`market:read`): candle and cluster intervals. */
  intervals(): Promise<Intervals> {
    return this.#get<Intervals>("market/intervals");
  }

  /** `GET /v1/market/candles` (`market:read`): candle history, oldest first. */
  candles(instrument: InstrumentAddress, options: CandlesOptions): Promise<Candles> {
    return this.#get<Candles>("market/candles", {
      instrument,
      connection_id: options.connectionId,
      interval: options.interval,
      limit: options.limit,
      end: options.end,
    });
  }

  /**
   * `GET /v1/market/trades` (`market:read`): the latest trades of the pair,
   * oldest to newest. A pair without a subscription is opened on demand and
   * the call may take up to 3 s.
   */
  trades(instrument: InstrumentAddress, options: TradesOptions = {}): Promise<Trades> {
    return this.#get<Trades>("market/trades", {
      instrument,
      connection_id: options.connectionId,
      limit: options.limit,
      since_ts: options.sinceTs,
    });
  }

  /** `GET /v1/market/snapshot` (`market:read`): best bid/ask, last trade, mark, ticker. */
  snapshot(instrument: InstrumentAddress, options: ConnectionOptions = {}): Promise<Snapshot> {
    return this.#get<Snapshot>("market/snapshot", {
      instrument,
      connection_id: options.connectionId,
    });
  }

  /** `GET /v1/market/orderbook` (`market:read`); `unavailable` without a full book within 3 s. */
  orderbook(instrument: InstrumentAddress, options: OrderbookOptions = {}): Promise<Orderbook> {
    return this.#get<Orderbook>("market/orderbook", {
      instrument,
      connection_id: options.connectionId,
      depth: options.depth,
    });
  }

  /**
   * `GET /v1/market/clusters` (`market:read`): up to ten buckets at the
   * interval selected in the terminal. The first call for an instrument not
   * open in the window may answer `not_active` (409); a retry a few seconds
   * later finds the clusters.
   */
  clusters(instrument: InstrumentAddress, options: ConnectionOptions = {}): Promise<Clusters> {
    return this.#get<Clusters>("market/clusters", {
      instrument,
      connection_id: options.connectionId,
    });
  }

  /**
   * `GET /v1/account/orders` (`account:read`): open orders and trigger
   * orders of one connection, the same cut the terminal window sees.
   * `not_found` for an unknown connection.
   */
  accountOrders(connectionId: number): Promise<AccountOrders> {
    return this.#get<AccountOrders>("account/orders", { connection_id: connectionId });
  }

  /** `GET /v1/account/positions` (`account:read`): open positions of one connection. */
  accountPositions(connectionId: number): Promise<AccountPositions> {
    return this.#get<AccountPositions>("account/positions", { connection_id: connectionId });
  }

  /**
   * `GET /v1/account/balances` (`account:read`): per currency, the latest
   * value the exchange sent since the API was switched on. A currency
   * nothing happened to since then is absent.
   */
  accountBalances(connectionId: number): Promise<AccountBalances> {
    return this.#get<AccountBalances>("account/balances", { connection_id: connectionId });
  }

  /**
   * `GET /v1/account/fills` (`account:read`): the connection's fills since
   * the API was switched on (the last thousand), oldest to newest.
   */
  accountFills(connectionId: number, options: AccountFillsOptions = {}): Promise<AccountFills> {
    return this.#get<AccountFills>("account/fills", {
      connection_id: connectionId,
      limit: options.limit,
      since_ts: options.sinceTs,
    });
  }

  /**
   * `POST /v1/orders` (`trading:write`): place a limit or market order with
   * the same command the window uses. The answer means accepted by the
   * terminal, not by the exchange: watch `account.orders` in the stream, or
   * {@link accountOrders}, for the order under `key`. `not_tradable` (409)
   * for a disabled, read-only or credential-less connection,
   * `invalid_request` (400) for a foreign instrument or a refused size or
   * price, `rate_limited` (429) above `limits.commands_per_second`.
   */
  placeOrder(options: PlaceOrderOptions): Promise<Accepted> {
    const body: PlaceOrderRequest = {
      connection_id: options.connectionId,
      instrument: options.instrument,
      side: options.side,
      type: options.type,
      price: options.price,
      size: options.size,
      notional: options.notional,
      reduce_only: options.reduceOnly,
      post_only: options.postOnly,
      time_in_force: options.timeInForce,
      client_key: options.clientKey,
    };
    return this.#request<Accepted>("POST", "orders", { body });
  }

  /**
   * `DELETE /v1/orders/{id}` (`trading:write`): cancel one order by the
   * terminal key (`t-…`) or the exchange's id. The cancellation goes to the
   * exchange directly; the confirmation arrives through the stream.
   */
  cancelOrder(options: CancelOrderOptions): Promise<Accepted> {
    return this.#request<Accepted>("DELETE", `orders/${encodeURIComponent(options.orderId)}`, {
      query: { connection_id: options.connectionId, instrument: options.instrument },
    });
  }

  /** `POST /v1/orders/cancel-all` (`trading:write`): cancel every order of the instrument, as the space bar does. */
  cancelAll(options: InstrumentCommandOptions): Promise<Accepted> {
    return this.#request<Accepted>("POST", "orders/cancel-all", { body: instrumentCommand(options) });
  }

  /**
   * `POST /v1/positions/close` (`trading:write`): close the instrument's
   * position the way the window does — a market order for the position size
   * on futures, "cancel all and close" as one atomic command on spot.
   * `invalid_request` without an open position.
   */
  closePosition(options: InstrumentCommandOptions): Promise<Accepted> {
    return this.#request<Accepted>("POST", "positions/close", { body: instrumentCommand(options) });
  }

  /**
   * `POST /v1/orders/trigger` (`trading:write`): a stop loss, take profit or
   * stop, placed by the same services the window uses. `stop_loss` and
   * `take_profit` go on the open position (side, size and rule come from
   * it; `invalid_request` without one); a `stop` needs `side` and
   * `notional`. `key` in the answer is the trigger's key (`sl_…`, `tp_…`,
   * `stop_…`), which shows up as `client_id` of the trigger in
   * {@link accountOrders}; cancelling and amending use the numeric `id` from
   * there. `unsupported` (501) on a venue without trigger orders in the terminal.
   */
  placeTrigger(options: PlaceTriggerOptions): Promise<Accepted> {
    const body: PlaceTriggerRequest = {
      connection_id: options.connectionId,
      instrument: options.instrument,
      kind: options.kind,
      trigger_price: options.triggerPrice,
      side: options.side,
      notional: options.notional,
      rule: options.rule,
      client_key: options.clientKey,
    };
    return this.#request<Accepted>("POST", "orders/trigger", { body });
  }

  /** `DELETE /v1/orders/trigger/{id}` (`trading:write`): cancel one trigger by its numeric `id`. */
  cancelTrigger(options: CancelTriggerOptions): Promise<Accepted> {
    return this.#request<Accepted>("DELETE", `orders/trigger/${encodeURIComponent(String(options.triggerId))}`, {
      query: { connection_id: options.connectionId, instrument: options.instrument },
    });
  }

  /** `POST /v1/orders/trigger/cancel-all` (`trading:write`): cancel every trigger of the instrument; plain orders stay. */
  cancelAllTriggers(options: InstrumentCommandOptions): Promise<Accepted> {
    return this.#request<Accepted>("POST", "orders/trigger/cancel-all", { body: instrumentCommand(options) });
  }

  /**
   * `PATCH /v1/orders/trigger/{id}` (`trading:write`): move a trigger to a
   * new price — the window's sequential replacement, cancel then place.
   * `kind` is required; a `stop` also needs its `side`. `key` is `null`.
   */
  amendTrigger(options: AmendTriggerOptions): Promise<Accepted> {
    const body: AmendTriggerRequest = {
      connection_id: options.connectionId,
      instrument: options.instrument,
      kind: options.kind,
      trigger_price: options.triggerPrice,
      side: options.side,
      rule: options.rule,
    };
    return this.#request<Accepted>("PATCH", `orders/trigger/${encodeURIComponent(String(options.triggerId))}`, {
      body,
    });
  }

  /**
   * `GET /v1/account/leverage` (`account:read`): leverage and margin mode of
   * a futures instrument, from the terminal's cache. An instrument the
   * terminal has not touched yet is `not_active` (409): open it in the window
   * or call {@link setLeverage}, which is how it enters the cache.
   */
  leverage(options: InstrumentCommandOptions): Promise<Leverage> {
    return this.#get<Leverage>("account/leverage", {
      connection_id: options.connectionId,
      instrument: options.instrument,
    });
  }

  /**
   * `POST /v1/account/leverage` (`trading:write`): set the leverage the way
   * the window does — exactly one of `leverage` (an integer ≥ 1) and `mode`
   * (`max`, `smart`). The applied value shows in {@link leverage} after the
   * exchange answered.
   */
  setLeverage(options: SetLeverageOptions): Promise<Accepted> {
    const body: SetLeverageRequest = {
      connection_id: options.connectionId,
      instrument: options.instrument,
      leverage: options.leverage,
      mode: options.mode,
    };
    return this.#request<Accepted>("POST", "account/leverage", { body });
  }

  /**
   * `POST /v1/account/margin-mode` (`trading:write`): `cross` or `isolated`.
   * Changing it with an open position is refused by the exchange, as in the
   * window; the `accepted` answer does not know that yet.
   */
  setMarginMode(options: SetMarginModeOptions): Promise<Accepted> {
    const body: SetMarginModeRequest = {
      connection_id: options.connectionId,
      instrument: options.instrument,
      margin_mode: options.marginMode,
    };
    return this.#request<Accepted>("POST", "account/margin-mode", { body });
  }

  // --- workspace -----------------------------------------------------------

  /**
   * `GET /v1/workspace` (`workspace:read`): every window with its tabs,
   * stacks and charts, from the snapshot the window publishes at every
   * structural change. The ids are internal to this run of the terminal.
   */
  workspace(): Promise<Workspace> {
    return this.#get<Workspace>("workspace");
  }

  /** `GET /v1/workspace/windows/{id}` (`workspace:read`): one window; an unknown id is `not_found`. */
  workspaceWindow(options: WindowOptions): Promise<WorkspaceWindow> {
    return this.#get<WorkspaceWindow>(`workspace/windows/${windowPath(options.windowId)}`);
  }

  /**
   * `POST /v1/workspace/stacks` (`workspace:write`): a stack of the instrument
   * in a new tab or a new window, with a chart over it when `chart` is set.
   * The answer names the window, the tab and the new widgets. An instrument
   * the terminal's catalogue does not know is `invalid_request`.
   */
  openStack(options: OpenStackOptions): Promise<WorkspaceOutcome> {
    const body: OpenStackRequest = {
      instrument: options.instrument,
      connection_id: options.connectionId,
      chart: options.chart,
      target: options.target,
      window_id: options.windowId,
      activate: options.activate,
    };
    return this.#request<WorkspaceOutcome>("POST", "workspace/stacks", { body });
  }

  /**
   * `POST /v1/workspace/multiview` (`workspace:write`): a coin on every venue
   * of «Exchange layout», the same plan as the window's Multiview button. No
   * cell for the coin is `not_found`.
   */
  openMultiview(options: OpenMultiviewOptions): Promise<WorkspaceOutcome> {
    const body: OpenMultiviewRequest = {
      base: options.base,
      target: options.target,
      window_id: options.windowId,
      activate: options.activate,
    };
    return this.#request<WorkspaceOutcome>("POST", "workspace/multiview", { body });
  }

  /** `PATCH /v1/workspace/stacks/{widget_id}` (`workspace:write`): another instrument in the stack and its charts. */
  setStackInstrument(options: StackInstrumentOptions): Promise<WorkspaceOutcome> {
    const body: StackInstrumentRequest = { instrument: options.instrument, connection_id: options.connectionId };
    return this.#request<WorkspaceOutcome>("PATCH", `workspace/stacks/${windowPath(options.widgetId)}`, { body });
  }

  /** `DELETE /v1/workspace/stacks/{widget_id}` (`workspace:write`): close one stack, as its close button does. */
  closeStack(options: StackOptions): Promise<WorkspaceOutcome> {
    return this.#request<WorkspaceOutcome>("DELETE", `workspace/stacks/${windowPath(options.widgetId)}`, {});
  }

  /** `DELETE /v1/workspace/windows/{id}/tabs/{tab}` (`workspace:write`): the only tab of a window is `invalid_request`. */
  closeTab(options: TabOptions): Promise<WorkspaceOutcome> {
    return this.#request<WorkspaceOutcome>("DELETE", tabPath(options), {});
  }

  /** `POST /v1/workspace/windows/{id}/tabs/{tab}/activate` (`workspace:write`): select the tab; the window's focus is untouched. */
  activateTab(options: TabOptions): Promise<WorkspaceOutcome> {
    return this.#request<WorkspaceOutcome>("POST", `${tabPath(options)}/activate`, { body: {} });
  }

  /** `DELETE /v1/workspace/windows/{id}` (`workspace:write`): the main window is `invalid_request`. */
  closeWindow(options: WindowOptions): Promise<WorkspaceOutcome> {
    return this.#request<WorkspaceOutcome>("DELETE", `workspace/windows/${windowPath(options.windowId)}`, {});
  }

  /** `POST /v1/workspace/windows/{id}/activate` (`workspace:write`): restore if minimised and bring to the front. */
  activateWindow(options: WindowOptions): Promise<WorkspaceOutcome> {
    return this.#request<WorkspaceOutcome>("POST", `workspace/windows/${windowPath(options.windowId)}/activate`, {
      body: {},
    });
  }

  // --- settings ------------------------------------------------------------

  /**
   * `GET /v1/settings` (`settings:read`): rows as stored, without the default
   * ladder. Without options: the global rows without a connection. Each row
   * says whether it is `writable` through {@link updateSettings}.
   */
  settings(options: SettingsOptions = {}): Promise<Settings> {
    return this.#get<Settings>("settings", {
      scope: options.scope,
      category: options.category,
      key: options.key,
      connection_id: options.connectionId,
      instrument: options.instrument,
    });
  }

  /**
   * `GET /v1/settings/orderbook` (`settings:read`): the stack settings of an
   * instrument as its stack on the connection sees them — the pair's row, the
   * connection's default, the pair's row without a connection, the global
   * default — with `resolved_from` on every key.
   */
  orderbookSettings(options: InstrumentCommandOptions): Promise<OrderbookSettings> {
    return this.#get<OrderbookSettings>("settings/orderbook", {
      connection_id: options.connectionId,
      instrument: options.instrument,
    });
  }

  /**
   * `PATCH /v1/settings` (`settings:write`): write settings the way the
   * Settings App does. Every change is checked against the terminal's
   * catalogue first (`invalid_request` naming `changes[i]`, nothing written;
   * leverage is `unsupported` here — use {@link setLeverage}), then applied in
   * order: the same row, window event and service caches as the Settings App.
   * The first failed change rejects the call; earlier ones stay applied.
   */
  updateSettings(changes: SettingChange[]): Promise<SettingsApplied> {
    if (changes.length === 0) {
      throw new RangeError("changes must not be empty");
    }
    const body: UpdateSettingsRequest = { changes };
    return this.#request<SettingsApplied>("PATCH", "settings", { body });
  }

  /** Open `/v1/stream`. Node only: the token goes in the handshake header. */
  stream(options: StreamOptions = {}): Promise<Stream> {
    return Stream.connect({
      url: `ws://${authority(this.host, this.port)}/v1/stream`,
      token: this.#token,
      timeoutMs: options.timeoutMs ?? this.timeoutMs,
    });
  }

  /** Serialises without the token. */
  toJSON(): { host: string; port: number; timeoutMs: number } {
    return { host: this.host, port: this.port, timeoutMs: this.timeoutMs };
  }

  /** `util.inspect` output without the token. */
  [INSPECT](): string {
    return `Terminal { host: '${this.host}', port: ${this.port}, timeoutMs: ${this.timeoutMs}, token: <redacted> }`;
  }

  #get<T>(path: string, query?: Query): Promise<T> {
    return this.#request<T>("GET", path, { query });
  }

  async #request<T>(method: Method, path: string, options: RequestOptions): Promise<T> {
    const url = new URL(path, this.baseUrl);
    if (options.query !== undefined) {
      for (const [key, value] of Object.entries(options.query)) {
        if (value !== undefined) {
          url.searchParams.set(key, String(value));
        }
      }
    }
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.#token}`,
      Accept: "application/json",
    };
    if (method !== "GET") {
      headers["Content-Type"] = "application/json";
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers,
        // JSON.stringify leaves out `undefined` properties, so optional
        // fields that were not given are absent from the wire.
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        redirect: "error",
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (cause) {
      throw new TerminalUnreachableError(
        `${method} ${url.pathname} on ${authority(this.host, this.port)} got no answer: ${describeFailure(cause)}`,
        { cause },
      );
    }

    const text = await response.text();
    if (response.ok) {
      try {
        return JSON.parse(text) as T;
      } catch (cause) {
        throw new ApiError("unknown", `HTTP ${response.status} with a non-JSON body`, response.status, { cause });
      }
    }
    throw errorFrom(response.status, text);
  }
}

/** The wire body of `cancel-all` and `positions/close`. */
function instrumentCommand(options: InstrumentCommandOptions): InstrumentCommandRequest {
  return { connection_id: options.connectionId, instrument: options.instrument };
}

/** An id in a workspace path: an integer, never a string the server would refuse. */
function windowPath(id: number): string {
  if (!Number.isInteger(id) || id < 0) {
    throw new RangeError(`workspace ids are non-negative integers, got ${id}`);
  }
  return String(id);
}

function tabPath(options: TabOptions): string {
  return `workspace/windows/${windowPath(options.windowId)}/tabs/${windowPath(options.tabId)}`;
}

/** `host:port`, bracketing an IPv6 literal. */
function authority(host: string, port: number): string {
  return host.includes(":") && !host.startsWith("[") ? `[${host}]:${port}` : `${host}:${port}`;
}

/** Build the {@link ApiError} for a non-2xx body: the envelope, or `unknown`. */
function errorFrom(status: number, text: string): ApiError {
  try {
    const parsed: unknown = JSON.parse(text);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "error" in parsed &&
      typeof parsed.error === "object" &&
      parsed.error !== null
    ) {
      const envelope = parsed.error as Record<string, unknown>;
      if (typeof envelope.code === "string") {
        return new ApiError(
          envelope.code,
          typeof envelope.message === "string" ? envelope.message : "",
          status,
        );
      }
    }
  } catch {
    // Not JSON: fall through to the generic error.
  }
  return new ApiError("unknown", `HTTP ${status} without the error envelope`, status);
}

/** The reason `fetch` rejected, with the OS-level cause when there is one. */
function describeFailure(cause: unknown): string {
  if (!(cause instanceof Error)) {
    return String(cause);
  }
  if (cause.name === "TimeoutError") {
    return "request timed out";
  }
  const inner = cause.cause;
  if (inner instanceof Error && inner.message !== "") {
    return `${cause.message} (${inner.message})`;
  }
  return cause.message;
}
