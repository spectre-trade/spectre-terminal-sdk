# Compatibility

Three numbers move independently:

| Number | Where | Meaning |
| --- | --- | --- |
| terminal version | `meta().app_version`, e.g. `2.0.0` | the Spectre Terminal release |
| API version | `meta().api_version`, the `/v1` path | the contract; grows only additively within a version |
| SDK version | the package version; one for all packages in this repository | SemVer against the contract |

## What the clients check

`discover()` (and the first request otherwise) reads `/v1/meta`:

- `api_version` is not one this client supports → `IncompatibleTerminal`.
  The clients in this repository support API **v1**.
- `topics` is empty → the terminal was built without the market-data tap;
  market operations and the stream answer `unsupported`. The clients do not
  fail early on this; the error comes with the first market call.

Unknown fields in any response are ignored, and unknown topics or scopes in
`meta()` do not break anything: a newer terminal keeps working with an older
client, and the client simply does not expose what it does not know.

## Matrix

| SDK | API | Terminal |
| --- | --- | --- |
| 0.1.x | v1 | the first release that ships the Local API, and later |

Within API v1, a terminal newer than the SDK is always fine. An SDK newer than
the terminal works too; a method for an operation the terminal does not have
yet answers `not_found`.

## Versioning of the packages

- **Patch** — a fix with no change to the public surface.
- **Minor** — a new operation, field, topic or option added to the contract
  and exposed by the clients.
- **Major** — a change of shape, which only happens with a new API version of
  the terminal (`/v2`).

The contract copy in `contract/` is pinned to a terminal revision in
`contract/TERMINAL_VERSION`; the changelog names the terminal version each
SDK release was developed against.
