/**
 * The REST client of Local API v1.
 *
 * {@link Terminal} wraps the global `fetch` (Node 22+). Every request carries
 * `Authorization: Bearer <token>` and `Accept: application/json`, nothing
 * else; redirects are refused and each request has a timeout. The token
 * lives in a private field and never appears in errors, `JSON.stringify` or
 * `util.inspect` output.
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
  Candles,
  Clusters,
  Connection,
  Health,
  InstrumentAddress,
  Instrument,
  InstrumentsPage,
  Intervals,
  List,
  Meta,
  Orderbook,
  Snapshot,
  Trades,
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

/** Options of {@link Terminal.stream}. */
export interface StreamOptions {
  /** Handshake timeout; defaults to the client's `timeoutMs`. */
  timeoutMs?: number;
}

type Query = Record<string, string | number | undefined>;

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

  async #get<T>(path: string, query?: Query): Promise<T> {
    const url = new URL(path, this.baseUrl);
    if (query !== undefined) {
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined) {
          url.searchParams.set(key, String(value));
        }
      }
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${this.#token}`,
          Accept: "application/json",
        },
        redirect: "error",
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (cause) {
      throw new TerminalUnreachableError(
        `GET ${url.pathname} on ${authority(this.host, this.port)} got no answer: ${describeFailure(cause)}`,
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
