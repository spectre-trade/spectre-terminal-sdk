/**
 * The `/v1/stream` WebSocket client.
 *
 * {@link Stream} wraps Node's global `WebSocket` (undici, Node 22+). The token
 * travels in the handshake header, which browsers cannot set — and the API
 * refuses any request carrying an `Origin` header — so this module runs in
 * Node only. {@link StreamProtocol} is the socket-free part: request ids,
 * matching replies to requests and classifying incoming frames.
 *
 * @module
 */

import { StreamClosedError, StreamRequestError, TerminalUnreachableError } from "./errors.ts";
import type {
  BookTopParams,
  ErrorCode,
  Event,
  InstrumentAddress,
  StreamFrame,
  Subscribed,
  SubscribedFrame,
  SubscribeRequest,
  Topic,
  UnsubscribedFrame,
  UnsubscribeRequest,
} from "./types.ts";

/** Close codes after which iteration ends by throwing {@link StreamClosedError}. */
const FATAL_CLOSE_CODES: ReadonlySet<number> = new Set([
  1001, // the API was switched off or the token was reissued
  1006, // the connection dropped without a close frame
  4008, // this client read too slowly
  4029, // per-token connection limit
]);

/** Normal closure, used when the client closes without a code. */
const CLOSE_NORMAL = 1000;

/** How long `close()` waits for the server's close frame before giving up. */
const CLOSE_HANDSHAKE_TIMEOUT_MS = 3000;

const KNOWN_TOPICS: ReadonlySet<string> = new Set<Topic>([
  "trades",
  "ticker",
  "mark_price",
  "book.top",
  "clusters",
  "account.orders",
  "account.positions",
  "account.balances",
  "account.fills",
  "workspace",
]);

/** Account topics are keyed by connection, not instrument. */
function isAccountTopic(topic: Topic): boolean {
  return topic.startsWith("account.");
}

/** The layout topic takes neither instrument nor connection. */
function isWorkspaceTopic(topic: Topic): boolean {
  return topic === "workspace";
}

/**
 * Options of {@link Stream.subscribe}. Market topics (`trades`, `ticker`,
 * `mark_price`, `book.top`, `clusters`) take `instrument`, with
 * `connectionId` chosen by the general rule when omitted; account topics
 * (`account.*`) take `connectionId` and no instrument; `workspace` takes
 * neither and gets the current layout as its first frame.
 */
export interface SubscribeOptions {
  topic: Topic;
  /** Required for market topics; ignored for `account.*`. */
  instrument?: InstrumentAddress;
  /** Required for `account.*`; chosen by the general rule for market topics when omitted. */
  connectionId?: number;
  /** Only `book.top` reads them; wire names (`depth`, `interval_ms`). */
  params?: BookTopParams;
}

/** Options of {@link Stream.connect}. */
export interface StreamConnectOptions {
  /** `ws://127.0.0.1:48180/v1/stream`. */
  url: string;
  token: string;
  /** Handshake timeout; default 10 000. */
  timeoutMs?: number;
}

/** A reply the server sends to one of our requests. */
type ReplyFrame = SubscribedFrame | UnsubscribedFrame;

interface Pending {
  resolve: (frame: ReplyFrame) => void;
  reject: (error: Error) => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The topic of a subscription id: `"{stream}:{topic}"` or `"{connection}:account.<topic>"`. */
function topicOf(sub: string): Topic | undefined {
  const name = sub.slice(sub.indexOf(":") + 1);
  return KNOWN_TOPICS.has(name) ? (name as Topic) : undefined;
}

/**
 * The socket-free half of the stream protocol: hands out request ids, keeps
 * the requests waiting for a reply, settles them from `subscribed` /
 * `unsubscribed` / `error` frames and turns everything else into the frames
 * a consumer iterates. Pure, so it is unit-testable without a server.
 */
export class StreamProtocol {
  #counter = 0;
  readonly #pending = new Map<string, Pending>();

  /** A fresh `request_id`, unique within this stream. */
  nextRequestId(): string {
    this.#counter += 1;
    return `r${this.#counter}`;
  }

  /** Register a request and get the promise its reply will settle. */
  expect(requestId: string): Promise<ReplyFrame> {
    return new Promise<ReplyFrame>((resolve, reject) => {
      this.#pending.set(requestId, { resolve, reject });
    });
  }

  /** Requests still waiting for a reply. */
  get pendingCount(): number {
    return this.#pending.size;
  }

  /**
   * Classify a decoded frame. Replies to our requests settle the matching
   * promise and return `undefined`; `event`, `gap` and subscription errors
   * are returned for the consumer; anything unknown or malformed is dropped.
   */
  route(raw: unknown): StreamFrame | undefined {
    if (!isRecord(raw) || typeof raw.type !== "string") {
      return undefined;
    }
    switch (raw.type) {
      case "subscribed":
      case "unsubscribed":
        this.#settle(raw, (pending) => pending.resolve(raw as unknown as ReplyFrame));
        return undefined;
      case "error":
        return this.#routeError(raw);
      case "event":
        return this.#routeEvent(raw);
      case "gap":
        if (
          typeof raw.sub === "string" &&
          typeof raw.from_seq === "number" &&
          typeof raw.to_seq === "number"
        ) {
          return {
            type: "gap",
            sub: raw.sub,
            from_seq: raw.from_seq,
            to_seq: raw.to_seq,
            reason: typeof raw.reason === "string" ? raw.reason : "",
          };
        }
        return undefined;
      default:
        return undefined;
    }
  }

  /** Reject every waiting request, e.g. when the socket closes. */
  abortAll(error: Error): void {
    for (const pending of this.#pending.values()) {
      pending.reject(error);
    }
    this.#pending.clear();
  }

  #settle(raw: Record<string, unknown>, settle: (pending: Pending) => void): boolean {
    if (typeof raw.request_id !== "string") {
      return false;
    }
    const pending = this.#pending.get(raw.request_id);
    if (pending === undefined) {
      return false;
    }
    this.#pending.delete(raw.request_id);
    settle(pending);
    return true;
  }

  #routeError(raw: Record<string, unknown>): StreamFrame | undefined {
    const code = typeof raw.code === "string" ? (raw.code as ErrorCode) : "unknown";
    const message = typeof raw.message === "string" ? raw.message : "";
    if (this.#settle(raw, (pending) => pending.reject(new StreamRequestError(code, message)))) {
      return undefined;
    }
    if (typeof raw.request_id === "undefined" && typeof raw.sub === "string") {
      return { type: "error", sub: raw.sub, code, message };
    }
    // An error that answers no request of ours and names no subscription:
    // outside the contract, nothing to attach it to.
    return undefined;
  }

  #routeEvent(raw: Record<string, unknown>): Event | undefined {
    if (typeof raw.sub !== "string" || typeof raw.seq !== "number" || typeof raw.ts !== "number") {
      return undefined;
    }
    // The topic is read from `sub` ("{stream}:{topic}"); the data shape
    // follows the topic by contract, so the cast only names what the server
    // promised.
    return {
      type: "event",
      topic: topicOf(raw.sub),
      sub: raw.sub,
      seq: raw.seq,
      ts: raw.ts,
      data: raw.data,
    } as Event;
  }
}

/**
 * A live `/v1/stream` connection.
 *
 * Obtain one with `terminal.stream()`. Subscribe with {@link subscribe}, then
 * iterate: `for await (const frame of stream)` yields events, gaps and
 * subscription errors in arrival order, buffered without limit while the
 * consumer is busy (the server protects itself: a client that lags for more
 * than 5 s is closed with `4008`). One consumer iterates at a time; a second
 * concurrent `next()` simply waits its turn.
 *
 * When the server closes the connection, iteration ends; for `1001`, `4008`,
 * `4029` and a lost connection (`1006`) it ends by throwing
 * {@link StreamClosedError}. {@link closeCode} and {@link closeReason} are
 * set either way. Closing from the client ({@link close}, or `break` out of
 * the loop) ends iteration normally.
 */
export class Stream implements AsyncIterable<StreamFrame> {
  readonly #socket: WebSocket;
  readonly #protocol = new StreamProtocol();
  readonly #queue: StreamFrame[] = [];
  #waiters: Array<() => void> = [];
  #closeCode: number | undefined;
  #closeReason: string | undefined;
  #closedByClient = false;
  #closeDelivered = false;
  #closeResolvers: Array<() => void> = [];

  private constructor(socket: WebSocket) {
    this.#socket = socket;
    socket.addEventListener("message", (event) => this.#onMessage(event));
    socket.addEventListener("close", (event) => this.#onClose(event.code, event.reason));
    // After "open", undici follows every "error" with a "close": the close
    // handler carries the state, nothing to do here but keep the event
    // from being reported as unhandled.
    socket.addEventListener("error", () => undefined);
  }

  /**
   * Open the WebSocket and complete the handshake. Rejects with
   * {@link TerminalUnreachableError} when the terminal does not accept it:
   * Node's `WebSocket` reports a refused handshake (terminal down, API off,
   * token rejected) as one generic failure, so the three are not told apart.
   */
  static connect(options: StreamConnectOptions): Promise<Stream> {
    const timeoutMs = options.timeoutMs ?? 10_000;
    const socket = new WebSocket(options.url, {
      headers: { Authorization: `Bearer ${options.token}` },
    });
    return new Promise<Stream>((resolve, reject) => {
      let settled = false;
      const settle = (outcome: () => void): void => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        outcome();
      };
      const fail = (message: string, cause?: unknown): void =>
        settle(() => reject(new TerminalUnreachableError(message, cause === undefined ? undefined : { cause })));

      const timer = setTimeout(() => {
        socket.close();
        fail(`WebSocket handshake with ${options.url} timed out after ${timeoutMs} ms`);
      }, timeoutMs);

      socket.addEventListener("open", () => settle(() => resolve(new Stream(socket))), { once: true });
      socket.addEventListener(
        "error",
        (event) => {
          const detail = describeErrorEvent(event);
          fail(
            `WebSocket handshake with ${options.url} failed${detail ? ` (${detail})` : ""}: the terminal is not running, its Local API is switched off, or the token was rejected`,
            event,
          );
        },
        { once: true },
      );
      socket.addEventListener(
        "close",
        (event) => fail(`WebSocket to ${options.url} closed during the handshake with code ${event.code}`),
        { once: true },
      );
    });
  }

  /** The stream URL (never carries the token). */
  get url(): string {
    return this.#socket.url;
  }

  /** `true` once the socket is closed, whoever closed it. */
  get closed(): boolean {
    return this.#closeCode !== undefined;
  }

  /** WebSocket close code, once closed. */
  get closeCode(): number | undefined {
    return this.#closeCode;
  }

  /** WebSocket close reason, once closed. */
  get closeReason(): string | undefined {
    return this.#closeReason;
  }

  /**
   * Subscribe to a topic of an instrument, or to an account topic of a
   * connection. Resolves with the server's `subscribed` frame (plus the
   * requested `topic` and, for market topics, `instrument`) and rejects with
   * {@link StreamRequestError} on the server's `error` reply; events of other
   * subscriptions keep flowing meanwhile. Note the terminal's limit on new
   * exchange subscriptions per second (`/v1/meta`); account topics do not
   * touch the exchange and send no snapshot frame — read the current state
   * with the `/v1/account/*` operations first.
   */
  async subscribe(options: SubscribeOptions): Promise<Subscribed> {
    const account = isAccountTopic(options.topic);
    const workspace = isWorkspaceTopic(options.topic);
    const request: SubscribeRequest = {
      type: "subscribe",
      request_id: this.#protocol.nextRequestId(),
      topic: options.topic,
    };
    if (!account && !workspace && options.instrument !== undefined) {
      request.instrument = options.instrument;
    }
    if (!workspace && options.connectionId !== undefined) {
      request.connection_id = options.connectionId;
    }
    if (options.params !== undefined) {
      request.params = options.params;
    }
    const reply = (await this.#send(request)) as SubscribedFrame;
    const subscribed: Subscribed = { ...reply, topic: options.topic };
    if (request.instrument !== undefined) {
      subscribed.instrument = request.instrument;
    }
    return subscribed;
  }

  /**
   * Remove a subscription immediately. Accepts the value `subscribe` resolved
   * with or the bare `sub` id. Resolves on the server's `unsubscribed`.
   */
  async unsubscribe(subscription: Subscribed | SubscribedFrame | string): Promise<void> {
    const request: UnsubscribeRequest = {
      type: "unsubscribe",
      request_id: this.#protocol.nextRequestId(),
      sub: typeof subscription === "string" ? subscription : subscription.sub,
    };
    await this.#send(request);
  }

  /**
   * Close the stream. The server completes the close handshake with the
   * client's code; the promise resolves when it has, or after a short grace
   * period if it never does. Safe to call more than once.
   */
  close(code: number = CLOSE_NORMAL, reason?: string): Promise<void> {
    if (this.closed) {
      return Promise.resolve();
    }
    this.#closedByClient = true;
    const done = new Promise<void>((resolve) => {
      this.#closeResolvers.push(resolve);
    });
    if (this.#socket.readyState === WebSocket.CONNECTING || this.#socket.readyState === WebSocket.OPEN) {
      try {
        this.#socket.close(code, reason);
      } catch {
        // An invalid code or reason: the socket stays open, so close it
        // without them rather than leave the connection dangling.
        this.#socket.close();
      }
    }
    const grace = new Promise<void>((resolve) => {
      setTimeout(() => {
        this.#onClose(1006, "close handshake timed out");
        resolve();
      }, CLOSE_HANDSHAKE_TIMEOUT_MS).unref();
    });
    return Promise.race([done, grace]);
  }

  /** Frames in arrival order; see the class description for how it ends. */
  [Symbol.asyncIterator](): AsyncIterator<StreamFrame> {
    return {
      next: () => this.#next(),
      return: async () => {
        await this.close();
        return { value: undefined, done: true };
      },
    };
  }

  async #next(): Promise<IteratorResult<StreamFrame>> {
    for (;;) {
      const frame = this.#queue.shift();
      if (frame !== undefined) {
        return { value: frame, done: false };
      }
      if (this.closed) {
        if (!this.#closeDelivered && !this.#closedByClient && FATAL_CLOSE_CODES.has(this.#closeCode ?? 1006)) {
          this.#closeDelivered = true;
          throw new StreamClosedError(this.#closeCode ?? 1006, this.#closeReason ?? "");
        }
        this.#closeDelivered = true;
        return { value: undefined, done: true };
      }
      await new Promise<void>((resolve) => {
        this.#waiters.push(resolve);
      });
    }
  }

  #send(request: SubscribeRequest | UnsubscribeRequest): Promise<ReplyFrame> {
    if (this.closed) {
      return Promise.reject(new StreamClosedError(this.#closeCode ?? 1006, this.#closeReason ?? ""));
    }
    const reply = this.#protocol.expect(request.request_id);
    try {
      this.#socket.send(JSON.stringify(request));
    } catch (cause) {
      this.#protocol.abortAll(
        new StreamClosedError(1006, cause instanceof Error ? cause.message : "send failed"),
      );
    }
    return reply;
  }

  #onMessage(event: MessageEvent): void {
    if (typeof event.data !== "string") {
      return;
    }
    let raw: unknown;
    try {
      raw = JSON.parse(event.data);
    } catch {
      return;
    }
    const frame = this.#protocol.route(raw);
    if (frame !== undefined) {
      this.#queue.push(frame);
      this.#wake();
    }
  }

  #onClose(code: number, reason: string): void {
    if (this.closed) {
      return;
    }
    this.#closeCode = code;
    this.#closeReason = reason;
    this.#protocol.abortAll(new StreamClosedError(code, reason));
    this.#wake();
    const resolvers = this.#closeResolvers;
    this.#closeResolvers = [];
    for (const resolve of resolvers) {
      resolve();
    }
  }

  #wake(): void {
    const waiters = this.#waiters;
    this.#waiters = [];
    for (const wake of waiters) {
      wake();
    }
  }
}

/** The text of an undici `ErrorEvent`, if it carries one. */
function describeErrorEvent(event: unknown): string {
  if (!isRecord(event)) {
    return "";
  }
  if (typeof event.message === "string" && event.message !== "") {
    return event.message;
  }
  const error = event.error;
  return error instanceof Error ? error.message : "";
}
