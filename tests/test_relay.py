import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
import websockets
from websockets.asyncio.client import ClientConnection

from eclip.protocol import VERSION
from eclip.relay import Relay, listen


@pytest_asyncio.fixture
async def relay_url() -> AsyncIterator[tuple[Relay, str]]:
    relay = Relay()
    async with listen(relay, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield relay, f"ws://127.0.0.1:{port}"


async def ask(ws: ClientConnection, **message: Any) -> dict[str, Any]:
    await ws.send(json.dumps(message))
    reply: dict[str, Any] = json.loads(await ws.recv())
    return reply


async def claim(ws: ClientConnection) -> str:
    nameplate: str = (await ask(ws, action="claim", version=VERSION))["nameplate"]
    return nameplate


@pytest.mark.asyncio
async def test_payload_delivered_once_and_room_deleted(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender, websockets.connect(url) as receiver:
        nameplate = await claim(sender)
        assert (await ask(receiver, action="join", nameplate=nameplate, version=VERSION))[
            "type"
        ] == "joined"
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
        assert (await ask(second, action="join", nameplate=nameplate, version=VERSION))[
            "error"
        ] == "room-not-found"


@pytest.mark.asyncio
async def test_non_final_message_goes_both_ways_and_keeps_room(
    relay_url: tuple[Relay, str],
) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender, websockets.connect(url) as receiver:
        nameplate = await claim(sender)
        await ask(receiver, action="join", nameplate=nameplate, version=VERSION)
        await sender.recv()  # receiver-ready

        await receiver.send(
            json.dumps({"action": "message", "payload": "b", "payloadType": "pake"})
        )
        assert json.loads(await sender.recv())["payload"] == "b"
        await sender.send(json.dumps({"action": "message", "payload": "a", "payloadType": "pake"}))
        assert json.loads(await receiver.recv())["payload"] == "a"
        assert nameplate in relay.rooms

        # Only the sender delivers the secret, so a receiver "payload" keeps the room.
        await receiver.send(
            json.dumps({"action": "message", "payload": "x", "payloadType": "payload"})
        )
        assert json.loads(await sender.recv())["payload"] == "x"
        assert nameplate in relay.rooms


@pytest.mark.asyncio
async def test_claim_finds_last_free_nameplate_then_reports_full(
    relay_url: tuple[Relay, str],
) -> None:
    relay, url = relay_url
    relay.max_rooms = 2
    async with (
        websockets.connect(url) as first,
        websockets.connect(url) as last,
        websockets.connect(url) as extra,
    ):
        assert {await claim(first), await claim(last)} == {"1", "2"}
        assert (await ask(extra, action="claim", version=VERSION))["error"] == "relay-full"
        assert (await ask(extra, action="claim", version=VERSION))["error"] == "relay-full"


@pytest.mark.asyncio
async def test_connections_and_rooms_expire_after_ttl(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    relay.ttl = 1  # long enough to pair on a slow CI runner
    async with (
        websockets.connect(url) as sender,
        websockets.connect(url) as receiver,
        websockets.connect(url) as idle,
    ):
        nameplate = await claim(sender)
        await ask(receiver, action="join", nameplate=nameplate, version=VERSION)
        assert json.loads(await sender.recv())["type"] == "receiver-ready"

        for ws in (sender, receiver, idle):
            reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            assert reply["error"] == "expired"
            await asyncio.wait_for(ws.wait_closed(), timeout=10)
        assert relay.rooms == {}
        assert relay.connections == {}


@pytest.mark.asyncio
async def test_connections_per_ip_are_capped(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    relay.max_ip_connections = 2
    async with websockets.connect(url) as one:
        async with websockets.connect(url) as two, websockets.connect(url) as three:
            assert json.loads(await three.recv())["error"] == "too-many-connections"
            await three.wait_closed()
            assert "nameplate" in await ask(two, action="claim", version=VERSION)
        for _ in range(50):
            if sum(relay.ip_connections.values()) == 1:
                break
            await asyncio.sleep(0.01)
        async with websockets.connect(url) as again:
            assert "nameplate" in await ask(again, action="claim", version=VERSION)
        assert "nameplate" in await ask(one, action="claim", version=VERSION)


@pytest.mark.asyncio
async def test_large_frame_closes_connection_and_relay_keeps_serving() -> None:
    relay = Relay(max_message=100)
    async with listen(relay, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with websockets.connect(url) as big:
            await big.send(json.dumps({"action": "claim", "pad": "x" * 100}))
            with pytest.raises(websockets.ConnectionClosed) as closed:
                await big.recv()
            assert closed.value.rcvd is not None and closed.value.rcvd.code == 1009
        async with websockets.connect(url) as small:
            assert "nameplate" in await ask(small, action="claim", version=VERSION)


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, 0, 2, True, 1.0, "1"])
async def test_claim_and_join_need_the_relay_version(
    relay_url: tuple[Relay, str], version: object
) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as ws:
        for action in ("claim", "join"):
            message: dict[str, Any] = {"action": action, "nameplate": "1"}
            if version is not None:
                message["version"] = version
            reply = await ask(ws, **message)
            assert reply == {"type": "error", "error": "unsupported-version", "version": VERSION}
        assert relay.rooms == {}


@pytest.mark.asyncio
async def test_third_client_is_room_full(relay_url: tuple[Relay, str]) -> None:
    _, url = relay_url
    async with websockets.connect(url) as sender, websockets.connect(url) as receiver:
        nameplate = await claim(sender)
        await ask(receiver, action="join", nameplate=nameplate, version=VERSION)

        async with websockets.connect(url) as third:
            assert (await ask(third, action="join", nameplate=nameplate, version=VERSION))[
                "error"
            ] == "room-full"


@pytest.mark.asyncio
async def test_outside_connection_cannot_forward_or_delete(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender, websockets.connect(url) as outsider:
        nameplate = await claim(sender)
        reply = await ask(
            outsider, action="message", nameplate=nameplate, payload="x", payloadType="payload"
        )
        assert reply["error"] == "not-in-room"
        assert nameplate in relay.rooms


@pytest.mark.asyncio
async def test_connection_holds_one_room_only(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender:
        nameplate = await claim(sender)
        assert (await ask(sender, action="claim", version=VERSION))["error"] == "already-in-room"
        assert (await ask(sender, action="join", nameplate=nameplate, version=VERSION))[
            "error"
        ] == "already-in-room"
        assert list(relay.rooms) == [nameplate]


@pytest.mark.asyncio
async def test_payload_without_receiver_keeps_room(relay_url: tuple[Relay, str]) -> None:
    relay, url = relay_url
    async with websockets.connect(url) as sender:
        nameplate = await claim(sender)
        reply = await ask(sender, action="message", payload="x", payloadType="payload")
        assert reply["error"] == "no-receiver-yet"
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
        "[" * 60_000,  # under the 64 KiB frame limit, over the recursion limit
    ],
)
async def test_bad_input_gets_error_and_connection_stays_open(
    relay_url: tuple[Relay, str], raw: str | bytes
) -> None:
    _, url = relay_url
    async with websockets.connect(url) as ws:
        await ws.send(raw)
        assert json.loads(await ws.recv())["type"] == "error"
        assert "nameplate" in await ask(ws, action="claim", version=VERSION)
