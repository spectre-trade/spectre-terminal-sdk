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

# MCP server (needs the Python client from this checkout)
cd mcp
python3 -m venv .venv && .venv/bin/pip install -e ../python -e '.[dev]'
.venv/bin/pytest
```

A live smoke check against a running terminal (Local API on, token in
`SPECTRE_LOCAL_API_TOKEN`):

```bash
python/.venv/bin/python python/examples/smoke.py
node typescript/examples/smoke.ts
mcp/.venv/bin/python mcp/examples/smoke.py
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
every package through GitHub Actions (`release.yml`: PyPI trusted publishing
from the `pypi` environment for `spectre-terminal` and `pypi-mcp` for
`spectre-terminal-mcp` — PyPI wants a distinct environment per project —, npm
trusted publishing with provenance from the `npm` environment). There are no long-lived registry tokens in the repository.

Every merge into `main` is a release (`version-bump.yml`), and the PR's
label says how big:

| Label | Next version |
| --- | --- |
| `patch` (default when no label) | `X.Y.Z+1` |
| `minor` | `X.Y+1.0` — a new operation, field, model or MCP tool |
| `major` | `X+1.0.0` — a new API version of the terminal |
| `rc` | the next release candidate; from a stable version `X.Y.Z+1-rc.1` |
| `release` | the candidate becomes the stable `X.Y.Z` |
| `no-release` | nothing is published — docs, CI, housekeeping |

While the current version is a candidate, the default is `rc` and only `rc`
and `release` are accepted. After the merge the workflow writes the version
into the three manifests (`X.Y.Z-rc.N` in `package.json`, `X.Y.ZrcN` in the
two `pyproject.toml`), turns the `[Unreleased]` section of `CHANGELOG.md`
into `[X.Y.Z] - date`, commits to `main`, tags `vX.Y.Z` and dispatches
`release.yml` on it. So a PR only has to describe its change under
`[Unreleased]`; the version is never edited by hand. A candidate goes to npm
under the `next` dist-tag and to GitHub as a pre-release.

`contract/TERMINAL_VERSION` names the terminal build the packages promise;
a stable version is released only against a terminal release that is
shipped. `release.yml` refuses a tag whose version differs from any manifest
or has no changelog section, and skips an npm version that is already on
the registry, so a tag pushed by hand (`git tag vX.Y.Z && git push origin
vX.Y.Z`) works the same way.

The very first npm publish of `@spectre-trade/terminal` is made by hand
(`npm publish --access public` from `typescript/` with a 2FA code): npm lets a
trusted publisher be configured only on a package that already exists. After
that, the package settings on npmjs.com get this repository and `release.yml`
as the trusted publisher, and every later release comes from the tag.
