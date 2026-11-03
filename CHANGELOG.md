# Changelog

All packages in this repository share one version and are released together.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
the versioning is [SemVer](https://semver.org/) against the Local API contract:
a new operation or field is a minor bump, a fix is a patch, a change of shape
is a major bump and happens only with a new API version of the terminal.

## [Unreleased]

### Added

- Python client `spectre-terminal`: REST operations of Local API v1, the
  `/v1/stream` client, discovery through `instance.json`, contract tests
  against the terminal fixtures.
- TypeScript client `@spectre-trade/terminal`: the same surface for Node 22+.
- MCP server `spectre-terminal-mcp`: seven read-only tools over stdio on top of
  the Python client (`terminal_status`, `find_instrument`, `market_snapshot`,
  `order_book_top`, `recent_trades_summary`, `cluster_summary`, `candles`).
- The contract copy (`contract/`) pinned to a terminal revision.
