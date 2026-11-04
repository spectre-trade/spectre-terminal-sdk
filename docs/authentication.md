# Authentication

## The token

A token is `spt_` followed by 64 hex characters, issued by the terminal and
shown in **Settings App → General → Local API**. It is sent as a bearer token
in the `Authorization` header of every HTTP request and of the WebSocket
handshake:

```
Authorization: Bearer spt_…
```

A token in the query string is not accepted (URLs end up in logs). The
clients add the header for you and never put the token into error messages,
`repr`/`inspect` output or logs.

## Scopes

| Scope | Grants |
| --- | --- |
| `market:read` | catalogue, candles, intervals, trades, snapshot, order book, clusters, the market topics of the stream |
| `connections:read` | `/v1/connections` |
| `account:read` | `/v1/account/*` and the `account.*` stream topics |
| `trading:write` | `/v1/orders`, `/v1/orders/trigger`, `/v1/positions/close`, `/v1/account/leverage`, `/v1/account/margin-mode` |
| `workspace:read` | `/v1/workspace` and the `workspace` stream topic |
| `workspace:write` | opening, closing and selecting stacks, tabs and windows under `/v1/workspace` |
| `settings:read`, `settings:write` | granted ahead of the settings operations; no operation takes them yet |

`/v1/meta` and `/v1/health` need any valid token. All scopes are
granted: there is no separate write switch, the Local API toggle is the one
consent and the one kill switch (a product decision). `meta().scopes` tells
you what a token has; a terminal older than a scope simply does not list it,
and a missing scope answers `403 forbidden_scope`.

## Refusals

| Situation | Response | What the clients raise |
| --- | --- | --- |
| no token, a foreign token, or the API switched off | `401 unauthorized` | `ApiError` with code `unauthorized` |
| an `Origin` header (a browser page) | `403 forbidden` | — the clients never send one |
| `Host` not loopback | `403 forbidden` | — the clients only talk to loopback |
| missing scope | `403 forbidden_scope` | `ApiError` with code `forbidden_scope` |

`401` is deliberately the same for "wrong token" and "API off": it does not
tell a caller on the machine whether the API exists.

## Reissuing

**Reissue token** in the Settings App revokes the old token at once: HTTP
requests with it get `401`, and open streams are closed with code `1001`.
A client that reconnects must pick up the new token from its environment;
the clients do not cache the token anywhere.

## Keeping the token safe

- Put it in the environment of the one program that needs it, or in a
  secrets store your platform provides. Not in source, not in a config file
  you commit, not in a chat.
- The token grants read access to market data and to the list of exchange
  connections. It never exposes exchange keys: the API has no field for them,
  not even masked.
- If it leaks, reissue. There is no partial revocation; the terminal has one
  token.
