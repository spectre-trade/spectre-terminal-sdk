/**
 * Discovery: the `instance.json` path per OS, reading the port from it, and
 * `Terminal.discover()` against a fake terminal.
 */

import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";

import {
  ApiError,
  IncompatibleTerminalError,
  LocalApiDisabledError,
  Terminal,
  TOKEN_ENV,
  TokenMissingError,
  instancePath,
  readPort,
  tokenFromEnv,
} from "../src/index.ts";

const TOKEN = `spt_${"cd".repeat(32)}`;

test("instancePath follows the OS data directory", () => {
  assert.equal(
    instancePath({ platform: "linux", env: { XDG_DATA_HOME: "/xdg/data" }, homedir: "/home/u" }),
    "/xdg/data/spectre-terminal/instance.json",
  );
  assert.equal(
    instancePath({ platform: "linux", env: {}, homedir: "/home/u" }),
    "/home/u/.local/share/spectre-terminal/instance.json",
  );
  assert.equal(
    instancePath({ platform: "darwin", env: { XDG_DATA_HOME: "/ignored" }, homedir: "/Users/u" }),
    "/Users/u/Library/Application Support/spectre-terminal/instance.json",
  );
  const windows = instancePath({ platform: "win32", env: { LOCALAPPDATA: "C:\\Users\\u\\AppData\\Local" }, homedir: "C:\\Users\\u" });
  assert.ok(windows.startsWith("C:\\Users\\u\\AppData\\Local"), windows);
  assert.ok(windows.endsWith(join("spectre-terminal", "instance.json")), windows);
  const windowsFallback = instancePath({ platform: "win32", env: {}, homedir: "C:\\Users\\u" });
  assert.ok(windowsFallback.includes(join("AppData", "Local")), windowsFallback);
  assert.equal(typeof instancePath(), "string");
});

test("readPort reads local_api_port and nothing else", async (t) => {
  const dir = await mkdtemp(join(tmpdir(), "spectre-sdk-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const file = join(dir, "instance.json");

  await writeFile(file, JSON.stringify({ pid: 1, http_port: 46727, local_api_port: 48181 }));
  assert.equal(await readPort({ instancePath: file }), 48181);

  assert.equal(await readPort({ instancePath: join(dir, "missing.json") }), undefined);

  await writeFile(file, JSON.stringify({ pid: 1, http_port: 46727, local_api_port: null }));
  await assert.rejects(readPort({ instancePath: file }), LocalApiDisabledError);

  // The terminal omits the field while the API is off; same meaning as null.
  await writeFile(file, JSON.stringify({ pid: 1, http_port: 46727 }));
  await assert.rejects(readPort({ instancePath: file }), LocalApiDisabledError);

  await writeFile(file, "{not json");
  assert.equal(await readPort({ instancePath: file }), undefined);

  await writeFile(file, JSON.stringify({ local_api_port: "48180" }));
  assert.equal(await readPort({ instancePath: file }), undefined);

  await writeFile(file, JSON.stringify([48180]));
  assert.equal(await readPort({ instancePath: file }), undefined);
});

test("tokenFromEnv", () => {
  assert.equal(tokenFromEnv({ [TOKEN_ENV]: TOKEN }), TOKEN);
  assert.equal(tokenFromEnv({ [TOKEN_ENV]: "" }), undefined);
  assert.equal(tokenFromEnv({}), undefined);
});

// --- Terminal.discover() against a fake terminal -----------------------------

let server: Server;
let port: number;
let apiVersion = "1";
let unauthorized = false;
const paths: string[] = [];
const authorizations: Array<string | undefined> = [];

before(async () => {
  server = createServer((req, res) => {
    paths.push(req.url ?? "");
    authorizations.push(req.headers.authorization);
    if (unauthorized) {
      res.writeHead(401, { "Content-Type": "application/json", "WWW-Authenticate": "Bearer" });
      res.end(JSON.stringify({ error: { code: "unauthorized", message: "token does not match" } }));
      return;
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        api_version: apiVersion,
        app_version: "1.9.6",
        build_hash: "unknown",
        build_env: "development",
        features: "local-api",
        scopes: ["market:read", "connections:read"],
        limits: {
          ws_connections_per_token: 8,
          subscriptions_per_connection: 100,
          api_only_instruments: 50,
          exchange_subscriptions_per_second: 5,
        },
        topics: ["trades"],
      }),
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  port = (server.address() as AddressInfo).port;
});

after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

async function withInstanceFile(contents: unknown, run: (file: string) => Promise<void>): Promise<void> {
  const dir = await mkdtemp(join(tmpdir(), "spectre-sdk-"));
  try {
    const file = join(dir, "instance.json");
    await writeFile(file, JSON.stringify(contents));
    await run(file);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

test("discover takes the port from instance.json and checks /v1/meta", async () => {
  await withInstanceFile({ pid: 1, http_port: 1, local_api_port: port }, async (file) => {
    paths.length = 0;
    const terminal = await Terminal.discover({ token: TOKEN, instancePath: file });
    assert.equal(terminal.port, port);
    assert.deepEqual(paths, ["/v1/meta"]);
    assert.equal(authorizations.at(-1), `Bearer ${TOKEN}`);
  });
});

test("discover prefers an explicit port over instance.json", async () => {
  await withInstanceFile({ local_api_port: 1 }, async (file) => {
    const terminal = await Terminal.discover({ token: TOKEN, port, instancePath: file });
    assert.equal(terminal.port, port);
  });
});

test("discover fails on an instance.json without a port", async () => {
  await withInstanceFile({ pid: 1, http_port: 1, local_api_port: null }, async (file) => {
    await assert.rejects(Terminal.discover({ token: TOKEN, instancePath: file }), LocalApiDisabledError);
  });
});

test("discover rejects another API version", async () => {
  apiVersion = "2";
  try {
    const error = await Terminal.discover({ token: TOKEN, port }).catch((e: unknown) => e);
    assert.ok(error instanceof IncompatibleTerminalError);
    assert.equal(error.apiVersion, "2");
    assert.equal(error.appVersion, "1.9.6");
  } finally {
    apiVersion = "1";
  }
});

test("discover explains an unauthorized answer without leaking the token", async () => {
  unauthorized = true;
  try {
    const error = await Terminal.discover({ token: TOKEN, port }).catch((e: unknown) => e);
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, "unauthorized");
    assert.equal(error.status, 401);
    assert.ok(error.message.includes("switched off"), error.message);
    assert.ok(!error.message.includes(TOKEN));
  } finally {
    unauthorized = false;
  }
});

test("discover without a token is TokenMissingError that names the Settings App", async () => {
  const saved = process.env[TOKEN_ENV];
  delete process.env[TOKEN_ENV];
  try {
    const error = await Terminal.discover({ port }).catch((e: unknown) => e);
    assert.ok(error instanceof TokenMissingError);
    assert.ok(error.message.includes("Settings App"), error.message);
    assert.ok(error.message.includes("Copy token"), error.message);
    assert.ok(error.message.includes(TOKEN_ENV), error.message);
  } finally {
    if (saved !== undefined) process.env[TOKEN_ENV] = saved;
  }
});

test("discover reads the token from the environment", async () => {
  const saved = process.env[TOKEN_ENV];
  process.env[TOKEN_ENV] = TOKEN;
  try {
    const terminal = await Terminal.discover({ port });
    assert.equal(authorizations.at(-1), `Bearer ${TOKEN}`);
    assert.equal(terminal.port, port);
  } finally {
    if (saved === undefined) delete process.env[TOKEN_ENV];
    else process.env[TOKEN_ENV] = saved;
  }
});
