import asyncio
import contextlib
import json
import secrets
from collections import Counter
from dataclasses import dataclass

import websockets
from websockets.asyncio.server import Server, ServerConnection

from . import protocol
from .protocol import Error


@dataclass
class Room:
    sender: ServerConnection
    receiver: ServerConnection | None = None


async def _error(websocket: ServerConnection, code: Error) -> None:
    await websocket.send(protocol.error(code))


async def _end(websocket: ServerConnection, code: Error | None) -> None:
    if code is not None:
        with contextlib.suppress(websockets.ConnectionClosed):
            await _error(websocket, code)
    await websocket.close(code=1000, reason=code or "room deleted")


class Relay:
    def __init__(
        self,
        ttl: float = 300,
        max_rooms: int = 1000,
        max_ip_connections: int = 20,
        max_message: int = protocol.MAX_MESSAGE,
    ) -> None:
        self.ttl = ttl
        self.max_rooms = max_rooms
        self.max_ip_connections = max_ip_connections
        self.max_message = max_message
        self.rooms: dict[str, Room] = {}
        self.connections: dict[ServerConnection, str] = {}
        self.ip_connections: Counter[str] = Counter()

    def _claim_nameplate(self) -> str | None:
        # Nameplates are 1..max_rooms, so a full nameplate space is the room cap.
        # shortcut: scans every nameplate per claim, fine to ~100k rooms; sample first above that.
        free = [str(n) for n in range(1, self.max_rooms + 1) if str(n) not in self.rooms]
        return secrets.choice(free) if free else None

    async def _close_room(self, nameplate: str, code: Error | None = None) -> None:
        room = self.rooms.pop(nameplate, None)
        if room is None:
            return

        members = [room.sender] if room.receiver is None else [room.sender, room.receiver]
        for member in members:
            self.connections.pop(member, None)
        # Shielded so a lifetime timeout cannot leave the other member open after the pop.
        await asyncio.shield(asyncio.gather(*(_end(member, code) for member in members)))

    async def close(self, websocket: ServerConnection, code: Error | None = None) -> None:
        nameplate = self.connections.pop(websocket, None)
        if nameplate is not None:
            await self._close_room(nameplate, code)
        elif code is not None:
            await _end(websocket, code)

    async def handler(self, websocket: ServerConnection) -> None:
        # shortcut: counts the socket address, so behind a reverse proxy every client
        # shares one IP; read X-Forwarded-For from a trusted proxy when #19 lands.
        ip = str(websocket.remote_address[0])
        if self.ip_connections[ip] >= self.max_ip_connections:
            with contextlib.suppress(websockets.ConnectionClosed):
                await _error(websocket, Error.TOO_MANY_CONNECTIONS)
            return

        self.ip_connections[ip] += 1
        try:
            # The TTL bounds every connection, so idle ones and their rooms both expire.
            async with asyncio.timeout(self.ttl):
                async for raw in websocket:
                    await self._dispatch(websocket, raw)
        except TimeoutError:
            await self.close(websocket, Error.EXPIRED)
        except websockets.ConnectionClosed:
            pass  # a client that drops mid-exchange is normal, not a relay error
        finally:
            self.ip_connections[ip] -= 1
            if not self.ip_connections[ip]:
                del self.ip_connections[ip]
            await self.close(websocket)

    async def _dispatch(self, websocket: ServerConnection, raw: str | bytes) -> None:
        message = protocol.parse(raw)
        if isinstance(message, Error):
            await _error(websocket, message)
            return

        action = message["action"]
        nameplate = message.get("nameplate")

        if action in ("claim", "join") and websocket in self.connections:
            await _error(websocket, Error.ALREADY_IN_ROOM)
            return

        if action == "claim":
            nameplate = self._claim_nameplate()
            if nameplate is None:
                await _error(websocket, Error.RELAY_FULL)
                return
            self.rooms[nameplate] = Room(sender=websocket)
            self.connections[websocket] = nameplate
            await websocket.send(json.dumps({"type": "claimed", "nameplate": nameplate}))
            return

        if action == "join":
            joined_room = self.rooms.get(nameplate) if nameplate else None
            if nameplate is None or joined_room is None:
                await _error(websocket, Error.ROOM_NOT_FOUND)
                return
            if joined_room.receiver is not None:
                await _error(websocket, Error.ROOM_FULL)
                return

            joined_room.receiver = websocket
            self.connections[websocket] = nameplate
            await websocket.send(json.dumps({"type": "joined"}))
            await joined_room.sender.send(json.dumps({"type": "receiver-ready"}))
            return

        if action == "message":
            member_nameplate = self.connections.get(websocket)
            if member_nameplate is None or nameplate not in (None, member_nameplate):
                await _error(websocket, Error.NOT_IN_ROOM)
                return

            room = self.rooms[member_nameplate]
            target = room.receiver if websocket is room.sender else room.sender
            if target is None:
                await _error(websocket, Error.NO_RECEIVER_YET)
                return

            await target.send(
                json.dumps(
                    {
                        "type": "message",
                        "payload": message.get("payload"),
                        "payloadType": message.get("payloadType"),
                    }
                )
            )
            # Only the sender delivers the secret, so only the sender's payload ends the room.
            if websocket is room.sender and message.get("payloadType") == "payload":
                await self._close_room(member_nameplate)
            return

        await _error(websocket, Error.UNKNOWN_ACTION)


def listen(relay: Relay, host: str, port: int) -> Server:
    # max_size makes websockets refuse big frames before it buffers them (close code 1009).
    return websockets.serve(relay.handler, host, port, max_size=relay.max_message)


async def serve(host: str = "0.0.0.0", port: int = 8765, relay: Relay | None = None) -> None:
    async with listen(relay or Relay(), host, port):
        await asyncio.Future()
