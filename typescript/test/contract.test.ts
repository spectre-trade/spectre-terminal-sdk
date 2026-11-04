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
type Kind = "string" | "decimal" | "int" | "bool" | "side" | "position_side" | "state";

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
    case "position_side":
      if (value !== "long" && value !== "short") fail('"long" or "short"');
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
  // Optional in types.ts only for terminals older than the writing stage;
  // the fixture is the current terminal's answer and must carry it.
  commands_per_second: "int",
  workspace_commands_per_second: "int",
  settings_commands_per_second: "int",
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

const order = {
  key: "string?",
  exchange_id: "string?",
  instrument: "string",
  side: "side",
  type: "string",
  price: "decimal",
  size: "decimal",
  filled: "decimal",
  remaining: "decimal",
  notional: "decimal?",
  status: "string",
  created_ts: "int",
} as const;

const triggerOrder = {
  id: "string",
  instrument: "string",
  type: "string",
  trigger_price: "decimal",
  rule: "string",
  size: "decimal?",
  notional: "decimal?",
  status: "string",
  order_type: "string?",
  client_id: "string?",
  created_ts: "int?",
} as const;

const accountOrders = { connection_id: "int", data: [order], triggers: [triggerOrder] } as const;

const position = {
  instrument: "string",
  side: "position_side",
  size: "decimal",
  lot_size: "decimal",
  entry_price: "decimal",
  notional: "decimal",
  unrealized_pnl: "decimal",
  mark_price: "decimal?",
} as const;

const accountPositions = { connection_id: "int", data: [position] } as const;

const balance = {
  currency: "string",
  total: "decimal",
  available: "decimal?",
  locked: "decimal?",
  ts: "int",
} as const;

const accountBalances = { connection_id: "int", data: [balance] } as const;

const fill = {
  trade_id: "string",
  order_id: "string",
  instrument: "string",
  side: "side",
  price: "decimal",
  qty: "decimal",
  fee: "decimal",
  fee_currency: "string",
  position_side: "position_side?",
  ts: "int",
} as const;

const accountFills = { connection_id: "int", data: [fill] } as const;

const accepted = {
  accepted: "bool",
  operation_id: "string",
  key: "string?",
  connection_id: "int",
  instrument: "string",
} as const;

const leverage = {
  connection_id: "int",
  instrument: "string",
  leverage: "int",
  max_leverage: "int",
  mode: "string",
  margin_mode: "string",
} as const;

const cellPosition = { column: "int", row: "int", cell: "int" } as const;

const stack = {
  widget_id: "int",
  instrument: "string?",
  connection_id: "int?",
  empty: "bool",
  frozen: "bool",
  position: cellPosition,
} as const;

const chart = {
  widget_id: "int",
  instrument: "string?",
  connection_id: "int?",
  interval: "string",
  owner_widget_id: "int?",
  position: cellPosition,
} as const;

const tab = { id: "int", name: "string", active: "bool", stacks: [stack], charts: [chart] } as const;

const window = {
  id: "int",
  main: "bool",
  chart_window: "bool",
  focused: "bool",
  geometry: { x: "int", y: "int", width: "int", height: "int", maximized: "bool" },
  monitor: "string?",
  tabs: [tab],
} as const;

const workspace = { data: { windows: [window] } } as const;

const workspaceWindow = { data: window } as const;

const workspaceOutcome = { window_id: "int?", tab_id: "int?", stacks: ["int"], charts: ["int"] } as const;

const settingRow = {
  scope: "string",
  scope_id: "string?",
  connection_id: "int?",
  category: "string",
  key: "string",
  value: nullable("int"),
  writable: "bool",
} as const;

const settings = { data: [settingRow] } as const;

const settingsOrderbook = {
  connection_id: "int",
  instrument: "string",
  data: { general: { auto_scroll: { value: "bool", resolved_from: "string", writable: "bool" } } },
} as const;

const settingsApplied = { applied: "int" } as const;

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
  "account_orders.json": accountOrders,
  "account_positions.json": accountPositions,
  "account_balances.json": accountBalances,
  "account_fills.json": accountFills,
  "accepted.json": accepted,
  "leverage.json": leverage,
  "workspace.json": workspace,
  "workspace_window.json": workspaceWindow,
  "workspace_outcome.json": workspaceOutcome,
  "settings.json": settings,
  "settings_orderbook.json": settingsOrderbook,
  "settings_applied.json": settingsApplied,
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

test("meta.json names the eight scopes", async () => {
  const fixture = JSON.parse(await readFile(new URL("meta.json", FIXTURES), "utf8")) as { scopes: string[] };
  assert.deepEqual(
    [...fixture.scopes].sort(),
    [
      "account:read",
      "connections:read",
      "market:read",
      "settings:read",
      "settings:write",
      "trading:write",
      "workspace:read",
      "workspace:write",
    ],
  );
});

test("the checker itself catches a missing, an unknown and a mistyped field", () => {
  const failures: string[] = [];
  check({ ts: "1", extra: true }, { ts: "int", price: "decimal" }, "x", failures);
  assert.deepEqual(failures.map((line) => line.split(":")[0]), ["x.ts", "x.price", "x.extra"]);
});
