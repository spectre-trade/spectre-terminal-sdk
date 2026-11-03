# Contributing

## Layout

```
contract/        the Local API contract and response fixtures, copied from the terminal — read-only
python/          spectre-terminal (Python 3.10+)
typescript/      @spectre-trade/terminal (Node 22+)
mcp/             spectre-terminal-mcp, the MCP server on top of the Python client
docs/            guides; the API reference is generated from the code
scripts/         maintainer scripts
```

Each client has the same four modules — `client` (REST), `stream`
(WebSocket), `models`/`types` (the contract's DTOs), `discovery` (port and
token) — plus `errors`. Keep the two clients in step: a change to one is a
change to the other in the same pull request.

## The contract is read-only

`contract/contract-v1.md` and `contract/fixtures/` are copied from the
terminal repository and pinned to its revision in `contract/TERMINAL_VERSION`.
Do not edit them by hand. To update the copy from a local checkout of the
terminal:

```bash
python3 scripts/sync_contract.py /path/to/spectre-terminal
```

The script copies the contract and the fixtures and records the terminal
commit. A field that appears in a fixture and is missing from a client model
is a failing contract test in that client — that is the signal to extend the
model, never to touch the fixture.

## Tests

Tests run against the fixtures; no running terminal is needed.

```bash
# Python
cd python
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest

# TypeScript
cd typescript
npm ci
npm test
npm run typecheck
```

A live smoke check against a running terminal (Local API on, token in
`SPECTRE_LOCAL_API_TOKEN`):

```bash
python/.venv/bin/python python/examples/smoke.py
node typescript/examples/smoke.ts
```

## Style

- English everywhere in this repository: code, comments, commit messages,
  documentation.
- No secrets, no real account names or identifiers in fixtures, examples or
  tests; the fixtures are synthetic.
- No links to private resources (issue trackers, internal repositories).
- Python: `ruff` for lint and format, type hints on the public surface.
  TypeScript: `tsc --strict`, ESM only, no runtime dependencies.

## Releasing

One version for all packages, in `CHANGELOG.md`. A tag `vX.Y.Z` publishes
every package through GitHub Actions (PyPI trusted publishing, npm
provenance). There are no long-lived registry tokens in the repository.
