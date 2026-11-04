/**
 * `@spectre-trade/terminal` — the TypeScript client of the Spectre Terminal
 * Local API (v1).
 *
 * ```ts
 * import { Terminal } from "@spectre-trade/terminal";
 *
 * const terminal = await Terminal.discover();
 * const snapshot = await terminal.snapshot("binance:futures:BTCUSDT");
 * const { data: orders } = await terminal.accountOrders(12);
 * ```
 *
 * @module
 */

export { Terminal, SUPPORTED_API_VERSION } from "./client.ts";
export type {
  AccountFillsOptions,
  AddStacksOptions,
  AmendTriggerOptions,
  CancelOrderOptions,
  CancelTriggerOptions,
  CandlesOptions,
  ConnectionOptions,
  DiscoverOptions,
  InstrumentCommandOptions,
  InstrumentsOptions,
  OpenMultiviewOptions,
  OpenStackOptions,
  OpenTabOptions,
  OrderbookOptions,
  PlaceOrderOptions,
  PlaceTriggerOptions,
  SetLeverageOptions,
  SetMarginModeOptions,
  SettingsOptions,
  StackInstrumentOptions,
  TabItemOptions,
  StackOptions,
  StreamOptions,
  TabOptions,
  TerminalOptions,
  TradesOptions,
  WindowOptions,
} from "./client.ts";

export { Stream, StreamProtocol } from "./stream.ts";
export type { StreamConnectOptions, SubscribeOptions } from "./stream.ts";

export { DEFAULT_PORT, TOKEN_ENV, instancePath, readPort, tokenFromEnv } from "./discovery.ts";
export type { DiscoveryEnvironment, ReadPortOptions } from "./discovery.ts";

export {
  ApiError,
  IncompatibleTerminalError,
  LocalApiDisabledError,
  SpectreTerminalError,
  StreamClosedError,
  StreamRequestError,
  TerminalUnreachableError,
  TokenMissingError,
} from "./errors.ts";

export type * from "./types.ts";
