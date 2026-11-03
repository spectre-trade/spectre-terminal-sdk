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
  url: URL;
  headers: IncomingHttpHeaders;
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
async function route(url: URL): Promise<Reply | undefined> {
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
    default:
      return envelope(404, "not_found", "no such operation");
  }
}

let server: Server;
let port: number;
const requests: Recorded[] = [];

before(async () => {
  server = createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "127.0.0.1"}`);
    requests.push({ url, headers: req.headers });
    const reply = await route(url);
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
