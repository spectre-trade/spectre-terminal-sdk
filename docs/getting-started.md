# Getting started

The Local API runs inside the Spectre Terminal process on your machine. Nothing
leaves the computer: the clients connect to `127.0.0.1` and the terminal talks
to the exchanges exactly as it does for its own windows.

## 1. Switch the API on

Open the terminal's **Settings App → General** and switch **Local API** on.
The row shows the state of the listener and the port (`48180` unless the
terminal was started with `SPECTRE_LOCAL_API_PORT`). No restart is needed, and
the toggle can be switched off at any time; open streams are closed with code
`1001`.

## 2. Get the token

Press **Copy token** in the same row and put the token into the environment
of the program that will use it:

```bash
export SPECTRE_LOCAL_API_TOKEN=spt_…        # Linux, macOS
setx SPECTRE_LOCAL_API_TOKEN spt_…          # Windows, new shells
```

The token grants everything the terminal window can do, including placing
orders. Treat it as a
secret: do not commit it, do not paste it into a bug report. **Reissue token**
revokes it immediately.

## 3. First request

### Python

```bash
pip install spectre-terminal
```

```python
from spectre_terminal import Terminal

terminal = Terminal.discover()
meta = terminal.meta()
print(meta.app_version, meta.scopes, meta.topics)
```

### TypeScript

```bash
npm install @spectre-trade/terminal
```

```ts
import { Terminal } from "@spectre-trade/terminal";

const terminal = await Terminal.discover();
const meta = await terminal.meta();
console.log(meta.app_version, meta.scopes, meta.topics);
```

`discover()` finds the port, reads the token from the environment and calls
`/v1/meta` once, so a wrong token or a terminal that is not running fails
here with a clear error rather than on the first data call. See
[Discovery](discovery.md) and [Errors](errors.md).

## 4. Read something

```python
for connection in terminal.connections():
    print(connection.id, connection.exchange, connection.market, connection.status.state)

book = terminal.orderbook("binance:futures:BTCUSDT", depth=5)
for price, size in book.bids:
    print(price, size)
```

Instruments are addressed as `exchange:market:symbol` — `binance:futures:BTCUSDT`,
`bybit:spot:BTCUSDT` — with the symbol spelled as the exchange spells it. The
catalogue of each connection is available from `instruments(...)`; see
[Market data](market-data.md).

## 5. Go live

```python
import asyncio

async def main():
    async with terminal.stream() as stream:
        await stream.subscribe("trades", "binance:futures:BTCUSDT")
        async for frame in stream:
            print(frame)

asyncio.run(main())
```

Everything about subscriptions, gaps, conflation and close codes is in
[Streaming](streaming.md).

## What the API does not do

Version 1 does not answer for the outcome on the exchange: `accepted` means
accepted by the terminal, and the outcome is read from the account. Data of
MOEX is not served and there is no trading on MOEX. Requests from browser pages are refused (the API has no
CORS layer on purpose), so the clients are for scripts, bots and desktop
tools, not for web pages.
