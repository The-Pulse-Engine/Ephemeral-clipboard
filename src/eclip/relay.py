import asyncio
import json
import secrets
from dataclasses import dataclass

import websockets
from websockets.asyncio.server import ServerConnection


@dataclass
class Room:
    sender: ServerConnection
    receiver: ServerConnection | None = None


async def _error(websocket: ServerConnection, error: str) -> None:
    await websocket.send(json.dumps({"type": "error", "error": error}))


class Relay:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.connections: dict[ServerConnection, str] = {}

    def _claim_nameplate(self) -> str | None:
        free = [f"{n:03d}" for n in range(1000) if f"{n:03d}" not in self.rooms]
        return secrets.choice(free) if free else None

    async def _close_room(self, nameplate: str) -> None:
        room = self.rooms.pop(nameplate, None)
        if room is None:
            return

        self.connections.pop(room.sender, None)
        if room.receiver is not None:
            self.connections.pop(room.receiver, None)
        await room.sender.close(code=1000, reason="room deleted")
        if room.receiver is not None:
            await room.receiver.close(code=1000, reason="room deleted")

    async def close(self, websocket: ServerConnection) -> None:
        nameplate = self.connections.pop(websocket, None)
        if nameplate is not None:
            await self._close_room(nameplate)

    async def handler(self, websocket: ServerConnection) -> None:
        try:
            async for raw in websocket:
                try:
                    message = json.loads(raw)
                # ValueError covers bad UTF-8 and huge ints, RecursionError deep nesting
                except (ValueError, RecursionError):
                    await _error(websocket, "invalid json")
                    continue
                if not isinstance(message, dict):
                    await _error(websocket, "invalid message")
                    continue

                action = message.get("action")
                nameplate = message.get("nameplate")
                if not isinstance(action, str) or not isinstance(nameplate, str | None):
                    await _error(websocket, "invalid message")
                    continue

                if action in ("claim", "join") and websocket in self.connections:
                    await _error(websocket, "already in room")
                    continue

                if action == "claim":
                    nameplate = self._claim_nameplate()
                    if nameplate is None:
                        await _error(websocket, "relay full")
                        continue
                    self.rooms[nameplate] = Room(sender=websocket)
                    self.connections[websocket] = nameplate
                    await websocket.send(json.dumps({"type": "claimed", "nameplate": nameplate}))
                    continue

                if action == "join":
                    joined_room = self.rooms.get(nameplate) if nameplate else None
                    if nameplate is None or joined_room is None:
                        await _error(websocket, "room not found")
                        continue
                    if joined_room.receiver is not None:
                        await _error(websocket, "room full")
                        continue

                    joined_room.receiver = websocket
                    self.connections[websocket] = nameplate
                    await websocket.send(json.dumps({"type": "joined"}))
                    await joined_room.sender.send(json.dumps({"type": "receiver-ready"}))
                    continue

                if action == "message":
                    member_nameplate = self.connections.get(websocket)
                    if member_nameplate is None or nameplate not in (None, member_nameplate):
                        await _error(websocket, "not in room")
                        continue

                    room = self.rooms[member_nameplate]
                    target = room.receiver if websocket is room.sender else room.sender
                    if target is None:
                        await _error(websocket, "no receiver yet")
                        continue

                    await target.send(
                        json.dumps(
                            {
                                "type": "message",
                                "payload": message.get("payload"),
                                "payloadType": message.get("payloadType"),
                            }
                        )
                    )
                    if message.get("payloadType") == "payload":
                        await self._close_room(member_nameplate)
                    continue

                await _error(websocket, "unknown action")
        except websockets.ConnectionClosed:
            pass  # a client that drops mid-exchange is normal, not a relay error
        finally:
            await self.close(websocket)


async def serve(host: str = "0.0.0.0", port: int = 8765) -> None:
    async with websockets.serve(Relay().handler, host, port):
        await asyncio.Future()
