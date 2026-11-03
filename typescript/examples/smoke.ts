// Live smoke check: call every read operation once plus a short stream, print
// one PASS/FAIL line per operation, exit 1 if anything failed. Nothing here
// places an order: the account reads go to the first connection that trades
// (enabled, with credentials, not read-only) and are skipped without one;
// the writes are exercised by `examples/place-and-cancel.ts` on purpose.
//
// Runs from a checkout without a build:
//   node examples/smoke.ts [exchange:market:SYMBOL]
// (Node 22.18+ strips the types). The token comes from SPECTRE_LOCAL_API_TOKEN,
// the port from instance.json. Installed from npm, import
// "@spectre-trade/terminal" instead of "../src/index.ts".
//
// The default instrument is deliberately one that is usually not open in the
// window, so the cold paths (temporary subscription, cluster seeding) are
// exercised. Nothing printed here ever includes the token.

import { ApiError, Terminal, type Clusters, type Stream } from "../src/index.ts";

const instrument = process.argv[2] ?? "binance:futures:ETHUSDT";
const [exchange, market] = instrument.split(":");
if (!exchange || !market) {
  console.error(`bad instrument address: ${instrument}`);
  process.exit(2);
}

let failed = false;

function describe(error: unknown): string {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}`;
  }
  return String(error);
}

async function step(name: string, run: () => Promise<string>): Promise<void> {
  const started = Date.now();
  try {
    const summary = await run();
    console.log(`PASS ${name.padEnd(14)} ${summary} (${Date.now() - started} ms)`);
  } catch (error) {
    failed = true;
    console.log(`FAIL ${name.padEnd(14)} ${describe(error)} (${Date.now() - started} ms)`);
  }
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

let terminal: Terminal | undefined;
await step("discover", async () => {
  terminal = await Terminal.discover();
  const meta = await terminal.meta();
  return `terminal ${meta.app_version}, API v${meta.api_version}, topics [${meta.topics.join(", ")}], port ${terminal.port}`;
});
if (terminal === undefined) {
  process.exit(1);
}
const t = terminal;

await step("health", async () => {
  const health = await t.health();
  return `${health.status}, uptime ${Math.round(health.uptime_ms / 1000)} s, clients ${health.clients}, streams ${health.streams}, stream_available ${health.stream_available}`;
});

let firstConnectionId: number | undefined;
let tradableConnectionId: number | undefined;
await step("connections", async () => {
  const { data } = await t.connections();
  firstConnectionId = data[0]?.id;
  tradableConnectionId = data.find((c) => c.enabled && c.has_credentials && !c.read_only)?.id;
  return `${data.length} connections: ${data.map((c) => `${c.exchange}:${c.market}=${c.status.state}`).join(", ")}`;
});

await step("connection", async () => {
  if (firstConnectionId === undefined) {
    return "skipped: no connections";
  }
  const connection = await t.connection(firstConnectionId);
  return `#${connection.id} ${connection.exchange}:${connection.market} ${connection.status.state}`;
});

await step("instruments", async () => {
  const page = await t.instruments({ exchange, market, limit: 5 });
  return `${page.exchange}:${page.market}, ${page.data.length} on the first page, next_cursor ${page.next_cursor === null ? "null" : `"${page.next_cursor}"`}`;
});

await step("iterInstruments", async () => {
  const limit = 500;
  let count = 0;
  for await (const item of t.iterInstruments({ exchange, market, limit })) {
    count += 1;
    if (item.instrument !== `${exchange}:${market}:${item.symbol}`) {
      throw new Error(`instrument address mismatch: ${item.instrument}`);
    }
  }
  return `${count} instruments over ${Math.max(1, Math.ceil(count / limit))} page(s)`;
});

let candleInterval = "1m";
await step("intervals", async () => {
  const intervals = await t.intervals();
  candleInterval = intervals.candles[0]?.id ?? candleInterval;
  return `${intervals.candles.length} candle intervals, ${intervals.clusters.length} cluster intervals`;
});

await step("candles", async () => {
  const candles = await t.candles(instrument, { interval: candleInterval, limit: 5 });
  const last = candles.data.at(-1);
  return `${candles.data.length} bars of ${candles.interval}${last ? `, last close ${last.close} at ${new Date(last.ts).toISOString()}` : ""}`;
});

await step("trades", async () => {
  const trades = await t.trades(instrument, { limit: 10 });
  const last = trades.data.at(-1);
  return `${trades.data.length} trades${last ? `, last ${last.side} ${last.qty} @ ${last.price}` : ""}`;
});

await step("snapshot", async () => {
  const snapshot = await t.snapshot(instrument);
  return `bid ${snapshot.best_bid?.[0] ?? "null"} ask ${snapshot.best_ask?.[0] ?? "null"} mark ${snapshot.mark_price ?? "null"} ticker ${snapshot.ticker?.price ?? "null"}`;
});

await step("orderbook", async () => {
  const book = await t.orderbook(instrument, { depth: 5 });
  return `${book.bids.length} bids / ${book.asks.length} asks, best ${book.bids[0]?.[0]} / ${book.asks[0]?.[0]}`;
});

await step("clusters", async () => {
  let clusters: Clusters;
  try {
    clusters = await t.clusters(instrument);
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "not_active") {
      throw error;
    }
    await sleep(3000);
    clusters = await t.clusters(instrument);
  }
  const last = clusters.data.at(-1);
  return `${clusters.data.length} buckets of ${clusters.interval}${last ? `, last volume ${last.volume} over ${last.levels.length} levels` : ""}`;
});

const SKIP_ACCOUNT = "skipped: no enabled trading connection";

await step("accountOrders", async () => {
  if (tradableConnectionId === undefined) {
    return SKIP_ACCOUNT;
  }
  const orders = await t.accountOrders(tradableConnectionId);
  return `connection #${orders.connection_id}: ${orders.data.length} open orders, ${orders.triggers.length} triggers`;
});

await step("accountPositions", async () => {
  if (tradableConnectionId === undefined) {
    return SKIP_ACCOUNT;
  }
  const positions = await t.accountPositions(tradableConnectionId);
  return `${positions.data.length} positions${positions.data[0] ? `, first ${positions.data[0].instrument} ${positions.data[0].side} ${positions.data[0].size}` : ""}`;
});

await step("accountBalances", async () => {
  if (tradableConnectionId === undefined) {
    return SKIP_ACCOUNT;
  }
  const balances = await t.accountBalances(tradableConnectionId);
  return `${balances.data.length} currencies${balances.data[0] ? `, first ${balances.data[0].currency} ${balances.data[0].total}` : ""}`;
});

await step("accountFills", async () => {
  if (tradableConnectionId === undefined) {
    return SKIP_ACCOUNT;
  }
  const fills = await t.accountFills(tradableConnectionId, { limit: 10 });
  const last = fills.data.at(-1);
  return `${fills.data.length} fills${last ? `, last ${last.instrument} ${last.side} ${last.qty} @ ${last.price}` : ""}`;
});

let stream: Stream | undefined;
await step("stream", async () => {
  stream = await t.stream();
  const trades = await stream.subscribe({ topic: "trades", instrument });
  const book = await stream.subscribe({ topic: "book.top", instrument, params: { depth: 5, interval_ms: 200 } });
  return `subscribed ${trades.sub}, ${book.sub} via connection #${trades.connection_id}`;
});

await step("stream frames", async () => {
  if (stream === undefined) {
    throw new Error("no stream");
  }
  const live = stream;
  const counts = new Map<string, number>();
  let frames = 0;
  const collect = async (): Promise<void> => {
    for await (const frame of live) {
      frames += 1;
      const key = frame.type === "event" ? (frame.topic ?? frame.sub) : frame.type;
      counts.set(key, (counts.get(key) ?? 0) + 1);
      if (frames >= 20) {
        break;
      }
    }
  };
  await Promise.race([collect(), sleep(10_000)]);
  await live.close();
  if (frames === 0) {
    throw new Error("no frames within 10 s");
  }
  return `${frames} frames: ${[...counts].map(([key, count]) => `${key}=${count}`).join(", ")}; closed with ${live.closeCode}`;
});

console.log(failed ? "RESULT FAIL" : "RESULT PASS");
process.exit(failed ? 1 : 0);
