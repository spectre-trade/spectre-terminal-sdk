// Read one connection's account — open orders, triggers, positions, balances,
// fills — then follow the four account topics for a few frames.
//
// Runs from a checkout without a build:
//   node examples/account.ts <connectionId>
// (Node 22.18+ strips the types). The token comes from SPECTRE_LOCAL_API_TOKEN,
// the port from instance.json. Installed from npm, import
// "@spectre-trade/terminal" instead of "../src/index.ts".
//
// The account is always one connection: there is no default, pick the id from
// `examples/connections.ts`. Nothing here places an order.

import { Terminal } from "../src/index.ts";

const connectionId = Number(process.argv[2]);
if (!Number.isInteger(connectionId)) {
  console.error("usage: node examples/account.ts <connectionId>");
  process.exit(2);
}
const FRAMES = 10;
const WATCH_MS = 30_000;

const terminal = await Terminal.discover();
const connection = await terminal.connection(connectionId);
console.log(`#${connection.id} ${connection.exchange}:${connection.market} "${connection.label}" — ${connection.status.state}`);

const { data: orders, triggers } = await terminal.accountOrders(connectionId);
console.log(`${orders.length} open orders, ${triggers.length} triggers`);
for (const order of orders) {
  console.log(`  order   ${order.key ?? "?"} ${order.instrument} ${order.side} ${order.type} ${order.remaining}/${order.size} @ ${order.price} ${order.status}`);
}
for (const trigger of triggers) {
  console.log(`  trigger ${trigger.id} ${trigger.instrument} ${trigger.type} ${trigger.rule} ${trigger.trigger_price} ${trigger.status}`);
}

const { data: positions } = await terminal.accountPositions(connectionId);
console.log(`${positions.length} positions`);
for (const position of positions) {
  console.log(`  ${position.instrument} ${position.side} ${position.size} @ ${position.entry_price}, mark ${position.mark_price ?? "null"}, uPnL ${position.unrealized_pnl}`);
}

const { data: balances } = await terminal.accountBalances(connectionId);
console.log(`${balances.length} balances (currencies that changed since the API was switched on)`);
for (const balance of balances) {
  console.log(`  ${balance.currency} total ${balance.total} available ${balance.available ?? "null"} locked ${balance.locked ?? "null"}`);
}

const { data: fills } = await terminal.accountFills(connectionId, { limit: 20 });
console.log(`${fills.length} fills (oldest first, since the API was switched on)`);
for (const fill of fills) {
  console.log(`  ${new Date(fill.ts).toISOString()} ${fill.instrument} ${fill.side} ${fill.qty} @ ${fill.price} fee ${fill.fee} ${fill.fee_currency}`);
}

// Live: the topics are keyed by connection, no instrument. Subscribing sends
// no snapshot — the reads above are the current state, the stream is what
// changes from here.
const stream = await terminal.stream();
for (const topic of ["account.orders", "account.positions", "account.balances", "account.fills"] as const) {
  const subscribed = await stream.subscribe({ topic, connectionId });
  console.log(`subscribed ${subscribed.sub}`);
}
console.log(`watching for ${FRAMES} frames or ${WATCH_MS / 1000} s — trade in the terminal window to see them`);

const deadline = setTimeout(() => void stream.close(), WATCH_MS);
let printed = 0;
try {
  for await (const frame of stream) {
    if (frame.type === "error") {
      console.log(`error  ${frame.sub} removed by the server: ${frame.code} ${frame.message}`);
      continue;
    }
    if (frame.type !== "event") {
      continue; // `gap` is for `trades` only
    }
    switch (frame.topic) {
      case "account.orders":
        console.log(`orders    ${frame.data.instrument}: ${frame.data.orders.length} open, ${frame.data.triggers.length} triggers (seq ${frame.seq})`);
        break;
      case "account.positions":
        console.log(
          frame.data.position === null
            ? `position  ${frame.data.instrument}: closed (seq ${frame.seq})`
            : `position  ${frame.data.instrument}: ${frame.data.position.side} ${frame.data.position.size} @ ${frame.data.position.entry_price} (seq ${frame.seq})`,
        );
        break;
      case "account.balances":
        console.log(`balance   ${frame.data.currency} total ${frame.data.total} available ${frame.data.available ?? "null"} (seq ${frame.seq})`);
        break;
      case "account.fills":
        console.log(`fill      ${frame.data.instrument} ${frame.data.side} ${frame.data.qty} @ ${frame.data.price} (seq ${frame.seq})`);
        break;
      default:
        console.log(`event     ${frame.sub} seq ${frame.seq}`);
    }
    printed += 1;
    if (printed >= FRAMES) {
      break; // leaving the loop closes the stream
    }
  }
} finally {
  clearTimeout(deadline);
  await stream.close();
}
console.log(`closed with code ${stream.closeCode}`);
