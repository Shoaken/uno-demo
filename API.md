# UNO Demo API and Events

This document summarizes the server HTTP endpoints, Socket.IO events, and the optional Redis persistence switch.

## HTTP API

All endpoints return JSON.

### `GET /healthz`

Returns:

```json
{"status": "ok"}
```

### `POST /api/rooms/create`

Body:

```json
{"room_id": "room-1", "host_name": "alice"}
```

Returns room events plus `meta`:

```json
{
  "events": [
    {"event": "game::room", "data": {"...": "..."}}
  ],
  "meta": {
    "player_id": "player-alice",
    "reconnect_token": "..."
  }
}
```

### `POST /api/rooms/join`

Body:

```json
{"room_id": "room-1", "player_name": "bob"}
```

Returns room events plus `meta` with the new player's `player_id` and `reconnect_token`.

### `POST /api/rooms/ready`

Body:

```json
{"room_id": "room-1", "player_id": "player-bob", "ready": true}
```

### `POST /api/rooms/start`

Body:

```json
{"room_id": "room-1", "started_by_player_id": "player-alice", "hand_size": 7, "seed": 42}
```

### `POST /api/rooms/draw`

Body:

```json
{"room_id": "room-1", "player_id": "player-bob"}
```

### `POST /api/rooms/play`

Body:

```json
{"room_id": "room-1", "player_id": "player-bob", "card_id": "card-1", "chosen_color": "blue"}
```

### `POST /api/rooms/uno`

Body:

```json
{"room_id": "room-1", "player_id": "player-bob"}
```

### `GET /api/rooms`

Lists rooms and their current players.

### `GET /api/rooms/<room_id>`

Returns a full room snapshot with players, host, ready state, and connection state.

### `POST /api/rooms/leave`

Body:

```json
{"room_id": "room-1", "player_id": "player-bob"}
```

### `POST /api/rooms/transfer-host`

Body:

```json
{"room": "room-1", "current_host_id": "player-alice", "new_host_id": "player-bob"}
```

### `POST /api/rooms/kick`

Body:

```json
{"room": "room-1", "host_id": "player-alice", "player_id": "player-bob"}
```

## Socket.IO events

### Client to server

- `player::join`
- `player::ready`
- `game::start`
- `game::draw`
- `game::play`
- `game::uno`

### Server to client

- `session::info`
- `game::room`
- `game::state`
- `game::start`
- `game::draw`
- `game::play`
- `game::uno`
- `game::over`
- `game::notify`
- `player::leave`

## Redis persistence

Optional persistence is disabled by default.

Enable it with:

- `UNO_USE_REDIS=1`
- `UNO_REDIS_URL=redis://localhost:6379/0`
- optional `UNO_REDIS_PREFIX=uno_demo`

When enabled, room snapshots are mirrored to Redis and reloaded on startup.

## Notes

- `player_id` is always `player-<name>` in this demo.
- `reconnect_token` is issued per player and stored with the room snapshot.
- The room APIs are intentionally small so frontend code can stay simple.
