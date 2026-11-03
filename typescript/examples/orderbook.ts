// Print the top of the order book as a ladder.
//
// Runs from a checkout without a build:
//   node examples/orderbook.ts [exchange:market:SYMBOL] [depth]
// (Node 22.18+ strips the types). The token comes from SPECTRE_LOCAL_API_TOKEN,
// the port from instance.json. Installed from npm, import
// "@spectre-trade/terminal" instead of "../src/index.ts".

import { Terminal } from "../src/index.ts";

const instrument = process.argv[2] ?? "binance:futures:BTCUSDT";
const depth = Number(process.argv[3] ?? 10);

const terminal = await Terminal.discover();
const book = await terminal.orderbook(instrument, { depth });

console.log(`${book.instrument} via connection #${book.connection_id}, depth ${book.depth}, ${new Date(book.ts).toISOString()}`);
console.log("");
console.log("        ask size |  ask price");
for (const [price, size] of [...book.asks].reverse()) {
  console.log(`${size.padStart(16)} | ${price}`);
}
console.log("-----------------+-----------------");
for (const [price, size] of book.bids) {
  console.log(`${size.padStart(16)} | ${price}`);
}
console.log("        bid size |  bid price");
