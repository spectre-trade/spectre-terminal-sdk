/**
 * The stream client against a scripted `ws` server, plus the socket-free
 * `StreamProtocol` on its own.
 */

import assert from "node:assert/strict";
import type { AddressInfo } from "node:net";
import { after, before, test } from "node:test";

import { WebSocketServer, type WebSocket as ServerSocket } from "ws";

import {
  StreamClosedError,
  StreamProtocol,
  StreamRequestError,
  Terminal,
  TerminalUnreachableError,
  type AccountOrdersEvent,
  type Gap,
  type StreamFrame,
  type SubscriptionError,
  type Topic,
  type TradesEvent,
  type SettingsEvent,
  type WorkspaceEvent,
} from "../src/index.ts";

const TOKEN = `spt_${"ef".repeat(32)}`;
const TRADE = { id: null, price: "67000.1", qty: "0.012", side: "buy", ts: 1730294400125, exchange_ts: 1730294400119 };
const ORDER = {
  key: "t-123456789012345678",
  exchange_id: "987654321",
  instrument: "binance:futures:BTCUSDT",
  side: "buy",
  type: "limit",
  price: "67000.1",
  size: "0.012",
  filled: "0",
  remaining: "0.012",
  notional: "804",
  status: "open",
  created_ts: 1730294400123,
};
const FILL = {
  trade_id: "t1",
  order_id: "987654321",
  instrument: "binance:futures:BTCUSDT",
  side: "buy",
  price: "67000.1",
  qty: "0.012",
  fee: "0.32",
  fee_currency: "USDT",
  position_side: "long",
  ts: 1730294400123,
};

const WORKSPACE = {
  windows: [
    {
      id: 1,
      main: true,
      chart_window: false,
      focused: true,
      geometry: { x: 0, y: 0, width: 1920, height: 1080, maximized: true },
      monitor: null,
      tabs: [{ id: 1, name: "XRP", active: true, stacks: [], charts: [] }],
    },
  ],
};

let wss: WebSocketServer;
let port: number;
/** Every request the server received, decoded. */
const received: Array<Record<string, unknown>> = [];

function send(socket: ServerSocket, frame: Record<string, unknown>): void {
  socket.send(JSON.stringify(frame));
}

/** The script: what the fake terminal answers to each request. */
function serve(socket: ServerSocket, request: Record<string, unknown>): void {
  received.push(request);
  const requestId = request.request_id;
  if (request.type === "unsubscribe") {
    send(socket, { type: "unsubscribed", request_id: requestId, sub: request.sub });
    return;
  }
  if (request.type !== "subscribe") {
    send(socket, { type: "error", request_id: requestId, code: "invalid_request", message: "unknown request" });
    return;
  }
  const topic = String(request.topic);
  if (topic.startsWith("account.")) {
    serveAccount(socket, request, topic);
    return;
  }
  if (topic === "settings") {
    if ("instrument" in request || "connection_id" in request) {
      send(socket, { type: "error", request_id: requestId, code: "invalid_request", message: "settings takes no instrument" });
      return;
    }
    send(socket, { type: "subscribed", request_id: requestId, sub: "settings" });
    send(socket, {
      type: "event",
      sub: "settings",
      seq: 1,
      ts: 1730294400150,
      data: { scope: "global", scope_id: "default", connection_id: null, category: "multiview", key: "stack_width_px", value: 260 },
    });
    return;
  }
  if (topic === "workspace") {
    if ("instrument" in request || "connection_id" in request) {
      send(socket, { type: "error", request_id: requestId, code: "invalid_request", message: "workspace takes no instrument" });
      return;
    }
    send(socket, { type: "subscribed", request_id: requestId, sub: "workspace" });
    send(socket, { type: "event", sub: "workspace", seq: 1, ts: 1730294400140, data: WORKSPACE });
    return;
  }
  if (typeof request.instrument !== "string") {
    send(socket, { type: "error", request_id: requestId, code: "invalid_request", message: "instrument is required" });
    return;
  }
  const instrument = request.instrument;
  if (instrument.startsWith("none:")) {
    send(socket, { type: "error", request_id: requestId, code: "not_found", message: "no connection for the instrument" });
    return;
  }
  const sub = `7:${topic}`;
  send(socket, { type: "subscribed", request_id: requestId, sub, connection_id: 12 });
  if (instrument.startsWith("slow:")) {
    socket.close(4008, "slow consumer");
    return;
  }
  if (instrument.startsWith("drop:")) {
    send(socket, { type: "error", sub, code: "unavailable", message: "the venue refused" });
    return;
  }
  if (topic === "trades") {
    send(socket, { type: "event", sub, seq: 1, ts: 1730294400130, data: [TRADE] });
    send(socket, { type: "gap", sub, from_seq: 2, to_seq: 3, reason: "slow_consumer" });
    send(socket, { type: "event", sub, seq: 4, ts: 1730294400131, data: [TRADE, TRADE] });
  } else if (topic === "book.top") {
    send(socket, {
      type: "event",
      sub,
      seq: 10,
      ts: 1730294400132,
      data: { ts: 1730294400123, depth: 1, bids: [["67000.1", "1.25"]], asks: [["67000.2", "0.40"]] },
    });
  }
}

/** Account topics: keyed by connection, `instrument` must be absent. */
function serveAccount(socket: ServerSocket, request: Record<string, unknown>, topic: string): void {
  const requestId = request.request_id;
  if (typeof request.connection_id !== "number" || "instrument" in request) {
    send(socket, { type: "error", request_id: requestId, code: "invalid_request", message: "connection_id, no instrument" });
    return;
  }
  const sub = `${request.connection_id}:${topic}`;
  send(socket, { type: "subscribed", request_id: requestId, sub, connection_id: request.connection_id });
  if (topic === "account.orders") {
    send(socket, {
      type: "event",
      sub,
      seq: 5,
      ts: 1730294400130,
      data: { instrument: ORDER.instrument, orders: [ORDER], triggers: [] },
    });
  } else if (topic === "account.fills") {
    send(socket, { type: "event", sub, seq: 1, ts: 1730294400131, data: FILL });
  }
}

before(async () => {
  wss = new WebSocketServer({
    host: "127.0.0.1",
    port: 0,
    verifyClient: (info, done) => {
      if (info.req.headers.authorization === `Bearer ${TOKEN}` && info.req.headers.origin === undefined) {
        done(true);
      } else {
        done(false, 401, "Unauthorized");
      }
    },
  });
  wss.on("connection", (socket) => {
    socket.on("message", (data) => serve(socket, JSON.parse(String(data)) as Record<string, unknown>));
  });
  await new Promise<void>((resolve) => wss.once("listening", resolve));
  port = (wss.address() as AddressInfo).port;
});

after(async () => {
  for (const client of wss.clients) client.terminate();
  await new Promise<void>((resolve) => wss.close(() => resolve()));
});

function terminal(token = TOKEN): Terminal {
  return new Terminal({ token, port, timeoutMs: 2000 });
}

async function take(iterator: AsyncIterator<StreamFrame>, count: number): Promise<StreamFrame[]> {
  const frames: StreamFrame[] = [];
  while (frames.length < count) {
    const result = await iterator.next();
    assert.equal(result.done, false, "stream ended early");
    frames.push(result.value as StreamFrame);
  }
  return frames;
}

test("subscribe resolves and frames arrive in order, tagged by topic", async () => {
  const stream = await terminal().stream();
  assert.equal(stream.closed, false);
  assert.ok(stream.url.endsWith("/v1/stream"));

  const subscribed = await stream.subscribe({
    topic: "trades",
    instrument: "binance:futures:BTCUSDT",
    connectionId: 12,
  });
  assert.equal(subscribed.sub, "7:trades");
  assert.equal(subscribed.connection_id, 12);
  assert.equal(subscribed.topic, "trades");
  assert.equal(subscribed.instrument, "binance:futures:BTCUSDT");
  assert.equal(received.at(-1)?.connection_id, 12);
  assert.equal(received.at(-1)?.params, undefined);
  assert.equal(typeof received.at(-1)?.request_id, "string");

  const iterator = stream[Symbol.asyncIterator]();
  const [first, second, third] = (await take(iterator, 3)) as [TradesEvent, Gap, TradesEvent];
  assert.equal(first.type, "event");
  assert.equal(first.topic, "trades");
  assert.equal(first.seq, 1);
  assert.equal(first.data[0]?.price, "67000.1");
  assert.equal(second.type, "gap");
  assert.deepEqual([second.from_seq, second.to_seq, second.reason], [2, 3, "slow_consumer"]);
  assert.equal(third.seq, 4);
  assert.equal(third.data.length, 2);

  await stream.close();
  assert.equal(stream.closed, true);
  assert.equal(stream.closeCode, 1000);
  assert.deepEqual(await iterator.next(), { value: undefined, done: true });
});

test("book.top passes params and yields a book frame", async () => {
  const stream = await terminal().stream();
  const subscribed = await stream.subscribe({
    topic: "book.top",
    instrument: "binance:futures:BTCUSDT",
    params: { depth: 1, interval_ms: 200 },
  });
  assert.equal(subscribed.sub, "7:book.top");
  assert.deepEqual(received.at(-1)?.params, { depth: 1, interval_ms: 200 });

  for await (const frame of stream) {
    assert.equal(frame.type, "event");
    if (frame.type === "event" && frame.topic === "book.top") {
      assert.deepEqual(frame.data.bids[0], ["67000.1", "1.25"]);
      assert.equal(frame.seq, 10);
    } else {
      assert.fail(`unexpected frame ${JSON.stringify(frame)}`);
    }
    break; // leaving the loop closes the stream
  }
  assert.equal(stream.closed, true);
  assert.equal(stream.closeCode, 1000);
});

test("account topics send connection_id and no instrument; the sub id is {connection}:account.<topic>", async () => {
  const stream = await terminal().stream();

  const fills = await stream.subscribe({ topic: "account.fills", connectionId: 12 });
  assert.equal(fills.sub, "12:account.fills");
  assert.equal(fills.topic, "account.fills");
  assert.equal(fills.connection_id, 12);
  assert.equal(fills.instrument, undefined);
  assert.ok(!("instrument" in fills));
  const request = received.at(-1)!;
  assert.equal(request.topic, "account.fills");
  assert.equal(request.connection_id, 12);
  assert.ok(!("instrument" in request));

  // An instrument given with an account topic is dropped, not sent.
  const orders = await stream.subscribe({ topic: "account.orders", connectionId: 12, instrument: "binance:futures:BTCUSDT" });
  assert.equal(orders.sub, "12:account.orders");
  assert.ok(!("instrument" in received.at(-1)!));

  const frames = await take(stream[Symbol.asyncIterator](), 2);
  const fill = frames[0]!;
  assert.ok(fill.type === "event" && fill.topic === "account.fills");
  assert.equal(fill.data.trade_id, "t1");
  assert.equal(fill.data.position_side, "long");

  const update = frames[1] as AccountOrdersEvent;
  assert.equal(update.type, "event");
  assert.equal(update.topic, "account.orders");
  assert.equal(update.sub, "12:account.orders");
  assert.equal(update.seq, 5);
  assert.equal(update.data.instrument, "binance:futures:BTCUSDT");
  assert.equal(update.data.orders[0]?.key, "t-123456789012345678");
  assert.deepEqual(update.data.triggers, []);

  // Narrowing by topic in a loop, as a consumer writes it.
  for (const frame of frames) {
    if (frame.type === "event" && frame.topic === "account.orders") {
      assert.equal(frame.data.orders.length, 1);
    } else if (frame.type === "event" && frame.topic === "account.fills") {
      assert.equal(frame.data.qty, "0.012");
    } else {
      assert.fail(`unexpected frame ${JSON.stringify(frame)}`);
    }
  }

  // A market topic without an instrument is the server's error, not the client's.
  const error = await stream.subscribe({ topic: "trades", connectionId: 12 }).catch((e: unknown) => e);
  assert.ok(error instanceof StreamRequestError);
  assert.equal(error.code, "invalid_request");
  await stream.close();
});

test("a subscribe error rejects with StreamRequestError and leaves the stream usable", async () => {
  const stream = await terminal().stream();
  const error = await stream.subscribe({ topic: "trades", instrument: "none:spot:XYZ" }).catch((e: unknown) => e);
  assert.ok(error instanceof StreamRequestError);
  assert.equal(error.code, "not_found");
  assert.equal(error.detail, "no connection for the instrument");
  assert.equal(stream.closed, false);

  const subscribed = await stream.subscribe({ topic: "ticker", instrument: "binance:futures:BTCUSDT" });
  assert.equal(subscribed.sub, "7:ticker");
  await stream.close();
});

test("a server close with 4008 makes iteration throw StreamClosedError", async () => {
  const stream = await terminal().stream();
  await stream.subscribe({ topic: "trades", instrument: "slow:futures:BTCUSDT" });
  const error = await (async () => {
    for await (const frame of stream) {
      assert.fail(`unexpected frame ${JSON.stringify(frame)}`);
    }
  })().catch((e: unknown) => e);
  assert.ok(error instanceof StreamClosedError);
  assert.equal(error.code, 4008);
  assert.equal(error.reason, "slow consumer");
  assert.equal(stream.closeCode, 4008);
  assert.equal(stream.closeReason, "slow consumer");

  // The fatal close is reported once; afterwards the iterator is simply done.
  assert.deepEqual(await stream[Symbol.asyncIterator]().next(), { value: undefined, done: true });
  const late = await stream.subscribe({ topic: "trades", instrument: "binance:futures:BTCUSDT" }).catch((e: unknown) => e);
  assert.ok(late instanceof StreamClosedError);
  assert.equal(late.code, 4008);
  await stream.close(); // idempotent
});

test("an error frame with sub and no request_id is a SubscriptionError frame", async () => {
  const stream = await terminal().stream();
  const subscribed = await stream.subscribe({ topic: "trades", instrument: "drop:futures:BTCUSDT" });
  const [frame] = (await take(stream[Symbol.asyncIterator](), 1)) as [SubscriptionError];
  assert.equal(frame.type, "error");
  assert.equal(frame.sub, subscribed.sub);
  assert.equal(frame.code, "unavailable");
  assert.equal(frame.message, "the venue refused");
  await stream.close();
});

test("unsubscribe resolves on the server's unsubscribed", async () => {
  const stream = await terminal().stream();
  const subscribed = await stream.subscribe({ topic: "mark_price", instrument: "binance:futures:BTCUSDT" });
  await stream.unsubscribe(subscribed);
  assert.deepEqual(
    (({ type, sub }) => ({ type, sub }))(received.at(-1) as { type: string; sub: string }),
    { type: "unsubscribe", sub: "7:mark_price" },
  );
  await stream.unsubscribe("7:mark_price");
  assert.equal(received.at(-1)?.sub, "7:mark_price");
  await stream.close();
});

test("a rejected handshake is TerminalUnreachableError", async () => {
  const error = await terminal(`spt_${"00".repeat(32)}`).stream().catch((e: unknown) => e);
  assert.ok(error instanceof TerminalUnreachableError, String(error));
  assert.ok(error.message.includes("token"), error.message);
  assert.ok(!error.message.includes("00".repeat(32)));
});

test("a closed port is TerminalUnreachableError", async () => {
  const probe = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await new Promise<void>((resolve) => probe.once("listening", resolve));
  const closedPort = (probe.address() as AddressInfo).port;
  await new Promise<void>((resolve) => probe.close(() => resolve()));

  const error = await new Terminal({ token: TOKEN, port: closedPort, timeoutMs: 2000 }).stream().catch((e: unknown) => e);
  assert.ok(error instanceof TerminalUnreachableError, String(error));
});

// --- StreamProtocol, no socket ----------------------------------------------

test("StreamProtocol matches replies to requests", async () => {
  const protocol = new StreamProtocol();
  const r1 = protocol.nextRequestId();
  const r2 = protocol.nextRequestId();
  assert.notEqual(r1, r2);

  const subscribed = protocol.expect(r1);
  const failed = protocol.expect(r2);
  assert.equal(protocol.pendingCount, 2);

  assert.equal(protocol.route({ type: "subscribed", request_id: r1, sub: "7:trades", connection_id: 12 }), undefined);
  assert.deepEqual(await subscribed, { type: "subscribed", request_id: r1, sub: "7:trades", connection_id: 12 });

  assert.equal(protocol.route({ type: "error", request_id: r2, code: "rate_limited", message: "ceiling" }), undefined);
  const error = await failed.catch((e: unknown) => e);
  assert.ok(error instanceof StreamRequestError);
  assert.equal(error.code, "rate_limited");
  assert.equal(protocol.pendingCount, 0);

  // A reply to a request we never made is dropped.
  assert.equal(protocol.route({ type: "subscribed", request_id: "r99", sub: "1:x", connection_id: 1 }), undefined);
  assert.equal(protocol.route({ type: "error", request_id: "r99", code: "x", message: "" }), undefined);
});

test("StreamProtocol classifies events, gaps and subscription errors", () => {
  const protocol = new StreamProtocol();
  const event = protocol.route({ type: "event", sub: "7:trades", seq: 3, ts: 5, data: [TRADE] });
  assert.ok(event && event.type === "event");
  assert.equal(event.topic, "trades");
  assert.equal(event.seq, 3);

  for (const topic of ["ticker", "mark_price", "book.top", "clusters"] as Topic[]) {
    const frame = protocol.route({ type: "event", sub: `7:${topic}`, seq: 1, ts: 1, data: {} });
    assert.ok(frame && frame.type === "event");
    assert.equal(frame.topic, topic);
  }
  for (const topic of ["account.orders", "account.positions", "account.balances", "account.fills"] as Topic[]) {
    const frame = protocol.route({ type: "event", sub: `12:${topic}`, seq: 1, ts: 1, data: {} });
    assert.ok(frame && frame.type === "event");
    assert.equal(frame.topic, topic);
    assert.equal(frame.sub, `12:${topic}`);
  }

  const unknown = protocol.route({ type: "event", sub: "7:future_topic", seq: 1, ts: 1, data: {} });
  assert.ok(unknown && unknown.type === "event");
  assert.equal(unknown.topic, undefined);
  assert.equal(unknown.sub, "7:future_topic");

  assert.deepEqual(protocol.route({ type: "gap", sub: "7:trades", from_seq: 4, to_seq: 9, reason: "slow_consumer" }), {
    type: "gap",
    sub: "7:trades",
    from_seq: 4,
    to_seq: 9,
    reason: "slow_consumer",
  });
  assert.deepEqual(protocol.route({ type: "error", sub: "7:trades", code: "unavailable", message: "gone" }), {
    type: "error",
    sub: "7:trades",
    code: "unavailable",
    message: "gone",
  });

  // Malformed or unknown frames are dropped.
  assert.equal(protocol.route(null), undefined);
  assert.equal(protocol.route("text"), undefined);
  assert.equal(protocol.route({ type: "event", sub: 7 }), undefined);
  assert.equal(protocol.route({ type: "gap", sub: "7:trades" }), undefined);
  assert.equal(protocol.route({ type: "error", code: "x", message: "no sub, no request" }), undefined);
  assert.equal(protocol.route({ type: "pong" }), undefined);
});

test("StreamProtocol.abortAll rejects every waiting request", async () => {
  const protocol = new StreamProtocol();
  const a = protocol.expect(protocol.nextRequestId());
  const b = protocol.expect(protocol.nextRequestId());
  protocol.abortAll(new StreamClosedError(1001, "going away"));
  for (const pending of [a, b]) {
    const error = await pending.catch((e: unknown) => e);
    assert.ok(error instanceof StreamClosedError);
    assert.equal(error.code, 1001);
  }
  assert.equal(protocol.pendingCount, 0);
});

test("workspace subscribes without instrument or connection and gets the snapshot first", async () => {
  const stream = await terminal().stream();
  const subscribed = await stream.subscribe({ topic: "workspace" });
  assert.equal(subscribed.sub, "workspace");
  assert.equal(subscribed.topic, "workspace");
  assert.equal(subscribed.connection_id, undefined);
  const request = received.at(-1)!;
  assert.equal(request.topic, "workspace");
  assert.ok(!("instrument" in request) && !("connection_id" in request));

  // An instrument given with the workspace topic is dropped, not sent.
  const again = await stream.subscribe({ topic: "workspace", instrument: "binance:futures:BTCUSDT", connectionId: 12 });
  assert.equal(again.sub, "workspace");
  assert.ok(!("instrument" in received.at(-1)!) && !("connection_id" in received.at(-1)!));

  const frames: StreamFrame[] = [];
  for await (const frame of stream) {
    frames.push(frame);
    break;
  }
  const event = frames[0] as WorkspaceEvent;
  assert.equal(event.type, "event");
  assert.equal(event.topic, "workspace");
  assert.equal(event.sub, "workspace");
  assert.equal(event.data.windows[0]?.tabs[0]?.name, "XRP");
  await stream.close();
});

test("settings subscribes like workspace and types the written row", async () => {
  const stream = await terminal().stream();
  const subscribed = await stream.subscribe({ topic: "settings", connectionId: 12 });
  assert.equal(subscribed.sub, "settings");
  assert.equal(subscribed.topic, "settings");
  assert.equal(subscribed.connection_id, undefined);
  const request = received.at(-1)!;
  assert.ok(!("instrument" in request) && !("connection_id" in request));
  const frames: StreamFrame[] = [];
  for await (const frame of stream) {
    frames.push(frame);
    break;
  }
  const event = frames[0] as SettingsEvent;
  assert.equal(event.topic, "settings");
  assert.equal(event.data.key, "stack_width_px");
  assert.equal(event.data.value, 260);
  assert.equal(event.data.writable, undefined);
  await stream.close();
});
