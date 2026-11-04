# Workspace

What the terminal shows — windows, tabs, stacks (an order book with its
trade tape and clusters) and charts — and the commands that change it, with
the `workspace:read` and `workspace:write` scopes.

```python
layout = terminal.workspace()
main = layout.main
for tab in main.tabs:
    print(tab.id, tab.name, [s.instrument for s in tab.stacks])

opened = terminal.open_stack("binance:futures:BTCUSDT", chart=True, activate=False)
terminal.set_stack_instrument(opened.stacks[0], "binance:futures:ETHUSDT")
terminal.activate_tab(opened.window_id, opened.tab_id)
terminal.close_stack(opened.stacks[0])
terminal.close_tab(opened.window_id, opened.tab_id)

grid = terminal.open_multiview("BTC", target="new_window")
terminal.activate_window(grid.window_id)
terminal.close_window(grid.window_id)
```

```ts
const layout = await terminal.workspace();
const main = layout.data.windows.find((w) => w.main)!;

const opened = await terminal.openStack({ instrument: "binance:futures:BTCUSDT", chart: true, activate: false });
await terminal.setStackInstrument({ widgetId: opened.stacks[0]!, instrument: "binance:futures:ETHUSDT" });
await terminal.activateTab({ windowId: opened.window_id!, tabId: opened.tab_id! });
await terminal.closeStack({ widgetId: opened.stacks[0]! });
await terminal.closeTab({ windowId: opened.window_id!, tabId: opened.tab_id! });

const grid = await terminal.openMultiview({ base: "BTC", target: "new_window" });
await terminal.closeWindow({ windowId: grid.window_id! });
```

## Reading never waits on the window

`GET /v1/workspace` answers from a snapshot the window publishes at every
structural change (a stack added or closed, a coin picked, a window opened
or closed, a tab moved), on a focus change and after every API command.
The window's thread takes no part in a read, and a frozen window answers
with its last known layout rather than an error.

Every window carries `main` (the one whose close quits the terminal),
`chart_window` (a torn-off chart), `focused`, its geometry in logical
screen pixels and the monitor name. Exactly one tab per window is `active`.
A stack has a global `widget_id`, its `instrument` and `connection_id`
(`null` while `empty`), `frozen`, and its `position` in the tab's grid
(column, row, cell; `null` inside a stack group). A chart adds the
`interval` and `owner_widget_id`, the stack it follows.

## Ids live one run

`window_id` and `widget_id` are global for the current run of the terminal;
`tab_id` is numbered per window from 1, so tabs are addressed by window and
tab together. After a restart every number is different: read the layout
again instead of keeping ids, and subscribe to the `workspace` topic to
follow changes (the first frame is the current snapshot).

## Commands are applied by the window

A write is a command to the window, applied through the same paths a click
takes: a new tab via the Multiview opener, a tab close through the tab's
close path, a stack close as the stack's close button, a window close as
the window's close button. There are no confirmation dialogs. The window
answers after it published the new snapshot, so a `GET` right after the
answer shows the change, and the answer itself names what appeared:

```json
{ "window_id": 1, "tab_id": 2, "stacks": [14], "charts": [15] }
```

For a close or an activation the touched ids are filled in and the rest is
`null` or empty.

| Call | Does | Refuses with |
| --- | --- | --- |
| `open_stack` / `openStack` | a stack of the instrument, with a chart if asked, in a new tab (`target: "new_tab"`, in `window_id` or the focused window) or a new window; `activate: false` keeps the current tab selected | `invalid_request` for an instrument the catalogue does not know |
| `open_tab` / `openTab` | a tab with a column per item of `items` — a stack and, with `chart`, a chart over it — in a new tab or window; one to fifty items; `name` optional, up to 64 characters | `invalid_request` naming the item (`items[1]: …`); nothing is opened |
| `add_stacks` / `addStacks` | the same columns after the last column of an existing tab (`window_id`, `tab_id`); the tab keeps its name and widths; answers only the added widgets | `not_found` for the window or tab |
| `open_multiview` / `openMultiview` | the coin on every venue of «Exchange layout», as the Multiview button; `target` left out follows the terminal setting | `not_found` when no enabled row lists the coin |
| `set_stack_instrument` / `setStackInstrument` | another instrument in the stack and the charts that follow it | `not_found`; `invalid_request` for a chart id |
| `close_stack` / `closeStack` | closes one stack | `not_found`; `invalid_request` for a chart id |
| `close_tab` / `closeTab` | closes a tab | `invalid_request` for the only tab of a window |
| `activate_tab` / `activateTab` | selects the tab; the window's focus is untouched | `not_found` |
| `close_window` / `closeWindow` | closes a window | `invalid_request` for the main window |
| `activate_window` / `activateWindow` | restores a minimised window and brings it to the front | `not_found` |

A stack in a non-active tab makes that tab active for the duration of the
command and restores the previous tab afterwards. Commands are limited to
`meta.limits.workspace_commands_per_second` (5) per listener; beyond that
`rate_limited`. With no window at all, or a window that did not answer
within 2 s, the answer is `unavailable` and the command is not retried.

## What is not there

Empty windows, the screener, finres and orders windows, moving stacks
between tabs and column widths: the layout reports them, the API does not
change them. Columns are added only after a tab's last one.
