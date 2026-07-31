from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit, join_room as socket_join_room

from core.uno import GameOverReason
from lib import events
from lib.state import RoomManager

app = Flask(__name__)
app.json.sort_keys = False
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
room_manager = RoomManager()


def _json_data() -> Dict[str, Any]:
    return request.get_json(silent=True) or {}


def _emit_payloads(room_id: str, payloads: List[dict]) -> None:
    for payload in payloads:
        emit(payload["event"], payload.get("data", {}), to=room_id)


def _json_response(payloads: List[dict], status_code: int = 200):
    return jsonify({"events": payloads}), status_code


def _error_code(message: str) -> str:
    if message == "room does not exist":
        return "room_not_found"
    if message == "game does not exist":
        return "game_not_started"
    if message == "room already exists":
        return "room_exists"
    if message == "game already started":
        return "game_already_started"
    if message == "only host can start the game":
        return "forbidden_start"
    if message == "not enough players":
        return "not_enough_players"
    if message == "all players must be ready before game starts":
        return "players_not_ready"
    if message == "player name already taken":
        return "player_taken"
    if message == "player not in room":
        return "player_not_in_room"
    if "not player's turn" in message:
        return "not_current_player"
    if message == "card not found in player's hand":
        return "card_not_found"
    if "does not match top card" in message:
        return "illegal_play"
    if "chosen color" in message:
        return "invalid_chosen_color"
    if "wild cards require a chosen color" in message:
        return "missing_chosen_color"
    if "UNO can only be called" in message:
        return "invalid_uno_call"
    return "unknown_error"


def _notify_error(ex: Exception):
    message = str(ex)
    return {"type": "error", "code": _error_code(message), "message": message}


def _room_error(ex: Exception):
    message = str(ex)
    return jsonify({"error": message, "code": _error_code(message)}), 400


def _handle_http_room_action(action_name: str):
    data = _json_data()
    try:
        if action_name == "create":
            payloads = room_manager.create_room(data["room_id"], data["host_name"])
        elif action_name == "join":
            payloads = room_manager.join_room(data["room_id"], data["player_name"])
        elif action_name == "ready":
            payloads = room_manager.set_ready(data["room_id"], data["player_id"], bool(data.get("ready", True)))
        elif action_name == "start":
            payloads = room_manager.start_game(
                data["room_id"],
                data["started_by_player_id"],
                hand_size=int(data.get("hand_size", 7)),
                allow_immediate_play_after_draw=bool(data.get("allow_immediate_play_after_draw", True)),
                seed=data.get("seed"),
            )
        elif action_name == "draw":
            payloads = room_manager.draw(data["room_id"], data["player_id"])
        elif action_name == "play":
            payloads = room_manager.play(
                data["room_id"],
                data["player_id"],
                data["card_id"],
                chosen_color=data.get("chosen_color"),
            )
        elif action_name == "uno":
            payloads = room_manager.call_uno(data["room_id"], data["player_id"])
        else:
            raise ValueError(f"unsupported action: {action_name}")
        # if create/join, include reconnect token meta in HTTP response for the caller
        if action_name in ("create", "join"):
            room_id = data["room_id"]
            if action_name == "create":
                player_id = f"player-{data['host_name']}"
            else:
                player_id = f"player-{data['player_name']}"

            room = room_manager.rooms.get(room_id)
            meta = {}
            if room is not None:
                token = room.reconnect_tokens.get(player_id)
                if token:
                    meta = {"reconnect_token": token, "player_id": player_id}

            return jsonify({"events": payloads, "meta": meta}), 200

        return _json_response(payloads)
    except Exception as ex:
        return _room_error(ex)


@app.get("/healthz")
def healthcheck():
    return jsonify({"status": "ok"}), 200


@app.post("/api/rooms/create")
def create_room():
    return _handle_http_room_action("create")


@app.post("/api/rooms/join")
def join_room():
    return _handle_http_room_action("join")


@app.post("/api/rooms/ready")
def set_ready():
    return _handle_http_room_action("ready")


@app.post("/api/rooms/start")
def start_game():
    return _handle_http_room_action("start")


@app.post("/api/rooms/draw")
def draw_card():
    return _handle_http_room_action("draw")


@app.post("/api/rooms/play")
def play_card():
    return _handle_http_room_action("play")


@app.post("/api/rooms/uno")
def call_uno():
    return _handle_http_room_action("uno")


@app.get("/api/rooms")
def list_rooms():
    rooms = []
    for rid, room in room_manager.rooms.items():
        rooms.append({
            "room_id": rid,
            "host_id": room.host_id,
            "players": [p.__dict__ for p in room.players.values()],
        })
    return jsonify({"rooms": rooms}), 200


@app.get("/api/rooms/<room_id>")
def get_room(room_id: str):
    room = room_manager.rooms.get(room_id)
    if room is None:
        return jsonify({"error": "room does not exist"}), 404

    data = {
        "players": [player.__dict__ for player in room.players.values()],
        "host_id": room.host_id,
        "ready": {pid: pid in room.ready_player_ids for pid in room.players},
        "connected": {pid: pid in room.connected_player_ids for pid in room.players},
    }
    return jsonify({"room": data}), 200


@app.post("/api/rooms/leave")
def leave_room():
    data = _json_data()
    try:
        payloads = room_manager.leave_room(data["room_id"], data["player_id"])
        return _json_response(payloads)
    except Exception as ex:
        return _room_error(ex)


@socketio.on(events.PLAYER_JOIN)
def on_player_join(data: Dict[str, Any]):
    room_id = data["room"]
    player_name = data.get("name")
    player_id = data.get("player_id") or (f"player-{player_name}" if player_name else None)
    reconnect_token = data.get("reconnect_token")

    try:
        room = room_manager.rooms.get(room_id)
        if room is None:
            raise ValueError("room does not exist")

        socket_join_room(room_id)
        # handle reconnect using player_id + token
        if player_id and reconnect_token:
            expected = room.reconnect_tokens.get(player_id)
            if expected != reconnect_token:
                raise ValueError("invalid reconnect token")
            payloads = room_manager.connect_player(room_id, player_id, request.sid)
            _emit_payloads(room_id, payloads)
            return

        # normal join by name: create player, send reconnect token to joining socket, then connect
        if not player_id and player_name:
            payloads = room_manager.join_room(room_id, player_name)
            # send reconnect token meta directly to joining client
            player_id = f"player-{player_name}"
            token = room.reconnect_tokens.get(player_id)
            if token:
                emit("session::info", {"reconnect_token": token, "player_id": player_id})

            # now connect the player which will broadcast the updated room snapshot
            payloads = room_manager.connect_player(room_id, player_id, request.sid)
            _emit_payloads(room_id, payloads)
            return

        raise ValueError("missing player identification")
    except Exception as ex:
        emit(events.GAME_NOTIFY, _notify_error(ex))


@socketio.on("disconnect")
def on_disconnect():
    session = room_manager.disconnect_socket(request.sid)
    if session is None:
        return

    room_id, player_id, payloads = session
    emit(events.PLAYER_LEAVE, {"room": room_id, "player_id": player_id}, to=room_id)
    _emit_payloads(room_id, payloads)


@socketio.on(events.PLAYER_READY)
def on_player_ready(data: Dict[str, Any]):
    try:
        payloads = room_manager.set_ready(data["room"], data["player_id"], bool(data.get("ready", True)))
        _emit_payloads(data["room"], payloads)
    except Exception as ex:
        emit(events.GAME_NOTIFY, _notify_error(ex))


@socketio.on(events.GAME_START)
def on_game_start(data: Dict[str, Any]):
    try:
        payloads = room_manager.start_game(
            data["room"],
            data["started_by_player_id"],
            hand_size=int(data.get("hand_size", 7)),
            allow_immediate_play_after_draw=bool(data.get("allow_immediate_play_after_draw", True)),
            seed=data.get("seed"),
        )
        _emit_payloads(data["room"], payloads)
    except Exception as ex:
        emit(events.GAME_NOTIFY, _notify_error(ex))


@socketio.on(events.GAME_DRAW)
def on_game_draw(data: Dict[str, Any]):
    try:
        payloads = room_manager.draw(data["room"], data["player_id"])
        _emit_payloads(data["room"], payloads)
    except Exception as ex:
        emit(events.GAME_NOTIFY, _notify_error(ex))


@socketio.on(events.GAME_PLAY)
def on_game_play(data: Dict[str, Any]):
    try:
        payloads = room_manager.play(
            data["room"],
            data["player_id"],
            data["card_id"],
            chosen_color=data.get("chosen_color"),
        )
        _emit_payloads(data["room"], payloads)
    except Exception as ex:
        emit(events.GAME_NOTIFY, _notify_error(ex))


@socketio.on(events.GAME_UNO)
def on_game_uno(data: Dict[str, Any]):
    try:
        payloads = room_manager.call_uno(data["room"], data["player_id"])
        _emit_payloads(data["room"], payloads)
    except Exception as ex:
        emit(events.GAME_NOTIFY, _notify_error(ex))


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
