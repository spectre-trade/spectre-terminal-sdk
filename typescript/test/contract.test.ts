/**
 * The fixtures in `contract/fixtures/` are the terminal's own responses, one
 * per operation. This checklist mirrors `src/types.ts` at runtime: every
 * field a fixture carries must be known here with the right kind, and every
 * field named here must be in the fixture. A fixture that gains a field
 * fails until `types.ts` and this file learn it; a fixture that loses one
 * fails too — that is a v2 change, not a v1 one.
 */

import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { test } from "node:test";

const FIXTURES = new URL("../../contract/fixtures/", import.meta.url);

/** Scalar kinds; a trailing `?` allows `null`. */
type Kind = "string" | "decimal" | "int" | "bool" | "side" | "state";

/** A spec: a kind, an object shape (a key ending in `?` may be absent), an array of, a pair, or nullable. */
type Spec =
  | Kind
  | `${Kind}?`
  | Nullable
  | { readonly [key: string]: Spec }
  | readonly [Spec]
  | readonly [Spec, Spec];

class Nullable {
  readonly spec: Spec;
  constructor(spec: Spec) {
    this.spec = spec;
  }
}

const nullable = (spec: Spec): Nullable => new Nullable(spec);

const DECIMAL = /^-?\d+(\.\d+)?$/;
const STATES = new Set(["disabled", "enabled", "connecting", "connected", "failed"]);

function checkKind(value: unknown, kind: Kind, path: string, failures: string[]): void {
  const fail = (expected: string): void => {
    failures.push(`${path}: expected ${expected}, got ${JSON.stringify(value)}`);
  };
  switch (kind) {
    case "string":
      if (typeof value !== "string") fail("a string");
      break;
    case "decimal":
      if (typeof value !== "string" || !DECIMAL.test(value)) fail("a decimal string");
      break;
    case "int":
      if (typeof value !== "number" || !Number.isInteger(value)) fail("an integer");
      break;
    case "bool":
      if (typeof value !== "boolean") fail("a boolean");
      break;
    case "side":
      if (value !== "buy" && value !== "sell") fail('"buy" or "sell"');
      break;
    case "state":
      if (typeof value !== "string" || !STATES.has(value)) fail("a connection state");
      break;
  }
}

function check(value: unknown, spec: Spec, path: string, failures: string[]): void {
  if (typeof spec === "string") {
    const optional = spec.endsWith("?");
    if (optional && value === null) return;
    checkKind(value, (optional ? spec.slice(0, -1) : spec) as Kind, path, failures);
    return;
  }
  if (spec instanceof Nullable) {
    if (value !== null) check(value, spec.spec, path, failures);
    return;
  }
  if (Array.isArray(spec)) {
    if (!Array.isArray(value)) {
      failures.push(`${path}: expected an array, got ${JSON.stringify(value)}`);
      return;
    }
    if (spec.length === 2) {
      if (value.length !== 2) {
        failures.push(`${path}: expected a pair, got ${value.length} elements`);
        return;
      }
      check(value[0], spec[0], `${path}[0]`, failures);
      check(value[1], spec[1], `${path}[1]`, failures);
      return;
    }
    value.forEach((item, index) => check(item, spec[0], `${path}[${index}]`, failures));
    return;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    failures.push(`${path}: expected an object, got ${JSON.stringify(value)}`);
    return;
  }
  const record = value as Record<string, unknown>;
  const known = new Set<string>();
  for (const [rawKey, fieldSpec] of Object.entries(spec as { readonly [key: string]: Spec })) {
    const optional = rawKey.endsWith("?");
    const key = optional ? rawKey.slice(0, -1) : rawKey;
    known.add(key);
    if (!(key in record)) {
      if (!optional) failures.push(`${path}.${key}: missing`);
      continue;
    }
    check(record[key], fieldSpec, `${path}.${key}`, failures);
  }
  for (const key of Object.keys(record)) {
    if (!known.has(key)) {
      failures.push(`${path}.${key}: present in the fixture but unknown to types.ts`);
    }
  }
}

// --- Shapes, mirroring src/types.ts ------------------------------------------

const limits = {
  ws_connections_per_token: "int",
  subscriptions_per_connection: "int",
  api_only_instruments: "int",
  exchange_subscriptions_per_second: "int",
} as const;

const meta = {
  api_version: "string",
  app_version: "string",
  build_hash: "string",
  build_env: "string",
  features: "string",
  scopes: ["string"],
  limits,
  topics: ["string"],
} as const;

const health = {
  status: "string",
  uptime_ms: "int",
  clients: "int",
  streams: "int",
  api_only_instruments: "int",
  dropped_events: "int",
  dropped_frames: "int",
  overflow_closes: "int",
  stream_available: "bool",
} as const;

const connectionEvent = { code: "string", ts: "int" } as const;

const connection = {
  id: "int",
  exchange: "string",
  market: "string",
  label: "string",
  enabled: "bool",
  read_only: "bool",
  has_credentials: "bool",
  proxy_bound: "bool",
  status: { state: "state", "last_event?": connectionEvent },
} as const;

const instrument = {
  instrument: "string",
  exchange: "string",
  market: "string",
  symbol: "string",
  base: "string",
  quote: "string",
  status: "string",
  tick_size: "decimal?",
  lot_size: "decimal?",
  min_size: "decimal?",
  contract_value: "decimal?",
} as const;

const instrumentsPage = {
  exchange: "string",
  market: "string",
  data: [instrument],
  next_cursor: "string?",
} as const;

const candle = {
  ts: "int",
  open: "decimal",
  high: "decimal",
  low: "decimal",
  close: "decimal",
  volume: "decimal",
  quote_volume: "decimal",
  closed: "bool",
} as const;

const candles = {
  instrument: "string",
  connection_id: "int",
  interval: "string",
  data: [candle],
} as const;

const interval = { id: "string", duration_ms: "int" } as const;

const intervals = { candles: [interval], clusters: [interval] } as const;

const trade = {
  id: "string?",
  price: "decimal",
  qty: "decimal",
  side: "side",
  ts: "int",
  exchange_ts: "int",
} as const;

const trades = { instrument: "string", connection_id: "int", data: [trade] } as const;

const level = ["decimal", "decimal"] as const;

const ticker = {
  price: "decimal",
  change_24h_pct: "decimal?",
  volume_24h: "decimal",
  high_24h: "decimal?",
  low_24h: "decimal?",
  best_bid: "decimal?",
  best_ask: "decimal?",
  ts: "int",
} as const;

const snapshot = {
  instrument: "string",
  connection_id: "int",
  ts: "int",
  best_bid: nullable(level),
  best_ask: nullable(level),
  last_trade: nullable(trade),
  mark_price: "decimal?",
  ticker: nullable(ticker),
} as const;

const orderbook = {
  instrument: "string",
  connection_id: "int",
  ts: "int",
  depth: "int",
  bids: [level],
  asks: [level],
} as const;

const clusterLevel = {
  price: "decimal",
  volume: "decimal",
  buy_volume: "decimal",
  sell_volume: "decimal",
  buy_trades: "int",
  sell_trades: "int",
} as const;

const clusterBucket = {
  interval: "string",
  ts: "int",
  end_ts: "int",
  volume: "decimal",
  buy_volume: "decimal",
  sell_volume: "decimal",
  trades: "int",
  vwap: "decimal?",
  min_price: "decimal?",
  max_price: "decimal?",
  completed: "bool",
  last_trade_ts: "int",
  levels: [clusterLevel],
} as const;

const clusters = {
  instrument: "string",
  connection_id: "int",
  interval: "string",
  ts: "int",
  data: [clusterBucket],
} as const;

const errorEnvelope = { error: { code: "string", message: "string" } } as const;

/** Fixture file → the shape it must match. One entry per operation. */
const SHAPES: Record<string, Spec> = {
  "meta.json": meta,
  "health.json": health,
  "connections.json": { data: [connection] },
  "connection.json": connection,
  "instruments.json": instrumentsPage,
  "candles.json": candles,
  "intervals.json": intervals,
  "trades.json": trades,
  "snapshot.json": snapshot,
  "orderbook.json": orderbook,
  "clusters.json": clusters,
  "error.json": errorEnvelope,
};

test("every fixture has a shape and every shape has a fixture", async () => {
  const files = (await readdir(FIXTURES)).filter((name) => name.endsWith(".json")).sort();
  assert.deepEqual(files, Object.keys(SHAPES).sort());
});

for (const [file, spec] of Object.entries(SHAPES)) {
  test(`fixture ${file} matches types.ts`, async () => {
    const fixture: unknown = JSON.parse(await readFile(new URL(file, FIXTURES), "utf8"));
    const failures: string[] = [];
    check(fixture, spec, file.replace(/\.json$/, ""), failures);
    assert.deepEqual(failures, []);
  });
}

test("the checker itself catches a missing, an unknown and a mistyped field", () => {
  const failures: string[] = [];
  check({ ts: "1", extra: true }, { ts: "int", price: "decimal" }, "x", failures);
  assert.deepEqual(failures.map((line) => line.split(":")[0]), ["x.ts", "x.price", "x.extra"]);
});
