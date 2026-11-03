/**
 * Where the port and the token come from.
 *
 * The port is published by the running terminal in `instance.json` next to
 * its database; the token comes only from `SPECTRE_LOCAL_API_TOKEN` or an
 * explicit option. Nothing else in the terminal's data directory is ever
 * read, and the token is never searched for on disk.
 *
 * @module
 */

import { readFile } from "node:fs/promises";
import { homedir as osHomedir } from "node:os";
import { join } from "node:path";

import { LocalApiDisabledError } from "./errors.ts";

/** The port the terminal listens on unless `SPECTRE_LOCAL_API_PORT` overrides it. */
export const DEFAULT_PORT = 48180;

/** The environment variable the token is read from. */
export const TOKEN_ENV = "SPECTRE_LOCAL_API_TOKEN";

/** Name of the terminal's data directory under the OS data folder. */
const DATA_DIR_NAME = "spectre-terminal";

/** Name of the file the terminal publishes its ports in. */
const INSTANCE_FILE = "instance.json";

/** Process environment, platform and home directory; injectable for tests. */
export interface DiscoveryEnvironment {
  /** Defaults to `process.env`. */
  env?: Record<string, string | undefined>;
  /** Defaults to `process.platform`. */
  platform?: NodeJS.Platform;
  /** Defaults to `os.homedir()`. */
  homedir?: string;
}

/** Options of {@link readPort}. */
export interface ReadPortOptions extends DiscoveryEnvironment {
  /** Read this file instead of {@link instancePath}. */
  instancePath?: string;
}

/**
 * Path of the terminal's `instance.json`, per OS:
 *
 * - Linux: `$XDG_DATA_HOME/spectre-terminal/instance.json`, falling back to
 *   `~/.local/share/spectre-terminal/instance.json`;
 * - macOS: `~/Library/Application Support/spectre-terminal/instance.json`;
 * - Windows: `%LOCALAPPDATA%\spectre-terminal\instance.json`, falling back to
 *   `%USERPROFILE%\AppData\Local\...`.
 *
 * This mirrors the terminal's own data directory (`dirs::data_local_dir`).
 */
export function instancePath(options: DiscoveryEnvironment = {}): string {
  const env = options.env ?? process.env;
  const platform = options.platform ?? process.platform;
  const home = options.homedir ?? osHomedir();

  let base: string;
  switch (platform) {
    case "win32":
      base = env.LOCALAPPDATA || join(home, "AppData", "Local");
      break;
    case "darwin":
      base = join(home, "Library", "Application Support");
      break;
    default:
      base = env.XDG_DATA_HOME || join(home, ".local", "share");
      break;
  }
  return join(base, DATA_DIR_NAME, INSTANCE_FILE);
}

/**
 * The Local API port published in `instance.json`.
 *
 * Resolves to `undefined` when the file is missing or unreadable (no running
 * terminal, or a terminal that does not publish the field): the caller falls
 * back to {@link DEFAULT_PORT}. Throws {@link LocalApiDisabledError} when the
 * file exists but `local_api_port` is `null` or absent — the terminal is
 * running and the API is switched off. Reads only this one field.
 */
export async function readPort(options: ReadPortOptions = {}): Promise<number | undefined> {
  const path = options.instancePath ?? instancePath(options);

  let text: string;
  try {
    text = await readFile(path, "utf8");
  } catch {
    return undefined;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return undefined;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return undefined;
  }

  const port = (parsed as Record<string, unknown>).local_api_port;
  if (port === null || port === undefined) {
    // The contract describes `null` while the API is off; the terminal in
    // fact omits the field. Both mean the same: running, API switched off.
    throw new LocalApiDisabledError();
  }
  if (typeof port === "number" && Number.isInteger(port) && port > 0 && port < 65536) {
    return port;
  }
  return undefined;
}

/** The token from `SPECTRE_LOCAL_API_TOKEN`, or `undefined` when unset or empty. */
export function tokenFromEnv(env: Record<string, string | undefined> = process.env): string | undefined {
  const token = env[TOKEN_ENV];
  return token ? token : undefined;
}
