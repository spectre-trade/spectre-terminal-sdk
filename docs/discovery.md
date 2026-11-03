# Discovery

A client needs two things: the port the terminal listens on and the token.
`Terminal.discover()` finds both; `new Terminal({...})` / `Terminal(token=...)`
takes them explicitly.

## The port

The port is fixed at `48180` unless the terminal was started with
`SPECTRE_LOCAL_API_PORT`. Whatever it is, the terminal publishes it as the
`local_api_port` field of `instance.json`, which lives next to its database:

| OS | Path |
| --- | --- |
| Linux | `$XDG_DATA_HOME/spectre-terminal/instance.json`, by default `~/.local/share/spectre-terminal/instance.json` |
| macOS | `~/Library/Application Support/spectre-terminal/instance.json` |
| Windows | `%LOCALAPPDATA%\spectre-terminal\instance.json` |

```json
{ "pid": 108957, "http_port": 46727, "local_api_port": 48180 }
```

- `local_api_port` is absent (or `null`) while the API is switched off: the
  clients raise `LocalApiDisabled` with a pointer to the Settings App toggle.
- The file is missing when the terminal is not running (or has never run):
  the clients fall back to `48180` and the first request fails with
  `TerminalUnreachable`.
- `http_port` is the server of the terminal's own Settings App. It is not
  the Local API and the clients never use it.

The clients read nothing else from the terminal's data directory.

## The token

The token comes from the `SPECTRE_LOCAL_API_TOKEN` environment variable or
from the constructor argument — nowhere else. It is deliberately not
discoverable: the Settings App shows it to the trader, and the trader decides
which program gets it. A client without a token raises `TokenMissing`.

## Overriding

```python
Terminal(token, port=48181)                       # explicit
Terminal.discover(port=48181)                     # skip instance.json
```

```ts
new Terminal({ token, port: 48181 });
await Terminal.discover({ port: 48181 });
```

The host is always loopback. The API answers only to `Host: 127.0.0.1` or
`localhost`, and the clients do not follow redirects anywhere else.

## Several terminals

One terminal per machine is the supported case: `instance.json` describes the
running instance, and the port is fixed. If you run a second instance on
another port for testing, pass the port explicitly.
