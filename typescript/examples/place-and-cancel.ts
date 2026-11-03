// Place a limit order far from the market, watch `account.orders` until the
// terminal's key shows up, cancel it, and watch until it is gone.
//
// Runs from a checkout without a build:
//   node examples/place-and-cancel.ts <connectionId> <exchange:market:SYMBOL> <size> [price]
// (Node 22.18+ strips the types). The token comes from SPECTRE_LOCAL_API_TOKEN,
// the port from instance.json. Installed from npm, import
// "@spectre-trade/terminal" instead of "../src/index.ts".
//
// This places a REAL order on the connection's account: a buy at half the best
// bid (rounded down to the tick), or at `price` if given, for `size` base
// coins. It should rest unfilled, and it is cancelled before the script ends;
// if the watch times out, the key is printed so the order can be found in
// the window. `accepted` means accepted by the terminal — the exchange may
// still refuse (below the minimum notional, too far from the market), in
// which case the key never appears in `account.orders` and the watch times
// out.

import { Terminal, type Decimal } from "../src/index.ts";

const [, , connectionArg, instrument, size, priceArg] = process.argv;
const connectionId = Number(connectionArg);
if (!Number.isInteger(connectionId) || instrument === undefined || size === undefined) {
  console.error("usage: node examples/place-and-cancel.ts <connectionId> <exchange:market:SYMBOL> <size> [price]");
  process.exit(2);
}
const WATCH_MS = 30_000;

const terminal = await Terminal.discover();

const price = priceArg ?? (await farBelowMarket(terminal, connectionId, instrument));
const clientKey = `sdk-example-${Date.now()}`;

// Subscribe before placing so the first update is not missed.
const stream = await terminal.stream();
await stream.subscribe({ topic: "account.orders", connectionId });

const accepted = await terminal.placeOrder({
  connectionId,
  instrument,
  side: "buy",
  type: "limit",
  price,
  size,
  postOnly: true,
  clientKey,
});
console.log(`accepted by the terminal: key ${accepted.key}, operation ${accepted.operation_id}, client_key ${clientKey}`);
const key = accepted.key;
if (key === null) {
  console.error("the terminal returned no key for the order");
  process.exit(1);
}

let phase: "placing" | "cancelling" = "placing";
const deadline = setTimeout(() => void stream.close(), WATCH_MS);
try {
  for await (const frame of stream) {
    if (frame.type !== "event" || frame.topic !== "account.orders" || frame.data.instrument !== instrument) {
      continue;
    }
    const order = frame.data.orders.find((candidate) => candidate.key === key);
    // Cancel only once the exchange has acknowledged the order (exchange_id
    // present): a cancel sent while it is still pending finds nothing.
    if (phase === "placing" && order !== undefined && order.exchange_id !== null) {
      console.log(`open at the exchange: ${order.status}, exchange id ${order.exchange_id ?? "pending"}, ${order.remaining} @ ${order.price}`);
      const cancel = await terminal.cancelOrder({ connectionId, instrument, orderId: key });
      console.log(`cancel accepted by the terminal: operation ${cancel.operation_id}`);
      phase = "cancelling";
    } else if (phase === "cancelling" && order === undefined) {
      console.log("gone from the book: cancelled");
      break;
    }
  }
} finally {
  clearTimeout(deadline);
  await stream.close();
}

if (phase === "placing") {
  console.error(`the key ${key} did not appear in account.orders within ${WATCH_MS / 1000} s: the exchange may have refused it — check the window`);
  process.exit(1);
}

/** Half the best bid, rounded down to the instrument's tick. */
async function farBelowMarket(t: Terminal, connection: number, address: string): Promise<Decimal> {
  const snapshot = await t.snapshot(address, { connectionId: connection });
  const bid = snapshot.best_bid?.[0];
  if (bid === undefined) {
    throw new Error(`no best bid for ${address} yet: pass a price`);
  }
  const symbol = address.slice(address.lastIndexOf(":") + 1);
  let tick: Decimal | null = null;
  for await (const item of t.iterInstruments({ connectionId: connection, q: symbol })) {
    if (item.instrument === address) {
      tick = item.tick_size;
      break;
    }
  }
  if (tick === null) {
    throw new Error(`no tick size for ${address} in the catalogue: pass a price`);
  }
  return halveToTick(bid, tick);
}

/** Decimal arithmetic on strings with BigInt: no `Number`, no precision loss. */
function halveToTick(price: Decimal, tick: Decimal): Decimal {
  const scale = Math.max(fraction(price), fraction(tick));
  const tickUnits = units(tick, scale);
  const half = units(price, scale) / 2n;
  const floored = (half / tickUnits) * tickUnits;
  const rounded = floored === 0n ? tickUnits : floored; // a tick wider than half the price: one tick, not zero
  const text = rounded.toString().padStart(scale + 1, "0");
  const whole = text.slice(0, text.length - scale);
  const digits = text.slice(text.length - scale).replace(/0+$/, "");
  return digits === "" ? whole : `${whole}.${digits}`;
}

function fraction(decimal: Decimal): number {
  const dot = decimal.indexOf(".");
  return dot === -1 ? 0 : decimal.length - dot - 1;
}

function units(decimal: Decimal, scale: number): bigint {
  const [whole, digits = ""] = decimal.split(".");
  return BigInt(`${whole}${digits.padEnd(scale, "0")}`);
}
