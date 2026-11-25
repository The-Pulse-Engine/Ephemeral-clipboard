import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
import pytest_asyncio
import websockets
from websockets.asyncio.client import ClientConnection

from eclip.relay import Relay, Room


@pytest_asyncio.fixture
async def relay_url() -> AsyncIterator[tuple[Relay, str]]:
    relay = Relay()
    async with websockets.serve(relay.handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield relay, f"ws://127.0.0.1:{port}"


async def ask(ws: ClientConnection, **message: Any) -> dict[str, Any]:
    await ws.send(json.dumps(message))
    reply: dict[str, Any] = json.loads(await ws.recv())
    return reply


async def claim(ws: ClientConnection) -> str:
    nameplate: str = (await ask(ws, action="claim"))["nameplate"]
    return nameplate


@pytest.mark.asyncio
async def test_payload_delivered_once_and_room_deleted(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender, websockets.connect(url) as receiver:
        nameplate = await claim(sender)
        assert (await ask(receiver, action="join", nameplate=nameplate))["type"] == "joined"
        assert json.loads(await sender.recv())["type"] == "receiver-ready"

        await sender.send(
            json.dumps({"action": "message", "payload": "encrypted-demo", "payloadType": "payload"})
        )
        delivered = json.loads(await receiver.recv())
        assert delivered["payload"] == "encrypted-demo"

        await receiver.wait_closed()
        assert relay.rooms == {}
        assert relay.connections == {}

    async with websockets.connect(url) as second:
        assert (await ask(second, action="join", nameplate=nameplate))["error"] == "room not found"


@pytest.mark.asyncio
async def test_non_final_message_goes_both_ways_and_keeps_room(
    relay_url: tuple[Relay, str],
) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender, websockets.connect(url) as receiver:
        nameplate = await claim(sender)
        await ask(receiver, action="join", nameplate=nameplate)
        await sender.recv()  # receiver-ready

        await receiver.send(
            json.dumps({"action": "message", "payload": "b", "payloadType": "pake"})
        )
        assert json.loads(await sender.recv())["payload"] == "b"
        await sender.send(json.dumps({"action": "message", "payload": "a", "payloadType": "pake"}))
        assert json.loads(await receiver.recv())["payload"] == "a"
        assert nameplate in relay.rooms


@pytest.mark.asyncio
async def test_claim_finds_last_free_nameplate_then_reports_full(
    relay_url: tuple[Relay, str],
) -> None:
    relay, url = relay_url
    placeholder = Room(sender=cast(Any, None))
    relay.rooms = {f"{n:03d}": placeholder for n in range(1, 1000)}
    async with websockets.connect(url) as last, websockets.connect(url) as extra:
        assert await claim(last) == "000"
        assert (await ask(extra, action="claim"))["error"] == "relay full"
        assert (await ask(extra, action="claim"))["error"] == "relay full"


@pytest.mark.asyncio
async def test_third_client_is_room_full(relay_url: tuple[Relay, str]) -> None:
    _, url = relay_url
    async with websockets.connect(url) as sender, websockets.connect(url) as receiver:
        nameplate = await claim(sender)
        await ask(receiver, action="join", nameplate=nameplate)

        async with websockets.connect(url) as third:
            assert (await ask(third, action="join", nameplate=nameplate))["error"] == "room full"


@pytest.mark.asyncio
async def test_outside_connection_cannot_forward_or_delete(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender, websockets.connect(url) as outsider:
        nameplate = await claim(sender)
        reply = await ask(
            outsider, action="message", nameplate=nameplate, payload="x", payloadType="payload"
        )
        assert reply["error"] == "not in room"
        assert nameplate in relay.rooms


@pytest.mark.asyncio
async def test_connection_holds_one_room_only(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender:
        nameplate = await claim(sender)
        assert (await ask(sender, action="claim"))["error"] == "already in room"
        assert (await ask(sender, action="join", nameplate=nameplate))["error"] == "already in room"
        assert list(relay.rooms) == [nameplate]


@pytest.mark.asyncio
async def test_payload_without_receiver_keeps_room(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender:
        nameplate = await claim(sender)
        reply = await ask(sender, action="message", payload="x", payloadType="payload")
        assert reply["error"] == "no receiver yet"
        assert nameplate in relay.rooms


@pytest.mark.asyncio
async def test_sender_disconnect_deletes_room(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender:
        await claim(sender)
    for _ in range(50):
        if not relay.rooms:
            break
        await asyncio.sleep(0.01)
    assert relay.rooms == {}
    assert relay.connections == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[1, 2]",
        '"text"',
        '{"action": 5}',
        '{"action": "join", "nameplate": [1]}',
        '{"action": "dance"}',
        b"\x80",
        "9" * 5000,
        "[" * 100_000,
    ],
)
async def test_bad_input_gets_error_and_connection_stays_open(
    relay_url: tuple[Relay, str], raw: str | bytes
) -> None:
    _, url = relay_url
    async with websockets.connect(url) as ws:
        await ws.send(raw)
        assert json.loads(await ws.recv())["type"] == "error"
        assert "nameplate" in await ask(ws, action="claim")
