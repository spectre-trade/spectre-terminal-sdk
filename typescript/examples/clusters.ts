// Print the cluster buckets of one instrument.
//
// Runs from a checkout without a build:
//   node examples/clusters.ts [exchange:market:SYMBOL]
// (Node 22.18+ strips the types). The token comes from SPECTRE_LOCAL_API_TOKEN,
// the port from instance.json. Installed from npm, import
// "@spectre-trade/terminal" instead of "../src/index.ts".
//
// An instrument not open in the window is computed on request and its
// history is seeded from the backend; the first call may answer `not_active`
// (HTTP 409), and a retry a few seconds later finds the buckets.

import { ApiError, Terminal, type Clusters } from "../src/index.ts";

const instrument = process.argv[2] ?? "binance:futures:BTCUSDT";

const terminal = await Terminal.discover();

async function clustersWithRetry(): Promise<Clusters> {
  try {
    return await terminal.clusters(instrument);
  } catch (error) {
    if (error instanceof ApiError && error.code === "not_active") {
      console.log("clusters not computed yet, retrying in 3 s…");
      await new Promise((resolve) => setTimeout(resolve, 3000));
      return terminal.clusters(instrument);
    }
    throw error;
  }
}

const clusters = await clustersWithRetry();
console.log(`${clusters.instrument} via connection #${clusters.connection_id}, interval ${clusters.interval}, ${clusters.data.length} buckets`);

for (const bucket of clusters.data) {
  const start = new Date(bucket.ts).toISOString();
  const state = bucket.completed ? "closed" : "open";
  console.log(
    `${start} ${state.padEnd(6)} volume ${bucket.volume} (buy ${bucket.buy_volume} / sell ${bucket.sell_volume}), ${bucket.trades} trades, vwap ${bucket.vwap ?? "n/a"}, ${bucket.levels.length} levels`,
  );
  // The three busiest price levels; volumes are decimal strings, so compare
  // them with a decimal library in real code — Number is fine for a printout.
  const busiest = [...bucket.levels].sort((a, b) => Number(b.volume) - Number(a.volume)).slice(0, 3);
  for (const level of busiest) {
    console.log(`    ${level.price}: ${level.volume} (buy ${level.buy_volume} in ${level.buy_trades} trades, sell ${level.sell_volume} in ${level.sell_trades})`);
  }
}
