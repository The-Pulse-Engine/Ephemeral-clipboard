# Ephemeral Clipboard protocol

Protocol version 1.

This document describes the messages between an `eclip` client and the relay. The relay code is in `src/eclip/relay.py`. The version, the frame limit and the error codes are in `src/eclip/protocol.py`. The relay and the client import them from there.

## Terms

- **Relay:** the server that pairs two clients and forwards their messages. It never reads the content of a forwarded message.
- **Sender:** the client that claims a room and sends the secret.
- **Receiver:** the client that joins the room and receives the secret.
- **Nameplate:** the room number. It is a decimal string from `"1"` to the room cap of the relay, for example `"7"`. It is the first part of a code such as `7-guitar-orbit`. It is not secret.
- **Room:** one sender and at most one receiver, paired on one nameplate.

## Transport

The protocol runs over WebSocket. The default port is 8765. A public relay must use `wss://` (WebSocket over TLS).

Each message is one WebSocket text frame that holds one JSON object. A frame can hold at most 64 KiB (65,536 bytes), and this limit includes the JSON envelope. If a frame is larger, the relay closes the connection with close code 1009.

The secret travels base64-encoded inside the envelope. Base64 makes data one third larger, so one frame carries about 48 KiB of ciphertext.

## Versions

The current version is 1. Each `claim` and each `join` must contain `"version": 1` as a JSON integer. If the version is missing or different, the relay replies with the error `unsupported-version`.

Each error message from the relay contains the version that the relay speaks. A client can use it to tell the user to update.

If you change the wire format, increase the version in `src/eclip/protocol.py` and in this document.

## Client messages

Each client message has an `action` field.

`claim` asks for a new room. The relay replies with `claimed`.

```json
{"action": "claim", "version": 1}
```

`join` enters the room of a nameplate. The relay replies with `joined` to the receiver and sends `receiver-ready` to the sender.

```json
{"action": "join", "nameplate": "7", "version": 1}
```

`message` sends data to the other member of the room. The relay forwards `payload` and `payloadType` without changes. The `payload` can be any JSON value. The `nameplate` field is optional. If it is present, it must be the nameplate of your own room.

```json
{"action": "message", "payload": "<base64>", "payloadType": "pake"}
```

## Relay messages

Each relay message has a `type` field.

- `claimed`: `{"type": "claimed", "nameplate": "7"}`. The relay sends it to the sender after a `claim`.
- `joined`: `{"type": "joined"}`. The relay sends it to the receiver after a `join`.
- `receiver-ready`: `{"type": "receiver-ready"}`. The relay sends it to the sender when a receiver joins.
- `message`: `{"type": "message", "payload": ..., "payloadType": "..."}`. This is a message from the other member of the room.
- `error`: `{"type": "error", "error": "room-full", "version": 1}`. The `error` field holds one of the codes below.

## Error codes

After most errors, the connection stays open and the client can try again. After `too-many-connections` and `expired`, the relay closes the connection.

- `invalid-json`: the frame is not valid JSON. Bad UTF-8, nesting that is too deep, and numbers that are too long also give this error.
- `invalid-message`: the JSON is not an object, `action` is not a string, or `nameplate` is present and is not a string.
- `unsupported-version`: a `claim` or `join` has a missing or different version.
- `unknown-action`: the `action` is not `claim`, `join` or `message`.
- `already-in-room`: a connection that is already in a room sent `claim` or `join`.
- `relay-full`: all nameplates are in use.
- `room-not-found`: no room has this nameplate, or the `join` has no nameplate.
- `room-full`: the room already has a receiver.
- `not-in-room`: a connection that is not in a room sent `message`, or the `nameplate` is not its own room.
- `no-receiver-yet`: the sender sent `message` before a receiver joined.
- `too-many-connections`: the IP address has too many open connections.
- `expired`: the connection reached the end of its lifetime.

## Room lifecycle

A connection goes through these states:

1. **New:** the connection is open and has no room. It can send `claim` or `join`.
2. **Waiting:** the sender has a room without a receiver. A `message` from the sender gets `no-receiver-yet`.
3. **Paired:** the room has a sender and a receiver. The relay forwards each `message` to the other member.
4. **Closed:** the relay deleted the room and closed both connections.

The relay deletes a room in three cases:

- The sender sends a `message` with `payloadType` set to `"payload"`. The relay forwards it first. A receiver message with this `payloadType` is forwarded, and the room stays.
- A member disconnects.
- The connection of a member reaches the end of its lifetime. Both members get the error `expired`.

When the relay deletes a room, it closes both connections with close code 1000.

## Limits

Each limit is a setting of `eclip serve`.

- **Lifetime** (`--ttl`, default 300 seconds): each connection lives at most this long, counted from when it connects. A room ends at the latest when the connection of its sender ends. The relay then sends `expired` and closes the connection. This also closes connections that never claim or join a room.
- **Rooms** (`--max-rooms`, default 1000): nameplates go from 1 to this number. When all are in use, a `claim` gets `relay-full`.
- **Connections per IP address** (`--max-ip-connections`, default 20): a new connection over the limit gets `too-many-connections` and is closed. The relay counts the address of the socket. Behind a reverse proxy, all clients have the address of the proxy.
- **Frame size** (`--max-message`, default 65,536 bytes): a larger frame closes the connection with close code 1009.

## Close codes

- 1000: the relay deleted the room, the lifetime ended, or the relay refused the connection.
- 1009: the frame is larger than the frame limit.
- 1011: an internal error in the relay. This is a bug. Report it.

## End-to-end messages

The two clients send these messages to each other inside `message`. The relay does not read them. The order is:

1. The sender sends `payloadType` `"pake"` with SPAKE2 message A.
2. The receiver sends `"pake"` with SPAKE2 message B.
3. The sender sends `"confirm"` with its key confirmation.
4. The receiver sends `"confirm"` with its key confirmation.
5. The sender sends `"payload"` with the encrypted secret. The relay forwards it and deletes the room.

If a key confirmation fails, the client stops and sends no payload.

The encoding of each field, the key derivation, the confirmation values and the nonce are not defined yet. Issue #9 (SPAKE2, HKDF and key confirmation) and issue #10 (ChaCha20-Poly1305) must add them to this section.
