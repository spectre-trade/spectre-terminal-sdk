"""``find_instrument``: from a coin or symbol to the exact instrument address."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field
from spectre_terminal import Terminal
from spectre_terminal.models import Instrument

from ..summaries import instrument_row
from ..terminal import TerminalProvider

__all__ = ["register"]

MAX_MATCHES = 50
# Quotes a trader means by default, best first; anything else ranks after them.
_QUOTE_ORDER = {"USDT": 0, "USD": 1, "USDC": 2}


def _pairs(terminal: Terminal, exchange: str | None, market: str | None) -> list[tuple[str, str]]:
    """Distinct (exchange, market) pairs of enabled connections, narrowed by the arguments."""
    seen: list[tuple[str, str]] = []
    for connection in terminal.connections():
        if not connection.enabled:
            continue
        if exchange and connection.exchange != exchange.lower():
            continue
        if market and connection.market != market.lower():
            continue
        pair = (connection.exchange, connection.market)
        if pair not in seen:
            seen.append(pair)
    return seen


def _rank(query: str) -> Any:
    """Exact symbol, then exact base coin, then a base behind a numeric prefix, then prefixes.

    Within a rank the usual quotes come first (USDT, USD, USDC), then shorter
    symbols: ``ETHUSDT`` before ``ETHUSDT_260327`` and before ``ETHBRL``.
    """
    wanted = query.upper()

    def key(instrument: Instrument) -> tuple[int, int, int, str]:
        symbol = instrument.symbol.upper()
        base = instrument.base.upper()
        if symbol == wanted:
            rank = 0
        elif base == wanted:
            rank = 1
        elif base.lstrip("0123456789") == wanted:
            rank = 2
        elif symbol.startswith(wanted) or base.startswith(wanted):
            rank = 3
        else:
            rank = 4
        quote = instrument.quote.upper()
        quote_rank = _QUOTE_ORDER.get(quote, len(_QUOTE_ORDER))
        return (rank, quote_rank, len(symbol), symbol)

    return key


def register(server: MCPServer, provider: TerminalProvider) -> None:
    from . import READ_ONLY

    @server.tool(name="find_instrument", annotations=READ_ONLY)
    def find_instrument(
        query: Annotated[
            str,
            Field(description="Coin or symbol fragment, case-insensitive: BTC, ETHUSDT, SOL-USDT"),
        ],
        exchange: Annotated[
            str | None,
            Field(description="Exchange in lower case: binance, bybit, okx, …; all when omitted"),
        ] = None,
        market: Annotated[
            str | None,
            Field(description="spot or futures; both when omitted"),
        ] = None,
        connection_id: Annotated[
            int | None,
            Field(description="Search one connection only (from terminal_status)"),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=MAX_MATCHES, description="Matches to return")] = 10,
    ) -> dict[str, Any]:
        """Find the exact instrument address for a coin or symbol.

        Searches the catalogue of the terminal's connections — one connection,
        one exchange, or all of them — and returns matches best first: an
        exact symbol or base coin, then the same base behind a numeric prefix
        (1000PEPE), then prefixes. Use the ``instrument`` field of a match in
        every other tool.
        """
        matches: list[tuple[str, int | None, Instrument]] = []
        truncated = False
        with provider.call() as terminal:
            if connection_id is not None:
                page = terminal.instruments(connection_id=connection_id, q=query, limit=MAX_MATCHES)
                matches.extend((page.exchange, connection_id, i) for i in page.data)
                truncated = page.next_cursor is not None
            else:
                for pair_exchange, pair_market in _pairs(terminal, exchange, market):
                    page = terminal.instruments(
                        exchange=pair_exchange, market=pair_market, q=query, limit=MAX_MATCHES
                    )
                    matches.extend((pair_exchange, None, i) for i in page.data)
                    truncated = truncated or page.next_cursor is not None
        ranked = sorted(matches, key=lambda m: _rank(query)(m[2]))
        rows = []
        for _exchange, pinned, instrument in ranked[:limit]:
            row = instrument_row(instrument)
            row["exchange"] = instrument.exchange
            row["market"] = instrument.market
            if pinned is not None:
                row["connection_id"] = pinned
            rows.append(row)
        return {
            "query": query,
            "matches": rows,
            "total_found": len(matches),
            "truncated": truncated or len(matches) > limit,
        }
