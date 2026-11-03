// Print the market snapshot of one instrument.
//
// Runs from a checkout without a build:
//   node examples/snapshot.ts [exchange:market:SYMBOL]
// (Node 22.18+ strips the types). The token comes from SPECTRE_LOCAL_API_TOKEN,
// the port from instance.json. Installed from npm, import
// "@spectre-trade/terminal" instead of "../src/index.ts".
//
// An instrument that is not open in the terminal window is opened on demand;
// the first call may take up to 3 s.

import { Terminal } from "../src/index.ts";

const instrument = process.argv[2] ?? "binance:futures:BTCUSDT";

const terminal = await Terminal.discover();
const snapshot = await terminal.snapshot(instrument);

console.log(`${snapshot.instrument} via connection #${snapshot.connection_id} at ${new Date(snapshot.ts).toISOString()}`);
console.log(`best bid: ${snapshot.best_bid ? snapshot.best_bid.join(" x ") : "no book yet"}`);
console.log(`best ask: ${snapshot.best_ask ? snapshot.best_ask.join(" x ") : "no book yet"}`);
console.log(`mark:     ${snapshot.mark_price ?? "n/a"}`);
if (snapshot.last_trade) {
  const trade = snapshot.last_trade;
  console.log(`last trade: ${trade.side} ${trade.qty} @ ${trade.price} (exchange time ${new Date(trade.exchange_ts).toISOString()})`);
} else {
  console.log("last trade: none yet");
}
if (snapshot.ticker) {
  const ticker = snapshot.ticker;
  console.log(`ticker: ${ticker.price}, 24h ${ticker.change_24h_pct ?? "n/a"}%, volume ${ticker.volume_24h}`);
}
