"""The stream client against a scripted ``websockets`` server, plus the pure router."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from conftest import TOKEN, load_fixture
from websockets.asyncio.server import ServerConnection, serve

from spectre_terminal import (
    ApiError,
    BookTop,
    Event,
    Fill,
    Gap,
    Order,
    OrdersUpdate,
    Stream,
    StreamClosed,
    StreamRequestError,
    Subscribed,
    SubscriptionError,
    Terminal,
    TerminalUnreachable,
    Trade,
    Unsubscribed,
)
from spectre_terminal.stream import FrameRouter, Reply

INSTRUMENT = "binance:futures:BTCUSDT"
UNKNOWN = "nowhere:spot:NONE"
CLOSE_4008 = "close:4008:SLOW"


class ScriptedServer:
    """Answers like the terminal: subscribed/error replies, then canned frames."""

    def __init__(self) -> None:
        self.handshakes: list[Any] = []
        self.requests: list[dict[str, Any]] = []
        self.closed_with: int | None = None

    def process_request(self, connection: ServerConnection, request: Any) -> Any:
        self.handshakes.append(request.headers)
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            body = json.dumps(
                {"error": {"code": "unauthorized", "message": "a valid bearer token"}}
            )
            return connection.respond(401, body)
        return None

    async def handle(self, connection: ServerConnection) -> None:
        try:
            async for raw in connection:
                request = json.loads(raw)
                self.requests.append(request)
                for frame in self.replies(request):
                    await connection.send(json.dumps(frame))
                if request.get("instrument") == CLOSE_4008:
                    await connection.close(4008, "slow consumer")
                    return
        finally:
            self.closed_with = connection.close_code

    @staticmethod
    def replies(request: dict[str, Any]) -> list[dict[str, Any]]:
        rid = request.get("request_id")
        if request["type"] == "unsubscribe":
            sub = request["sub"]
            if sub == "7:trades" or sub.startswith("12:account."):
                return [{"type": "unsubscribed", "request_id": rid, "sub": sub}]
            return [
                {
                    "type": "error",
                    "request_id": rid,
                    "sub": request["sub"],
                    "code": "not_found",
                    "message": "no such subscription on this connection",
                }
            ]
        if request["topic"].startswith("account."):
            return ScriptedServer.account_replies(request)
        if request["instrument"] == UNKNOWN:
            return [
                {
                    "type": "error",
                    "request_id": rid,
                    "code": "not_found",
                    "message": "no connection",
                }
            ]
        topic = request["topic"]
        sub = f"7:{topic}"
        frames: list[dict[str, Any]] = [
            {"type": "subscribed", "request_id": rid, "sub": sub, "connection_id": 12}
        ]
        if topic == "trades":
            frames += [
                {
                    "type": "event",
                    "sub": sub,
                    "seq": 41,
                    "ts": 1,
                    "data": load_fixture("trades")["data"],
                },
                {
                    "type": "gap",
                    "sub": sub,
                    "from_seq": 42,
                    "to_seq": 57,
                    "reason": "slow_consumer",
                },
                {"type": "error", "sub": sub, "code": "unavailable", "message": "venue refused"},
                {"type": "something_new", "sub": sub},
            ]
        elif topic == "book.top":
            book = load_fixture("orderbook")
            data = {key: book[key] for key in ("ts", "depth", "bids", "asks")}
            data["depth"] = request.get("params", {}).get("depth", data["depth"])
            frames.append({"type": "event", "sub": sub, "seq": 9, "ts": 2, "data": data})
        return frames

    @staticmethod
    def account_replies(request: dict[str, Any]) -> list[dict[str, Any]]:
        """Account topics: ``connection_id`` required, ``instrument`` must be absent."""
        rid = request.get("request_id")
        if "instrument" in request or request.get("connection_id") != 12:
            return [
                {
                    "type": "error",
                    "request_id": rid,
                    "code": "invalid_request",
                    "message": "account topics take connection_id, not instrument",
                }
            ]
        topic = request["topic"]
        sub = f"12:{topic}"
        frames: list[dict[str, Any]] = [
            {"type": "subscribed", "request_id": rid, "sub": sub, "connection_id": 12}
        ]
        if topic == "account.orders":
            body = load_fixture("account_orders")
            data = {
                "instrument": INSTRUMENT,
                "orders": body["data"],
                "triggers": body["triggers"],
            }
            frames.append({"type": "event", "sub": sub, "seq": 3, "ts": 1, "data": data})
        elif topic == "account.fills":
            fill = load_fixture("account_fills")["data"][0]
            frames.append({"type": "event", "sub": sub, "seq": 7, "ts": 1, "data": fill})
        return frames


def run(test: Callable[[ScriptedServer, int], Awaitable[None]]) -> None:
    """Start a scripted server on a random loopback port and run ``test`` against it."""

    async def main() -> None:
        scripted = ScriptedServer()
        async with serve(
            scripted.handle, "127.0.0.1", 0, process_request=scripted.process_request
        ) as server:
            port = server.sockets[0].getsockname()[1]
            await asyncio.wait_for(test(scripted, port), timeout=15)

    asyncio.run(main())


def stream_for(port: int, token: str = TOKEN) -> Stream:
    return Terminal(token, port=port, timeout=5).stream()


# --- handshake ----------------------------------------------------------------


def test_handshake_sends_bearer_and_no_origin() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            assert stream.connected
        headers = server.handshakes[0]
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        assert "Origin" not in headers
        assert headers["Host"] == f"127.0.0.1:{port}"

    run(test)


def test_handshake_rejected_is_api_error() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        bad = "spt_" + "00" * 32
        with pytest.raises(ApiError) as excinfo:
            async with stream_for(port, token=bad):
                pass
        assert (excinfo.value.code, excinfo.value.status) == ("unauthorized", 401)
        assert bad not in str(excinfo.value) and TOKEN not in str(excinfo.value)

    run(test)


def test_unreachable_port() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    async def test() -> None:
        with pytest.raises(TerminalUnreachable) as excinfo:
            async with stream_for(port):
                pass
        assert TOKEN not in str(excinfo.value)

    asyncio.run(test())


def test_stream_url_and_not_connected() -> None:
    stream = Terminal(TOKEN, port=1).stream()
    assert stream.url == "ws://127.0.0.1:1/v1/stream"
    assert not stream.connected and stream.close_code is None
    assert TOKEN not in repr(stream)

    async def test() -> None:
        with pytest.raises(Exception, match="not connected"):
            await stream.subscribe("trades", INSTRUMENT)

    asyncio.run(test())


# --- subscribe / iterate ------------------------------------------------------


def test_subscribe_success_and_frames_in_order() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            subscribed = await stream.subscribe("trades", INSTRUMENT)
            assert isinstance(subscribed, Subscribed)
            assert subscribed.sub == "7:trades" and subscribed.connection_id == 12
            assert subscribed.topic == "trades"
            frames = [await stream.__anext__() for _ in range(3)]
        event, gap, error = frames
        assert isinstance(event, Event) and event.seq == 41 and event.topic == "trades"
        assert isinstance(event.data[0], Trade)
        assert event.data[0].price == Decimal("67000.1")
        assert isinstance(gap, Gap) and (gap.from_seq, gap.to_seq) == (42, 57)
        assert isinstance(error, SubscriptionError) and error.code == "unavailable"
        assert stream.close_code == 1000

    run(test)


def test_subscribe_with_params_and_connection_id() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            subscribed = await stream.subscribe(
                "book.top", INSTRUMENT, connection_id=12, depth=3, interval_ms=200
            )
            assert subscribed.sub == "7:book.top"
            event = await stream.__anext__()
        assert isinstance(event, Event) and isinstance(event.data, BookTop)
        assert event.data.depth == 3, "params reached the server"
        assert event.data.bids[0].size == Decimal("1.25")

    run(test)


def test_subscribe_error() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            with pytest.raises(StreamRequestError) as excinfo:
                await stream.subscribe("trades", UNKNOWN)
            assert excinfo.value.code == "not_found"
            assert str(excinfo.value) == "not_found: no connection"
            # the connection is still usable
            assert (await stream.subscribe("book.top", INSTRUMENT)).sub == "7:book.top"

    run(test)


def test_unsubscribe() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            subscribed = await stream.subscribe("trades", INSTRUMENT)
            done = await stream.unsubscribe(subscribed)
            assert isinstance(done, Unsubscribed) and done.sub == "7:trades"
            with pytest.raises(StreamRequestError) as excinfo:
                await stream.unsubscribe("9:ticker")
            assert excinfo.value.code == "not_found"
            # the error reply carried ``sub`` and ``request_id``: it answered the request
            # and must not leak into the iterator, whose next frames are the trades ones.
            await stream.subscribe("book.top", INSTRUMENT)
            kinds = [type(await stream.__anext__()) for _ in range(4)]
        assert kinds == [Event, Gap, SubscriptionError, Event]

    run(test)


def test_subscribe_account_fills_sends_connection_id_and_no_instrument() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            subscribed = await stream.subscribe("account.fills", connection_id=12)
            assert subscribed.sub == "12:account.fills" and subscribed.connection_id == 12
            assert subscribed.topic == "account.fills"
            event = await stream.__anext__()
        request = server.requests[0]
        assert request["type"] == "subscribe" and request["topic"] == "account.fills"
        assert request["connection_id"] == 12
        assert "instrument" not in request
        assert isinstance(event, Event) and event.topic == "account.fills"
        assert isinstance(event.data, Fill)
        assert event.data.price == Decimal("67000.1") and event.data.side == "buy"

    run(test)


def test_account_orders_event_is_typed() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            subscribed = await stream.subscribe("account.orders", connection_id=12)
            assert subscribed.sub == "12:account.orders"
            event = await stream.__anext__()
            done = await stream.unsubscribe(subscribed)
        assert done.sub == "12:account.orders"
        assert isinstance(event, Event) and event.sub == "12:account.orders"
        assert isinstance(event.data, OrdersUpdate)
        assert event.data.instrument == INSTRUMENT
        assert isinstance(event.data.orders[0], Order)
        assert event.data.orders[0].key == "t-123456789012345678"
        assert event.data.orders[0].order_type == "limit"
        assert event.data.triggers[0].trigger_type == "stop_loss"

    run(test)


def test_account_topic_with_an_instrument_drops_it() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            # a positional instrument on an account topic is not sent: the server would refuse it
            subscribed = await stream.subscribe("account.balances", INSTRUMENT, connection_id=12)
            assert subscribed.sub == "12:account.balances"
        assert "instrument" not in server.requests[0]

    run(test)


def test_subscribe_argument_errors_do_not_touch_the_socket() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            with pytest.raises(ValueError, match="connection_id"):
                await stream.subscribe("account.fills")
            with pytest.raises(ValueError, match="instrument"):
                await stream.subscribe("trades")
        assert server.requests == []

    run(test)


def test_server_close_4008_raises_stream_closed() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        async with stream_for(port) as stream:
            await stream.subscribe("trades", CLOSE_4008)
            with pytest.raises(StreamClosed) as excinfo:
                async for _ in stream:
                    pass
            assert (excinfo.value.code, excinfo.value.reason) == (4008, "slow consumer")
            assert (stream.close_code, stream.close_reason) == (4008, "slow consumer")
            assert not stream.connected
            # a request after the close fails the same way
            with pytest.raises(StreamClosed):
                await stream.subscribe("trades", INSTRUMENT)

    run(test)


def test_client_close_ends_iteration_quietly() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        stream = stream_for(port)
        await stream.connect()
        await stream.subscribe("book.top", INSTRUMENT)

        async def close_soon() -> None:
            await asyncio.sleep(0.2)
            await stream.close()

        closer = asyncio.ensure_future(close_soon())
        seen = [frame async for frame in stream]
        await closer
        assert len(seen) == 1 and isinstance(seen[0], Event)
        assert stream.close_code == 1000
        assert server.closed_with == 1000
        # iterating again stays quiet
        assert [frame async for frame in stream] == []

    run(test)


def test_close_while_a_request_is_pending() -> None:
    async def test(server: ScriptedServer, port: int) -> None:
        stream = stream_for(port)
        await stream.connect()
        await stream.subscribe("trades", CLOSE_4008)
        # the server closes right after the reply: wait for the end and check bookkeeping
        with pytest.raises(StreamClosed):
            async for _ in stream:
                pass
        await stream.close()  # a second close is harmless

    run(test)


# --- FrameRouter, no socket ---------------------------------------------------


def test_router_pairs_replies_with_requests() -> None:
    router = FrameRouter()
    first, second = router.open_request(), router.open_request()
    assert first != second and router.pending == {first, second}
    routed = router.route({"type": "subscribed", "request_id": second, "sub": "7:trades"})
    assert isinstance(routed, Reply) and routed.request_id == second
    assert router.pending == {first}
    # an unsubscribe refusal carries both request_id and sub: still a reply
    routed = router.route({"type": "error", "request_id": first, "sub": "7:x", "code": "not_found"})
    assert isinstance(routed, Reply)
    assert router.pending == frozenset()


def test_router_types_data_frames() -> None:
    router = FrameRouter()
    event = router.route({"type": "event", "sub": "7:trades", "seq": 1, "ts": 1, "data": []})
    assert isinstance(event, Event) and event.data == []
    gap = router.route({"type": "gap", "sub": "7:trades", "from_seq": 1, "to_seq": 2})
    assert isinstance(gap, Gap) and gap.reason == ""
    error = router.route(
        {"type": "error", "sub": "7:trades", "code": "unavailable", "message": "x"}
    )
    assert isinstance(error, SubscriptionError)


def test_router_ignores_strays() -> None:
    router = FrameRouter()
    assert router.route({"type": "pong"}) is None
    assert router.route({"type": "subscribed", "request_id": "never", "sub": "1:t"}) is None
    assert router.route({"type": "error", "code": "invalid_request", "message": "bad"}) is None
    request_id = router.open_request()
    router.close_request(request_id)
    assert router.route({"type": "subscribed", "request_id": request_id, "sub": "1:t"}) is None
