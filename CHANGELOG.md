# Changelog

All packages in this repository share one version and are released together.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
the versioning is [SemVer](https://semver.org/) against the Local API contract:
a new operation or field is a minor bump, a fix is a patch, a change of shape
is a major bump and happens only with a new API version of the terminal.

## [Unreleased]

## [0.1.0-rc.3] - 2026-11-09

No user-facing changes.

## [0.1.0-rc.2] - 2026-11-05

### Changed

- Releases are cut on every merge into `main` by `version-bump.yml`; the PR
  label picks the step (see CONTRIBUTING.md).

## [0.1.0-rc.1] - 2026-11-05

First published version, against Spectre Terminal 2.0.0 with Local API v1
(the exact build in `contract/TERMINAL_VERSION`).

### Added

- Python client `spectre-terminal`: REST operations of Local API v1, the
  `/v1/stream` client, discovery through `instance.json`, contract tests
  against the terminal fixtures.
- TypeScript client `@spectre-trade/terminal`: the same surface for Node 22+.
- MCP server `spectre-terminal-mcp`: the read tools over stdio on top of
  the Python client (`terminal_status`, `find_instrument`, `market_snapshot`,
  `order_book_top`, `recent_trades_summary`, `cluster_summary`, `candles`).
- Account: `account_orders`, `account_positions`, `account_balances`,
  `account_fills` and the `account.*` stream topics in both clients.
- Trading: `place_order`, `cancel_order`, `cancel_all`, `close_position`
  in both clients; `accepted` answers carry the terminal's order key.
- Trigger orders and leverage: `place_trigger`, `cancel_trigger`,
  `cancel_all_triggers`, `amend_trigger`, `leverage`, `set_leverage`,
  `set_margin_mode` in both clients, the `Leverage` model, and the MCP tools
  `leverage`, `place_trigger`, `cancel_trigger`, `amend_trigger`,
  `cancel_all_triggers`, `set_leverage`, `set_margin_mode`.
- Workspace: `workspace`, `workspace_window`, `open_stack`, `open_tab`,
  `add_stacks`, `open_multiview`, `set_stack_instrument`, `close_stack`,
  `close_tab`, `activate_tab`, `close_window`, `activate_window` in both
  clients, the `Workspace`, `Window`, `Tab`, `Stack`, `Chart`, `TabItem`
  and `WorkspaceOutcome` models, the `workspace` stream topic, and the MCP
  tools `workspace`, `open_stack`, `open_tab`, `add_stacks`,
  `open_multiview`, `set_stack_instrument`, `close_stack`, `close_tab`,
  `activate_tab`, `close_window`, `activate_window`.
- Settings: `settings`, `orderbook_settings`, `update_settings` in both
  clients, the `SettingRow`, `Settings`, `OrderbookSettings`,
  `SettingChange` and `SettingsApplied` models, the `settings` stream
  topic, and the MCP tools `settings`, `orderbook_settings`,
  `update_settings`.
- The contract copy (`contract/`) pinned to a terminal revision.
