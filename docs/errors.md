# Errors

Every non-2xx HTTP response carries one body:

```json
{ "error": { "code": "unauthorized", "message": "token does not match" } }
```

The **code** is stable and part of the contract; the **message** is for
humans and may change. The same codes appear in stream `error` frames. The
clients raise `ApiError` with `code`, `message` and `status` (HTTP) and never
include the token in the text.

| Code | HTTP | When | What to do |
| --- | --- | --- | --- |
| `unauthorized` | 401 | the token does not match, or the API is switched off | copy the current token from the Settings App; check the toggle |
| `forbidden` | 403 | an `Origin` header or a foreign `Host` | you are not using the SDK, or something rewrote the request |
| `forbidden_scope` | 403 | the token lacks the operation's scope | see `meta().scopes` |
| `not_found` | 404 | unknown path, unknown connection, or no connection for the instrument's venue and market | check the instrument address and `connections()` |
| `invalid_request` | 400 | bad instrument, an instrument the terminal catalogue does not know, interval, depth, cursor, or a `connection_id` of another venue | fix the parameters |
| `unsupported` | 501 | the venue is not relayed (MOEX), the terminal was built without the market-data tap (`meta().topics` lists only `workspace` and `settings`), or a setting is not written through the API (leverage, the terminal's service rows) | nothing to retry |
| `not_active` | 409 | clusters of the instrument are not computed yet, or its leverage is not loaded yet | clusters: retry in a few seconds, the subscription is held; leverage: open the instrument in the terminal or set the leverage |
| `rate_limited` | 429 | stream connections, subscriptions, API-only instruments, the per-second subscription rate, more than 10 trading commands, 5 workspace commands or 5 settings writes per second | wait and retry; reuse connections |
| `not_tradable` | 409 | the connection does not trade: disabled, read-only, or without credentials | pick a trading connection from `connections()` |
| `unavailable` | 503 | the exchange, storage or coordinator did not answer; no data within 3 s; no terminal window to apply a workspace command, or it did not answer within 2 s | retry later |

## Client-side errors

Raised before or instead of a request:

| Error | Meaning |
| --- | --- |
| `TokenMissing` | no token argument and `SPECTRE_LOCAL_API_TOKEN` is not set |
| `LocalApiDisabled` | `instance.json` says the API is switched off |
| `TerminalUnreachable` | connection refused or timed out: the terminal is not running, or listens on another port |
| `IncompatibleTerminal` | `/v1/meta` reports an API version this client does not support |
| `StreamRequestError` | a `subscribe`/`unsubscribe` was refused (carries the code above) |
| `StreamClosed` | the server closed the stream with `1001`, `4008` or `4029` |

All of them extend `SpectreTerminalError` (`SpectreTerminalError` in Python,
the same name in TypeScript), so `except SpectreTerminalError` / `catch`
on the base class covers everything the SDK raises on purpose.
