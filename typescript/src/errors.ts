/**
 * Error types thrown by the client.
 *
 * Every error extends {@link SpectreTerminalError}, so `instanceof` on the
 * base class catches anything this package throws. None of them ever carries
 * the token: messages name hosts, ports, paths and the server's own text only.
 *
 * @module
 */

/** Base class of every error thrown by this package. */
export class SpectreTerminalError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "SpectreTerminalError";
  }
}

/**
 * The terminal answered with a non-2xx status.
 *
 * `code` is the stable code from the contract's error envelope
 * (`unauthorized`, `not_found`, `rate_limited`, …); `status` is the HTTP
 * status. A non-2xx body that is not the envelope gives code `"unknown"`.
 */
export class ApiError extends SpectreTerminalError {
  /** Stable error code from the contract, or `"unknown"`. */
  readonly code: string;
  /** HTTP status of the response. */
  readonly status: number;
  /** The server's human-readable message, unprefixed. */
  readonly detail: string;

  constructor(code: string, detail: string, status: number, options?: ErrorOptions) {
    super(`${code} (HTTP ${status}): ${detail}`, options);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

/**
 * No HTTP response at all: connection refused, request timed out, an
 * unexpected redirect, or a WebSocket handshake that did not complete.
 * The original failure is in `cause`.
 */
export class TerminalUnreachableError extends SpectreTerminalError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "TerminalUnreachableError";
  }
}

/**
 * `instance.json` exists but publishes no Local API port: the terminal is
 * running with the API switched off, or the file was left behind by a
 * terminal that did not shut down cleanly. Either way there is no port to
 * connect to until the API is enabled in the Settings App (General → Local
 * API).
 */
export class LocalApiDisabledError extends SpectreTerminalError {
  constructor(
    message = "The terminal's instance.json publishes no Local API port: the Local API is switched off, or the file is left over from a terminal that is no longer running. Enable it in Settings App → General → Local API.",
  ) {
    super(message);
    this.name = "LocalApiDisabledError";
  }
}

/** Neither the `token` option nor `SPECTRE_LOCAL_API_TOKEN` provided a token. */
export class TokenMissingError extends SpectreTerminalError {
  constructor(
    message = "No Local API token: pass { token } or set SPECTRE_LOCAL_API_TOKEN. Copy it in the terminal: Settings App → General → Local API → Copy token.",
  ) {
    super(message);
    this.name = "TokenMissingError";
  }
}

/** `/v1/meta` reported an API version this client does not speak. */
export class IncompatibleTerminalError extends SpectreTerminalError {
  /** The `api_version` the terminal reported. */
  readonly apiVersion: string;
  /** The `app_version` the terminal reported. */
  readonly appVersion: string;

  constructor(apiVersion: string, appVersion: string) {
    super(
      `The terminal (version ${appVersion}) serves Local API version "${apiVersion}", this client supports version "1". Update the client or the terminal.`,
    );
    this.name = "IncompatibleTerminalError";
    this.apiVersion = apiVersion;
    this.appVersion = appVersion;
  }
}

/**
 * The stream answered a `subscribe` or `unsubscribe` request with an `error`
 * frame. `code` is the contract's error code (`not_found`, `rate_limited`,
 * `invalid_request`, …). Other subscriptions keep flowing.
 */
export class StreamRequestError extends SpectreTerminalError {
  /** Stable error code from the contract. */
  readonly code: string;
  /** The server's human-readable message, unprefixed. */
  readonly detail: string;

  constructor(code: string, detail: string) {
    super(`${code}: ${detail}`);
    this.name = "StreamRequestError";
    this.code = code;
    this.detail = detail;
  }
}

/**
 * The stream was closed by the server for a reason the consumer must act on:
 * `1001` — the API was switched off or the token was reissued; `4008` — this
 * client read too slowly; `4029` — the per-token connection limit. It is also
 * raised for `1006` when the connection dropped without a close frame, and by
 * `subscribe` / `unsubscribe` on an already closed stream.
 */
export class StreamClosedError extends SpectreTerminalError {
  /** WebSocket close code. */
  readonly code: number;
  /** Close reason sent by the server, possibly empty. */
  readonly reason: string;

  constructor(code: number, reason: string) {
    super(`stream closed with code ${code}${reason ? `: ${reason}` : ""}`);
    this.name = "StreamClosedError";
    this.code = code;
    this.reason = reason;
  }
}
