# Settings

The terminal's settings table — terminal-wide settings and the settings of
each stack — with the `settings:read` and `settings:write` scopes. A write
goes through the **same path as the Settings App**: the same row, the same
event to the window, the same service caches and the same exchange commands
(a cluster interval, the average-price mode). The one difference: the
terminal checks every change against its catalogue before writing, because
it trusts its own window and not an external program.

```python
from spectre_terminal import SettingChange

rows = terminal.settings(category="multiview")          # terminal-wide rows
book = terminal.orderbook_settings(12, "binance:futures:BTCUSDT")
print(book.get("general", "auto_scroll"))               # value, resolved_from, writable

terminal.update_settings([
    SettingChange("multiview", "stack_width_px", 300),
    SettingChange("general", "auto_scroll", True,
                  instrument="binance:futures:BTCUSDT", connection_id=12),
    SettingChange("trading", "slippage", {"value": "0.1", "type": "percent"},
                  scope="order_book", connection_id=12),   # the connection's default
    SettingChange("appearance", "theme", {"stack": "dark"}),
])
```

```ts
const rows = await terminal.settings({ category: "multiview" });
const book = await terminal.orderbookSettings({ connectionId: 12, instrument: "binance:futures:BTCUSDT" });
await terminal.updateSettings([
  { category: "multiview", key: "stack_width_px", value: 300 },
  { instrument: "binance:futures:BTCUSDT", connection_id: 12, category: "general", key: "auto_scroll", value: true },
]);
```

## Rows and scopes

A row is `scope`, `scope_id`, `connection_id`, `category`, `key`, `value`.
Two scopes: `global` (the terminal; `scope_id` is `default`, `null` for
hotkeys) and `order_book` (a stack; `scope_id` is an instrument address or
`default`, `connection_id` a connection or `null`). `settings()` lists rows
as stored, without any resolution; each row carries `writable`, which is
`false` for leverage (`trading/leverage_mode` has its own operation, see
[trading.md](trading.md)) and for the terminal's service rows.

## The ladder of a stack

A stack resolves its settings the way the window does: the pair's row on
the connection, then the connection's default, then the pair's row without
a connection, then the global default. `orderbook_settings()` returns the
result per category and key with `resolved_from` naming the level:
`instrument`, `connection`, `app_instrument` or `global`. A stack the
window has opened usually shows `instrument` everywhere: the terminal
freezes the resolved defaults into the pair's rows on first open.

## Writing

`update_settings()` takes a list of changes. Where a change lands:

| Change | Row |
| --- | --- |
| `instrument` given | the pair's row on the connection chosen by the general rule, or `connection_id` |
| `scope="order_book"`, `connection_id`, no instrument | the connection's default |
| `scope="order_book"`, nothing else | the global stack default |
| anything else | the global setting; `connection_id` is refused |

Every change is checked first: an unknown key, a wrong type, a number out
of range, an enum value the terminal does not know, an object whose shape
differs from the terminal's default — `invalid_request` naming
`changes[i]`, and nothing is written. Leverage through settings is
`unsupported`. Then the changes are applied in order; the first one the
terminal could not apply stops the list and raises, the earlier ones stay
applied (the window already knows about them). The answer is
`{ "applied": n }`.

Theme (`appearance/theme`, an object with any of `stack`, `graphic`,
`interface`), font (`appearance/font_family`), language
(`localization/current_language`) and hotkeys (`hotkeys_*`, a
`{code, modifiers}` binding or `null`; a combination another action already
uses is refused) go through their own services, exactly as the Settings App
sends them. Writes are limited to `meta.limits.settings_commands_per_second`
(5) requests per second per listener.

## The `settings` topic

Subscribe to `settings` (no instrument, no connection) to get a frame for
**every row written** to the table — by the API, by the Settings App, or by
the window itself (compression by wheel, volume presets). There is no
snapshot on subscribe; read the current state with `settings()` first. A
frame is a row without `writable`. See [streaming.md](streaming.md).
