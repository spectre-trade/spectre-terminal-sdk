/**
 * REST client against a fake terminal on a random loopback port. The server
 * records every request so the tests can assert headers, paths and query
 * strings; bodies are the contract fixtures.
 */

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer, type IncomingHttpHeaders, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, test } from "node:test";
import { inspect } from "node:util";

import { ApiError, SpectreTerminalError, Terminal, TerminalUnreachableError } from "../src/index.ts";

const FIXTURES = new URL("../../contract/fixtures/", import.meta.url);
const TOKEN = `spt_${"ab".repeat(32)}`;
const INSTRUMENT = "binance:futures:BTCUSDT";

interface Recorded {
  method: string;
  url: URL;
  headers: IncomingHttpHeaders;
  /** The request body, decoded; `undefined` without one. */
  body: unknown;
}

interface Reply {
  status: number;
  body: string;
  headers?: Record<string, string>;
}

const fixtureCache = new Map<string, string>();
async function fixture(name: string): Promise<string> {
  let text = fixtureCache.get(name);
  if (text === undefined) {
    text = await readFile(new URL(`${name}.json`, FIXTURES), "utf8");
    fixtureCache.set(name, text);
  }
  return text;
}

function envelope(status: number, code: string, message: string): Reply {
  return {
    status,
    body: JSON.stringify({ error: { code, message } }),
    headers: status === 401 ? { "WWW-Authenticate": "Bearer" } : {},
  };
}

async function json(name: string): Promise<Reply> {
  return { status: 200, body: await fixture(name) };
}

/** Routes of the fake terminal; `undefined` means "never answer". */
async function route(method: string, url: URL, body: unknown): Promise<Reply | undefined> {
  if (url.pathname === "/v1/account/leverage" && method === "GET") {
    return json("leverage");
  }
  if (url.pathname.startsWith("/v1/orders") || WRITE_PATHS.has(url.pathname)) {
    return routeWrite(method, url, body);
  }
  if (url.pathname.startsWith("/v1/workspace")) {
    return routeWorkspace(method, url, body);
  }
  switch (url.pathname) {
    case "/v1/meta":
      return json("meta");
    case "/v1/health":
      return json("health");
    case "/v1/connections":
      return json("connections");
    case "/v1/connections/12":
      return json("connection");
    case "/v1/connections/401":
      return envelope(401, "unauthorized", "token does not match");
    case "/v1/connections/404":
      return envelope(404, "not_found", "no such connection");
    case "/v1/connections/429":
      return envelope(429, "rate_limited", "slow down");
    case "/v1/connections/500":
      return { status: 500, body: "boom", headers: { "Content-Type": "text/plain" } };
    case "/v1/connections/302":
      return { status: 302, body: "", headers: { Location: "http://example.invalid/" } };
    case "/v1/connections/200":
      return { status: 200, body: "not json", headers: { "Content-Type": "text/plain" } };
    case "/v1/connections/hang":
      return undefined;
    case "/v1/instruments": {
      const page = JSON.parse(await fixture("instruments")) as {
        data: Array<Record<string, unknown>>;
        next_cursor: string | null;
      };
      const first = page.data[0]!;
      if (url.searchParams.get("cursor") === "BTCUSDT") {
        return {
          status: 200,
          body: JSON.stringify({ ...page, data: [{ ...first, symbol: "ETHUSDT" }], next_cursor: null }),
        };
      }
      return { status: 200, body: JSON.stringify({ ...page, next_cursor: "BTCUSDT" }) };
    }
    case "/v1/market/intervals":
      return json("intervals");
    case "/v1/market/candles":
      return json("candles");
    case "/v1/market/trades":
      return json("trades");
    case "/v1/market/snapshot":
      return json("snapshot");
    case "/v1/market/orderbook":
      return json("orderbook");
    case "/v1/market/clusters":
      return json("clusters");
    case "/v1/account/orders":
      return json("account_orders");
    case "/v1/account/positions":
      return json("account_positions");
    case "/v1/account/balances":
      return json("account_balances");
    case "/v1/account/fills":
      return json("account_fills");
    default:
      return envelope(404, "not_found", "no such operation");
  }
}

/** Writes outside `/v1/orders`; `/v1/account/leverage` is a read on `GET`. */
const WRITE_PATHS = new Set(["/v1/positions/close", "/v1/account/leverage", "/v1/account/margin-mode"]);

/** Paths whose write is a `POST`; `/v1/orders/{id}` is `DELETE`, `/v1/orders/trigger/{id}` `DELETE` or `PATCH`. */
const POST_PATHS = new Set([
  "/v1/orders",
  "/v1/orders/cancel-all",
  "/v1/orders/trigger",
  "/v1/orders/trigger/cancel-all",
  "/v1/positions/close",
  "/v1/account/leverage",
  "/v1/account/margin-mode",
]);

/** Writes: `connection_id` 409 is a connection that does not trade, 429 a busy listener. */
async function routeWrite(method: string, url: URL, body: unknown): Promise<Reply> {
  const connectionId =
    typeof body === "object" && body !== null && "connection_id" in body
      ? body.connection_id
      : Number(url.searchParams.get("connection_id"));
  if (connectionId === 409) {
    return envelope(409, "not_tradable", "connection 409 is read-only");
  }
  if (connectionId === 429) {
    return envelope(429, "rate_limited", "10 commands per second");
  }
  const isTriggerItem = url.pathname.startsWith("/v1/orders/trigger/") && url.pathname !== "/v1/orders/trigger/cancel-all";
  const allowed = POST_PATHS.has(url.pathname) ? ["POST"] : isTriggerItem ? ["DELETE", "PATCH"] : ["DELETE"];
  if (!allowed.includes(method)) {
    return envelope(404, "not_found", `${method} ${url.pathname} is not an operation`);
  }
  const accepted = JSON.parse(await fixture("accepted")) as Record<string, unknown>;
  const key =
    url.pathname === "/v1/orders" ? accepted.key : url.pathname === "/v1/orders/trigger" ? "sl_1730294400123" : null;
  return { status: 200, body: JSON.stringify({ ...accepted, key }) };
}

/**
 * `/v1/workspace*`: reads from the fixtures, writes answer the outcome fixture.
 * Window 1 with tab 1 exists, stack 12 exists; the main window and the only
 * tab refuse to close like the terminal does.
 */
async function routeWorkspace(method: string, url: URL, body: unknown): Promise<Reply> {
  const parts = url.pathname.split("/").slice(3); // after /v1/workspace
  const outcome = JSON.parse(await fixture("workspace_outcome")) as Record<string, unknown>;
  const reply = (patch: Record<string, unknown>): Reply => ({ status: 200, body: JSON.stringify({ ...outcome, ...patch }) });
  if (method === "GET") {
    if (parts.length === 0) return json("workspace");
    if (parts[0] === "windows" && parts[1] === "1" && parts.length === 2) return json("workspace_window");
    return envelope(404, "not_found", "no such window");
  }
  if (method === "POST" && parts.length === 1 && parts[0] === "stacks") {
    const instrument = typeof body === "object" && body !== null && "instrument" in body ? body.instrument : undefined;
    if (instrument === "binance:futures:NOPE") return envelope(400, "invalid_request", "unknown instrument");
    return reply({});
  }
  if (method === "POST" && parts.length === 1 && parts[0] === "multiview") return reply({});
  if (parts[0] === "stacks" && parts.length === 2) {
    if (parts[1] !== "12") return envelope(404, "not_found", "no stack with this widget_id");
    if (method === "PATCH" || method === "DELETE") return reply({ stacks: [12], charts: [] });
  }
  if (parts[0] === "windows" && parts.length >= 2) {
    if (parts[1] !== "1") return envelope(404, "not_found", "no such window");
    if (parts.length === 2 && method === "DELETE") return envelope(400, "invalid_request", "the main window cannot be closed");
    if (parts.length === 3 && parts[2] === "activate" && method === "POST") return reply({ tab_id: null, stacks: [], charts: [] });
    if (parts[2] === "tabs" && (parts.length === 4 || parts.length === 5)) {
      if (parts[3] !== "1") return envelope(404, "not_found", "no such tab");
      if (parts.length === 4 && method === "DELETE") return envelope(400, "invalid_request", "the only tab");
      if (parts.length === 5 && parts[4] === "activate" && method === "POST") return reply({ tab_id: 1, stacks: [], charts: [] });
    }
  }
  return envelope(404, "not_found", "no such operation");
}

let server: Server;
let port: number;
const requests: Recorded[] = [];

before(async () => {
  server = createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "127.0.0.1"}`);
    const chunks: Buffer[] = [];
    for await (const chunk of req) {
      chunks.push(chunk as Buffer);
    }
    const text = Buffer.concat(chunks).toString("utf8");
    const body: unknown = text === "" ? undefined : JSON.parse(text);
    requests.push({ method: req.method ?? "", url, headers: req.headers, body });
    const reply = await route(req.method ?? "", url, body);
    if (reply === undefined) {
      return; // leave the request open until the client gives up
    }
    res.writeHead(reply.status, { "Content-Type": "application/json", ...reply.headers });
    res.end(reply.body);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  port = (server.address() as AddressInfo).port;
});

after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

function terminal(options: { timeoutMs?: number } = {}): Terminal {
  return new Terminal({ token: TOKEN, port, ...options });
}

function last(): Recorded {
  const recorded = requests.at(-1);
  assert.ok(recorded, "no request recorded");
  return recorded;
}

function params(url: URL): Record<string, string> {
  return Object.fromEntries(url.searchParams.entries());
}

test("sends only Authorization and Accept, never Origin", async () => {
  const meta = await terminal().meta();
  assert.equal(meta.api_version, "1");
  const { url, headers } = last();
  assert.equal(url.pathname, "/v1/meta");
  assert.equal(headers.authorization, `Bearer ${TOKEN}`);
  assert.equal(headers.accept, "application/json");
  assert.equal(headers.origin, undefined);
  assert.equal(headers.cookie, undefined);
});

test("health, connections and connection hit their paths", async () => {
  const t = terminal();
  const health = await t.health();
  assert.equal(health.status, "ok");
  assert.equal(last().url.pathname, "/v1/health");

  const { data } = await t.connections();
  assert.equal(data[0]?.id, 12);
  assert.equal(data[0]?.status.state, "connected");
  assert.equal(last().url.pathname, "/v1/connections");

  const connection = await t.connection(12);
  assert.equal(connection.exchange, "binance");
  assert.equal(last().url.pathname, "/v1/connections/12");
});

test("instruments passes every option under its wire name", async () => {
  const t = terminal();
  const page = await t.instruments({ exchange: "binance", market: "futures", q: "btc", limit: 10 });
  assert.equal(page.exchange, "binance");
  assert.equal(page.data[0]?.tick_size, "0.1");
  assert.equal(last().url.pathname, "/v1/instruments");
  assert.deepEqual(params(last().url), { exchange: "binance", market: "futures", q: "btc", limit: "10" });

  await t.instruments({ connectionId: 12, cursor: "BTCUSDT" });
  assert.deepEqual(params(last().url), { connection_id: "12", cursor: "BTCUSDT" });
});

test("iterInstruments follows next_cursor across pages", async () => {
  const symbols: string[] = [];
  const before = requests.length;
  for await (const instrument of terminal().iterInstruments({ exchange: "binance", market: "futures" })) {
    symbols.push(instrument.symbol);
  }
  assert.deepEqual(symbols, ["BTCUSDT", "ETHUSDT"]);
  const pages = requests.slice(before);
  assert.equal(pages.length, 2);
  assert.equal(pages[0]?.url.searchParams.get("cursor"), null);
  assert.equal(pages[1]?.url.searchParams.get("cursor"), "BTCUSDT");
});

test("intervals and candles", async () => {
  const t = terminal();
  const intervals = await t.intervals();
  assert.equal(intervals.candles[0]?.id, "1m");
  assert.equal(last().url.pathname, "/v1/market/intervals");

  const candles = await t.candles(INSTRUMENT, { interval: "1m", limit: 10, end: 1730294400000, connectionId: 12 });
  assert.equal(candles.data[0]?.open, "67000.1");
  assert.equal(last().url.pathname, "/v1/market/candles");
  assert.deepEqual(params(last().url), {
    instrument: INSTRUMENT,
    connection_id: "12",
    interval: "1m",
    limit: "10",
    end: "1730294400000",
  });
});

test("trades, snapshot, orderbook and clusters", async () => {
  const t = terminal();

  const trades = await t.trades(INSTRUMENT, { limit: 5, sinceTs: 1730294400000 });
  assert.equal(trades.data[0]?.price, "67000.1");
  assert.equal(trades.data[0]?.id, null);
  assert.equal(last().url.pathname, "/v1/market/trades");
  assert.deepEqual(params(last().url), { instrument: INSTRUMENT, limit: "5", since_ts: "1730294400000" });

  await t.trades(INSTRUMENT);
  assert.deepEqual(params(last().url), { instrument: INSTRUMENT });

  const snapshot = await t.snapshot(INSTRUMENT, { connectionId: 12 });
  assert.deepEqual(snapshot.best_bid, ["67000.1", "1.25"]);
  assert.equal(typeof snapshot.mark_price, "string");
  assert.equal(last().url.pathname, "/v1/market/snapshot");
  assert.deepEqual(params(last().url), { instrument: INSTRUMENT, connection_id: "12" });

  const book = await t.orderbook(INSTRUMENT, { depth: 20 });
  assert.deepEqual(book.bids[0], ["67000.1", "1.25"]);
  assert.equal(last().url.pathname, "/v1/market/orderbook");
  assert.deepEqual(params(last().url), { instrument: INSTRUMENT, depth: "20" });

  const clusters = await t.clusters(INSTRUMENT);
  assert.equal(clusters.data[0]?.levels[0]?.price, "67000.1");
  assert.equal(last().url.pathname, "/v1/market/clusters");
  assert.deepEqual(params(last().url), { instrument: INSTRUMENT });
});

test("account reads pass connection_id and the fills options", async () => {
  const t = terminal();

  const orders = await t.accountOrders(12);
  assert.equal(orders.connection_id, 12);
  assert.equal(orders.data[0]?.key, "t-123456789012345678");
  assert.equal(orders.data[0]?.type, "limit");
  assert.equal(orders.triggers[0]?.type, "stop_loss");
  assert.equal(last().method, "GET");
  assert.equal(last().url.pathname, "/v1/account/orders");
  assert.deepEqual(params(last().url), { connection_id: "12" });

  const positions = await t.accountPositions(12);
  assert.equal(positions.data[0]?.side, "long");
  assert.equal(positions.data[0]?.mark_price, "67000");
  assert.equal(last().url.pathname, "/v1/account/positions");
  assert.deepEqual(params(last().url), { connection_id: "12" });

  const balances = await t.accountBalances(12);
  assert.equal(balances.data[0]?.currency, "USDT");
  assert.equal(balances.data[0]?.total, "1000.5");
  assert.equal(last().url.pathname, "/v1/account/balances");
  assert.deepEqual(params(last().url), { connection_id: "12" });

  const fills = await t.accountFills(12, { limit: 50, sinceTs: 1730294400000 });
  assert.equal(fills.data[0]?.trade_id, "t1");
  assert.equal(fills.data[0]?.position_side, "long");
  assert.equal(last().url.pathname, "/v1/account/fills");
  assert.deepEqual(params(last().url), { connection_id: "12", limit: "50", since_ts: "1730294400000" });

  await t.accountFills(12);
  assert.deepEqual(params(last().url), { connection_id: "12" });
});

test("placeOrder posts the body under wire names, leaving out what was not given", async () => {
  const t = terminal();

  const accepted = await t.placeOrder({
    connectionId: 12,
    instrument: INSTRUMENT,
    side: "buy",
    type: "limit",
    price: "67000.1",
    size: "0.012",
    reduceOnly: false,
    postOnly: true,
    timeInForce: "gtc",
    clientKey: "bot-42",
  });
  assert.equal(accepted.accepted, true);
  assert.equal(accepted.key, "t-173029440012300001");
  assert.equal(accepted.operation_id, "1730294400123-000001");
  const { method, url, headers, body } = last();
  assert.equal(method, "POST");
  assert.equal(url.pathname, "/v1/orders");
  assert.equal(url.search, "");
  assert.equal(headers["content-type"], "application/json");
  assert.equal(headers.accept, "application/json");
  assert.equal(headers.authorization, `Bearer ${TOKEN}`);
  assert.equal(headers.origin, undefined);
  assert.deepEqual(body, {
    connection_id: 12,
    instrument: INSTRUMENT,
    side: "buy",
    type: "limit",
    price: "67000.1",
    size: "0.012",
    reduce_only: false,
    post_only: true,
    time_in_force: "gtc",
    client_key: "bot-42",
  });

  await t.placeOrder({ connectionId: 12, instrument: INSTRUMENT, side: "sell", type: "market", notional: "100" });
  assert.deepEqual(last().body, {
    connection_id: 12,
    instrument: INSTRUMENT,
    side: "sell",
    type: "market",
    notional: "100",
  });
});

test("cancelOrder deletes /v1/orders/{id} with the connection and instrument in the query", async () => {
  const t = terminal();

  const accepted = await t.cancelOrder({ connectionId: 12, instrument: INSTRUMENT, orderId: "t-173029440012300001" });
  assert.equal(accepted.key, null);
  assert.equal(last().method, "DELETE");
  assert.equal(last().url.pathname, "/v1/orders/t-173029440012300001");
  assert.deepEqual(params(last().url), { connection_id: "12", instrument: INSTRUMENT });
  assert.equal(last().body, undefined);

  await t.cancelOrder({ connectionId: 12, instrument: INSTRUMENT, orderId: "987654321" });
  assert.equal(last().url.pathname, "/v1/orders/987654321");

  await t.cancelOrder({ connectionId: 12, instrument: INSTRUMENT, orderId: "a/b?c" });
  assert.equal(last().url.pathname, "/v1/orders/a%2Fb%3Fc");
  assert.deepEqual(params(last().url), { connection_id: "12", instrument: INSTRUMENT });
});

test("cancelAll and closePosition post the instrument command", async () => {
  const t = terminal();

  await t.cancelAll({ connectionId: 12, instrument: INSTRUMENT });
  assert.equal(last().method, "POST");
  assert.equal(last().url.pathname, "/v1/orders/cancel-all");
  assert.equal(last().headers["content-type"], "application/json");
  assert.deepEqual(last().body, { connection_id: 12, instrument: INSTRUMENT });

  const accepted = await t.closePosition({ connectionId: 12, instrument: INSTRUMENT });
  assert.equal(accepted.instrument, INSTRUMENT);
  assert.equal(last().method, "POST");
  assert.equal(last().url.pathname, "/v1/positions/close");
  assert.deepEqual(last().body, { connection_id: 12, instrument: INSTRUMENT });
});

test("placeTrigger posts the trigger body; stop fields only when given", async () => {
  const t = terminal();

  const accepted = await t.placeTrigger({
    connectionId: 12,
    instrument: INSTRUMENT,
    kind: "stop_loss",
    triggerPrice: "66000",
    clientKey: "sl-42",
  });
  assert.equal(accepted.key, "sl_1730294400123");
  assert.equal(last().method, "POST");
  assert.equal(last().url.pathname, "/v1/orders/trigger");
  assert.deepEqual(last().body, {
    connection_id: 12,
    instrument: INSTRUMENT,
    kind: "stop_loss",
    trigger_price: "66000",
    client_key: "sl-42",
  });

  await t.placeTrigger({
    connectionId: 12,
    instrument: INSTRUMENT,
    kind: "stop",
    side: "sell",
    notional: "800",
    triggerPrice: "66000",
    rule: "price_below_or_equal",
  });
  assert.deepEqual(last().body, {
    connection_id: 12,
    instrument: INSTRUMENT,
    kind: "stop",
    trigger_price: "66000",
    side: "sell",
    notional: "800",
    rule: "price_below_or_equal",
  });
});

test("cancelTrigger, amendTrigger and cancelAllTriggers address the trigger by its numeric id", async () => {
  const t = terminal();

  let accepted = await t.cancelTrigger({ connectionId: 12, instrument: INSTRUMENT, triggerId: 42 });
  assert.equal(accepted.key, null);
  assert.equal(last().method, "DELETE");
  assert.equal(last().url.pathname, "/v1/orders/trigger/42");
  assert.deepEqual(params(last().url), { connection_id: "12", instrument: INSTRUMENT });
  assert.equal(last().body, undefined);

  accepted = await t.amendTrigger({
    connectionId: 12,
    instrument: INSTRUMENT,
    triggerId: "42",
    kind: "stop",
    side: "sell",
    triggerPrice: "65500",
  });
  assert.equal(accepted.key, null);
  assert.equal(last().method, "PATCH");
  assert.equal(last().url.pathname, "/v1/orders/trigger/42");
  assert.equal(last().headers["content-type"], "application/json");
  assert.deepEqual(last().body, {
    connection_id: 12,
    instrument: INSTRUMENT,
    kind: "stop",
    trigger_price: "65500",
    side: "sell",
  });

  await t.cancelAllTriggers({ connectionId: 12, instrument: INSTRUMENT });
  assert.equal(last().method, "POST");
  assert.equal(last().url.pathname, "/v1/orders/trigger/cancel-all");
  assert.deepEqual(last().body, { connection_id: 12, instrument: INSTRUMENT });
});

test("leverage reads the cache; setLeverage and setMarginMode post the command", async () => {
  const t = terminal();

  const leverage = await t.leverage({ connectionId: 12, instrument: INSTRUMENT });
  assert.equal(last().method, "GET");
  assert.equal(last().url.pathname, "/v1/account/leverage");
  assert.deepEqual(params(last().url), { connection_id: "12", instrument: INSTRUMENT });
  assert.equal(leverage.leverage, 10);
  assert.equal(leverage.max_leverage, 125);
  assert.equal(leverage.mode, "manual");
  assert.equal(leverage.margin_mode, "cross");

  let accepted = await t.setLeverage({ connectionId: 12, instrument: INSTRUMENT, leverage: 20 });
  assert.equal(accepted.key, null);
  assert.equal(last().method, "POST");
  assert.equal(last().url.pathname, "/v1/account/leverage");
  assert.deepEqual(last().body, { connection_id: 12, instrument: INSTRUMENT, leverage: 20 });

  await t.setLeverage({ connectionId: 12, instrument: INSTRUMENT, mode: "max" });
  assert.deepEqual(last().body, { connection_id: 12, instrument: INSTRUMENT, mode: "max" });

  accepted = await t.setMarginMode({ connectionId: 12, instrument: INSTRUMENT, marginMode: "isolated" });
  assert.equal(accepted.key, null);
  assert.equal(last().url.pathname, "/v1/account/margin-mode");
  assert.deepEqual(last().body, { connection_id: 12, instrument: INSTRUMENT, margin_mode: "isolated" });
});

test("not_tradable and rate_limited on writes are ApiErrors without the token", async () => {
  const t = terminal();
  const order = { instrument: INSTRUMENT, side: "buy", type: "limit", price: "1", size: "1" } as const;

  const notTradable = await t.placeOrder({ connectionId: 409, ...order }).catch((e: unknown) => e);
  assert.ok(notTradable instanceof ApiError);
  assert.equal(notTradable.code, "not_tradable");
  assert.equal(notTradable.status, 409);
  assert.equal(notTradable.detail, "connection 409 is read-only");

  const cancelRefused = await t
    .cancelOrder({ connectionId: 409, instrument: INSTRUMENT, orderId: "t-1" })
    .catch((e: unknown) => e);
  assert.ok(cancelRefused instanceof ApiError);
  assert.equal(cancelRefused.code, "not_tradable");

  const limited = await t.cancelAll({ connectionId: 429, instrument: INSTRUMENT }).catch((e: unknown) => e);
  assert.ok(limited instanceof ApiError);
  assert.equal(limited.code, "rate_limited");
  assert.equal(limited.status, 429);

  for (const error of [notTradable, cancelRefused, limited]) {
    assert.ok(!String(error).includes(TOKEN));
    assert.ok(!inspect(error, { depth: 10 }).includes(TOKEN));
  }
});

test("non-2xx with the envelope is an ApiError with code and status", async () => {
  const t = terminal();
  for (const [status, code] of [
    [401, "unauthorized"],
    [404, "not_found"],
    [429, "rate_limited"],
  ] as const) {
    const error = await t.connection(status).catch((e: unknown) => e);
    assert.ok(error instanceof ApiError, `expected ApiError for ${status}`);
    assert.ok(error instanceof SpectreTerminalError);
    assert.equal(error.code, code);
    assert.equal(error.status, status);
    assert.equal(error.name, "ApiError");
    assert.ok(error.message.includes(code));
  }
});

test("a non-JSON error body is an ApiError with code unknown", async () => {
  const error = await terminal().connection(500).catch((e: unknown) => e);
  assert.ok(error instanceof ApiError);
  assert.equal(error.code, "unknown");
  assert.equal(error.status, 500);
});

test("a 2xx with a non-JSON body is an ApiError with code unknown", async () => {
  const error = await terminal().connection(200).catch((e: unknown) => e);
  assert.ok(error instanceof ApiError);
  assert.equal(error.code, "unknown");
  assert.equal(error.status, 200);
});

test("a redirect is refused", async () => {
  const error = await terminal().connection(302).catch((e: unknown) => e);
  assert.ok(error instanceof TerminalUnreachableError);
});

test("a timeout is TerminalUnreachableError", async () => {
  const error = await terminal({ timeoutMs: 200 }).connection("hang" as unknown as number).catch((e: unknown) => e);
  assert.ok(error instanceof TerminalUnreachableError);
  assert.ok(error.message.includes("timed out"), error.message);
});

test("a closed port is TerminalUnreachableError", async () => {
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const closedPort = (probe.address() as AddressInfo).port;
  await new Promise<void>((resolve) => probe.close(() => resolve()));

  const error = await new Terminal({ token: TOKEN, port: closedPort }).meta().catch((e: unknown) => e);
  assert.ok(error instanceof TerminalUnreachableError);
  assert.equal(error.name, "TerminalUnreachableError");
  assert.ok(error.message.includes(String(closedPort)));
});

test("the token never leaks into errors, inspect or JSON", async () => {
  const t = terminal();
  const apiError = await t.connection(401).catch((e: unknown) => e);
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const closedPort = (probe.address() as AddressInfo).port;
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  const unreachable = await new Terminal({ token: TOKEN, port: closedPort }).meta().catch((e: unknown) => e);

  for (const error of [apiError, unreachable]) {
    assert.ok(error instanceof Error);
    assert.ok(!String(error).includes(TOKEN));
    assert.ok(!inspect(error, { depth: 10 }).includes(TOKEN));
  }
  assert.ok(!inspect(t).includes(TOKEN));
  assert.ok(inspect(t).includes("<redacted>"));
  assert.ok(!JSON.stringify(t).includes(TOKEN));
  assert.deepEqual(JSON.parse(JSON.stringify(t)), { host: "127.0.0.1", port, timeoutMs: 10_000 });
  assert.ok(!t.baseUrl.includes(TOKEN));
});

test("constructor defaults and an empty token", () => {
  const t = new Terminal({ token: TOKEN });
  assert.equal(t.host, "127.0.0.1");
  assert.equal(t.port, 48180);
  assert.equal(t.timeoutMs, 10_000);
  assert.equal(t.baseUrl, "http://127.0.0.1:48180/v1/");
  assert.throws(() => new Terminal({ token: "" }), { name: "TokenMissingError" });
});

test("workspace reads the snapshot and one window", async () => {
  const t = terminal();
  const workspace = await t.workspace();
  assert.equal(last().method, "GET");
  assert.equal(last().url.pathname, "/v1/workspace");
  const main = workspace.data.windows.find((w) => w.main)!;
  assert.equal(main.id, 1);
  assert.equal(main.geometry.width, 1920);
  assert.equal(main.tabs[0]?.name, "XRP");
  assert.equal(main.tabs[0]?.stacks[0]?.widget_id, 12);
  assert.equal(main.tabs[0]?.charts[0]?.interval, "5m");

  const window = await t.workspaceWindow({ windowId: 1 });
  assert.equal(last().url.pathname, "/v1/workspace/windows/1");
  assert.equal(window.data.main, true);

  const missing = await t.workspaceWindow({ windowId: 2 }).catch((e: unknown) => e);
  assert.ok(missing instanceof ApiError);
  assert.equal(missing.code, "not_found");
  assert.throws(() => t.workspaceWindow({ windowId: 1.5 }), RangeError);
});

test("openStack and openMultiview post their bodies; refusals keep their codes", async () => {
  const t = terminal();
  const outcome = await t.openStack({ instrument: INSTRUMENT, chart: true, windowId: 1, activate: false });
  assert.equal(last().method, "POST");
  assert.equal(last().url.pathname, "/v1/workspace/stacks");
  assert.deepEqual(last().body, { instrument: INSTRUMENT, chart: true, window_id: 1, activate: false });
  assert.deepEqual([outcome.window_id, outcome.tab_id, outcome.stacks], [1, 2, [14]]);

  await t.openStack({ instrument: INSTRUMENT, connectionId: 12, target: "new_window" });
  assert.deepEqual(last().body, { instrument: INSTRUMENT, connection_id: 12, target: "new_window" });

  await t.openMultiview({ base: "BTC" });
  assert.equal(last().url.pathname, "/v1/workspace/multiview");
  assert.deepEqual(last().body, { base: "BTC" });
  await t.openMultiview({ base: "BTC", target: "new_tab", windowId: 1, activate: false });
  assert.deepEqual(last().body, { base: "BTC", target: "new_tab", window_id: 1, activate: false });

  const refused = await t.openStack({ instrument: "binance:futures:NOPE" }).catch((e: unknown) => e);
  assert.ok(refused instanceof ApiError);
  assert.equal(refused.code, "invalid_request");
});

test("stack, tab and window commands use their routes", async () => {
  const t = terminal();
  const repointed = await t.setStackInstrument({ widgetId: 12, instrument: INSTRUMENT, connectionId: 12 });
  assert.equal(last().method, "PATCH");
  assert.equal(last().url.pathname, "/v1/workspace/stacks/12");
  assert.deepEqual(last().body, { instrument: INSTRUMENT, connection_id: 12 });
  assert.deepEqual(repointed.stacks, [12]);

  await t.closeStack({ widgetId: 12 });
  assert.equal(last().method, "DELETE");
  assert.equal(last().url.pathname, "/v1/workspace/stacks/12");
  assert.equal(last().body, undefined);

  await t.activateTab({ windowId: 1, tabId: 1 });
  assert.equal(last().method, "POST");
  assert.equal(last().url.pathname, "/v1/workspace/windows/1/tabs/1/activate");

  await t.activateWindow({ windowId: 1 });
  assert.equal(last().url.pathname, "/v1/workspace/windows/1/activate");

  const onlyTab = await t.closeTab({ windowId: 1, tabId: 1 }).catch((e: unknown) => e);
  assert.ok(onlyTab instanceof ApiError);
  assert.equal(onlyTab.code, "invalid_request");
  assert.equal(last().method, "DELETE");
  assert.equal(last().url.pathname, "/v1/workspace/windows/1/tabs/1");

  const mainWindow = await t.closeWindow({ windowId: 1 }).catch((e: unknown) => e);
  assert.ok(mainWindow instanceof ApiError);
  assert.equal(mainWindow.code, "invalid_request");

  const noStack = await t.closeStack({ widgetId: 99 }).catch((e: unknown) => e);
  assert.ok(noStack instanceof ApiError);
  assert.equal(noStack.code, "not_found");
});
