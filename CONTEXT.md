# Context

What this repository is, the decisions it rests on, and the rules that keep
it honest. For people and for coding agents alike.

## What

Client libraries and an MCP server for the **Local API** of Spectre
Terminal: a read-only HTTP/JSON and WebSocket/JSON interface the terminal
serves on `127.0.0.1` when the trader switches it on. The API contract is
owned by the terminal; this repository consumes it.

## Decisions

- **Separate, public repository.** The terminal is closed source; its SDK
  must be public. The SDK has its own languages, toolchain and release
  cadence, and needs no terminal build in CI.
- **The terminal is the source of truth for the contract.** `contract/`
  holds a verbatim copy of the contract and of the response fixtures, pinned
  to a terminal revision in `contract/TERMINAL_VERSION`. Tests run against the
  fixtures. There is no second description of the API anywhere in this
  repository: types are written from the contract and kept honest by the
  fixtures.
- **Two languages, not three.** Python for scripts and the MCP server,
  TypeScript for bots and web tooling. Each addition to the contract costs
  one change per language; a third language is a separate decision.
- **Compatibility is read from `/v1/meta`.** Three independent numbers:
  terminal version, API version (`/v1`), package version (SemVer, one for all
  packages). A client checks the API version on connect and fails with a
  clear error on a terminal it does not support. Unknown fields, topics and
  scopes never break a client: within v1 the contract only grows.
- **MCP lives here, not in the terminal.** `mcp/` is a package on top of the
  Python client with a stdio transport and read-only tools designed for a
  model (compact answers: snapshot, best prices, cluster summaries), not a
  mirror of the HTTP endpoints. An MCP endpoint inside the terminal is
  deferred; it would be revisited only if traders must install nothing but
  the terminal.
- **Discovery and the token.** The port comes from `instance.json` next to
  the terminal's database, falling back to `48180`. The token comes only from
  `SPECTRE_LOCAL_API_TOKEN` or an explicit constructor argument. Clients never
  read the terminal's database or search the disk for a token, and never put
  the token into logs, errors or reports.
- **Everything in English.** Code, comments, commits, docs. No links to
  private resources.

## Rules for changes

- The contract copy is updated only by `scripts/sync_contract.py`. A new
  field in a fixture that a model does not know is a failing test and a
  reason to extend the model.
- A change to one client is a change to the other, in the same pull request.
- Money stays decimal: `decimal.Decimal` in Python, `string` in TypeScript.
  Never `float`, never `Number`.
- The public surface of each client has the same four modules: `client`,
  `stream`, `models`/`types`, `discovery`, plus `errors`.
- Examples are runnable and double as the live smoke check.
- No running terminal in CI; the live check is manual.

## Open product decisions

- npm: scoped `@spectre-trade/*` (preferred) or flat `spectre-terminal*`.
- Documentation hosting: GitHub Pages from `docs/` or GitBook.
- The moment the repository goes public: with the first terminal release
  that ships the Local API (preferred).
