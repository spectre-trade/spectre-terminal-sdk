// Subscribe to trades and the top of the book, print ten frames, exit.
//
// Runs from a checkout without a build:
//   node examples/trades-stream.ts [exchange:market:SYMBOL]
// (Node 22.18+ strips the types). The token comes from SPECTRE_LOCAL_API_TOKEN,
// the port from instance.json. Installed from npm, import
// "@spectre-trade/terminal" instead of "../src/index.ts".

import { Terminal } from "../src/index.ts";

const instrument = process.argv[2] ?? "binance:futures:BTCUSDT";
const FRAMES = 10;

const terminal = await Terminal.discover();
const stream = await terminal.stream();

const trades = await stream.subscribe({ topic: "trades", instrument });
const book = await stream.subscribe({ topic: "book.top", instrument, params: { depth: 5, interval_ms: 200 } });
console.log(`subscribed: ${trades.sub} and ${book.sub} via connection #${trades.connection_id}`);

let printed = 0;
try {
  for await (const frame of stream) {
    switch (frame.type) {
      case "event":
        if (frame.topic === "trades") {
          for (const trade of frame.data) {
            console.log(`trade  ${trade.side.padEnd(4)} ${trade.qty} @ ${trade.price}  (seq ${frame.seq})`);
          }
        } else if (frame.topic === "book.top") {
          const [bid] = frame.data.bids;
          const [ask] = frame.data.asks;
          console.log(`book   ${bid?.join(" x ") ?? "-"}  |  ${ask?.join(" x ") ?? "-"}  (version ${frame.seq})`);
        } else {
          console.log(`event  ${frame.sub} seq ${frame.seq}`);
        }
        break;
      case "gap":
        console.log(`gap    ${frame.sub}: events ${frame.from_seq}..${frame.to_seq} lost (${frame.reason})`);
        break;
      case "error":
        console.log(`error  ${frame.sub} removed by the server: ${frame.code} ${frame.message}`);
        break;
    }
    printed += 1;
    if (printed >= FRAMES) {
      break; // leaving the loop closes the stream
    }
  }
} finally {
  await stream.close();
}
console.log(`closed with code ${stream.closeCode}`);
