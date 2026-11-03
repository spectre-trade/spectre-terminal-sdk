# spectre-terminal

Python client for the **Local API** of Spectre Terminal: connections, the
instrument catalogue, trades, order books, clusters and candles from a
running terminal on the same machine, over HTTP and WebSocket on
`127.0.0.1`.

- Python 3.10+, one dependency (`websockets`), HTTP through the standard library.
- Money is `decimal.Decimal`, never `float`; timestamps are `int` UTC milliseconds.
- The token is taken only from `SPECTRE_LOCAL_API_TOKEN` or the constructor
  argument and never appears in errors or logs.

## Install

```bash
pip install spectre-terminal
```

Switch the API on in the terminal: **Settings App → General → Local API**,
then **Copy token** and keep it in `SPECTRE_LOCAL_API_TOKEN`.

## Quick start

```python
from spectre_terminal import Terminal

terminal = Terminal.discover()  # port from instance.json, token from SPECTRE_LOCAL_API_TOKEN

for connection in terminal.connections():
    print(connection.id, connection.exchange, connection.market, connection.status.state)

snapshot = terminal.snapshot("binance:futures:BTCUSDT")
print(snapshot.best_bid, snapshot.best_ask, snapshot.last_trade)

book = terminal.orderbook("binance:futures:BTCUSDT", depth=10)
print(book.bids[0], book.asks[0])
```

Live data over the stream:

```python
import asyncio
from spectre_terminal import Terminal


async def main():
    terminal = Terminal.discover()
    async with terminal.stream() as stream:
        await stream.subscribe("trades", "binance:futures:BTCUSDT")
        await stream.subscribe("book.top", "binance:futures:BTCUSDT", depth=5, interval_ms=200)
        async for frame in stream:
            print(frame)


asyncio.run(main())
```

Every operation of the contract is a method of `Terminal`: `meta`, `health`,
`connections`, `connection`, `instruments` / `iter_instruments`,
`intervals`, `candles`, `trades`, `snapshot`, `orderbook`, `clusters`,
`stream`. Errors derive from `SpectreTerminalError`; the terminal's own
refusals are `ApiError` with the contract's `code` and the HTTP `status`.

Runnable scripts live in [`examples/`](examples/); `examples/smoke.py` calls
every operation once against a running terminal.

## Documentation

The guides are in [`../docs`](../docs); the authoritative description of
the API is [`../contract/contract-v1.md`](../contract/contract-v1.md).

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests run against the fixtures in `../contract/fixtures`; no terminal is
needed.
