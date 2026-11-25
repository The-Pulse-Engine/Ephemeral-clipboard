import asyncio
import contextlib
import json
import secrets
import time
from collections import Counter
from dataclasses import dataclass, field

import websockets
from websockets.asyncio.server import ServerConnection


@dataclass
class Room:
    sender: ServerConnection
    receiver: ServerConnection | None = None
    created: float = field(default_factory=time.monotonic)


async def _error(websocket: ServerConnection, error: str) -> None:
    await websocket.send(json.dumps({"type": "error", "error": error}))


class Relay:
    def __init__(
        self,
        ttl: float = 300,
        max_rooms: int = 1000,
        max_ip_connections: int = 20,
        max_message: int = 64 * 1024,
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
        free = [str(n) for n in range(1, self.max_rooms + 1) if str(n) not in self.rooms]
        return secrets.choice(free) if free else None

    async def _close_room(self, nameplate: str, error: str | None = None) -> None:
        room = self.rooms.pop(nameplate, None)
        if room is None:
            return

        members = [room.sender] if room.receiver is None else [room.sender, room.receiver]
        for member in members:
            self.connections.pop(member, None)
        for member in members:
            if error is not None:
                with contextlib.suppress(websockets.ConnectionClosed):
                    await _error(member, error)
            await member.close(code=1000, reason="room deleted")

    async def close(self, websocket: ServerConnection) -> None:
        nameplate = self.connections.pop(websocket, None)
        if nameplate is not None:
            await self._close_room(nameplate)

    async def reap_expired(self) -> None:
        now = time.monotonic()
        expired = [n for n, room in self.rooms.items() if now - room.created >= self.ttl]
        # Close in parallel so one peer that ignores the close frame cannot stall the rest.
        await asyncio.gather(*(self._close_room(n, "expired") for n in expired))

    async def handler(self, websocket: ServerConnection) -> None:
        # shortcut: counts the socket address, so behind a reverse proxy every client
        # shares one IP; read X-Forwarded-For from a trusted proxy when #19 lands.
        ip = str(websocket.remote_address[0])
        if self.ip_connections[ip] >= self.max_ip_connections:
            with contextlib.suppress(websockets.ConnectionClosed):
                await _error(websocket, "too many connections")
            return

        self.ip_connections[ip] += 1
        try:
            async for raw in websocket:
                await self._dispatch(websocket, raw)
        except websockets.ConnectionClosed:
            pass  # a client that drops mid-exchange is normal, not a relay error
        finally:
            self.ip_connections[ip] -= 1
            if not self.ip_connections[ip]:
                del self.ip_connections[ip]
            await self.close(websocket)

    async def _dispatch(self, websocket: ServerConnection, raw: str | bytes) -> None:
        # Length in characters for text frames; clients send ASCII JSON, so this is bytes.
        if len(raw) > self.max_message:
            await _error(websocket, "message too large")
            return
        try:
            message = json.loads(raw)
        # ValueError covers bad UTF-8 and huge ints, RecursionError deep nesting
        except (ValueError, RecursionError):
            await _error(websocket, "invalid json")
            return
        if not isinstance(message, dict):
            await _error(websocket, "invalid message")
            return

        action = message.get("action")
        nameplate = message.get("nameplate")
        if not isinstance(action, str) or not isinstance(nameplate, str | None):
            await _error(websocket, "invalid message")
            return

        if action in ("claim", "join") and websocket in self.connections:
            await _error(websocket, "already in room")
            return

        if action == "claim":
            nameplate = self._claim_nameplate()
            if nameplate is None:
                await _error(websocket, "relay full")
                return
            self.rooms[nameplate] = Room(sender=websocket)
            self.connections[websocket] = nameplate
            await websocket.send(json.dumps({"type": "claimed", "nameplate": nameplate}))
            return

        if action == "join":
            joined_room = self.rooms.get(nameplate) if nameplate else None
            if nameplate is None or joined_room is None:
                await _error(websocket, "room not found")
                return
            if joined_room.receiver is not None:
                await _error(websocket, "room full")
                return

            joined_room.receiver = websocket
            self.connections[websocket] = nameplate
            await websocket.send(json.dumps({"type": "joined"}))
            await joined_room.sender.send(json.dumps({"type": "receiver-ready"}))
            return

        if action == "message":
            member_nameplate = self.connections.get(websocket)
            if member_nameplate is None or nameplate not in (None, member_nameplate):
                await _error(websocket, "not in room")
                return

            room = self.rooms[member_nameplate]
            target = room.receiver if websocket is room.sender else room.sender
            if target is None:
                await _error(websocket, "no receiver yet")
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

        await _error(websocket, "unknown action")


async def serve(host: str = "0.0.0.0", port: int = 8765, relay: Relay | None = None) -> None:
    relay = relay or Relay()
    async with websockets.serve(relay.handler, host, port):
        while True:
            await asyncio.sleep(1)
            await relay.reap_expired()
