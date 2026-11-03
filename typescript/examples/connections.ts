// List the terminal's connections.
//
// Runs from a checkout without a build: `node examples/connections.ts`
// (Node 22.18+ strips the types). The token comes from SPECTRE_LOCAL_API_TOKEN,
// the port from instance.json. Installed from npm, import
// "@spectre-trade/terminal" instead of "../src/index.ts".

import { Terminal } from "../src/index.ts";

const terminal = await Terminal.discover();

const meta = await terminal.meta();
console.log(`terminal ${meta.app_version} (${meta.build_env}), API v${meta.api_version}, scopes: ${meta.scopes.join(", ")}`);

const { data: connections } = await terminal.connections();
if (connections.length === 0) {
  console.log("no connections");
}
for (const connection of connections) {
  const flags = [
    connection.enabled ? "enabled" : "disabled",
    connection.read_only ? "read-only" : "trading",
    connection.proxy_bound ? "proxy" : "direct",
  ].join(", ");
  const lastEvent = connection.status.last_event
    ? `${connection.status.last_event.code} at ${new Date(connection.status.last_event.ts).toISOString()}`
    : "no history yet";
  console.log(`#${connection.id} ${connection.exchange}:${connection.market} "${connection.label}" — ${connection.status.state} (${flags}; ${lastEvent})`);
}
