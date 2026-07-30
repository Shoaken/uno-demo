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


def _room_error(ex: Exception):
    return jsonify({"error": str(ex)}), 400


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


@socketio.on(events.PLAYER_JOIN)
def on_player_join(data: Dict[str, Any]):
    room_id = data["room"]
    player_name = data["name"]
    player_id = f"player-{player_name}"

    try:
        room = room_manager.rooms.get(room_id)
        if room is None:
            raise ValueError("room does not exist")

        socket_join_room(room_id)

        if player_id not in room.players:
            payloads = room_manager.join_room(room_id, player_name)
            _emit_payloads(room_id, payloads)
            return

        emit(events.GAME_ROOM, room_manager._events_for_room(room)[0]["data"], to=room_id)
    except Exception as ex:
        emit(events.GAME_NOTIFY, {"type": "error", "message": str(ex)})


@socketio.on(events.PLAYER_READY)
def on_player_ready(data: Dict[str, Any]):
    try:
        payloads = room_manager.set_ready(data["room"], data["player_id"], bool(data.get("ready", True)))
        _emit_payloads(data["room"], payloads)
    except Exception as ex:
        emit(events.GAME_NOTIFY, {"type": "error", "message": str(ex)})


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
        emit(events.GAME_NOTIFY, {"type": "error", "message": str(ex)})


@socketio.on(events.GAME_DRAW)
def on_game_draw(data: Dict[str, Any]):
    try:
        payloads = room_manager.draw(data["room"], data["player_id"])
        _emit_payloads(data["room"], payloads)
    except Exception as ex:
        emit(events.GAME_NOTIFY, {"type": "error", "message": str(ex)})


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
        emit(events.GAME_NOTIFY, {"type": "error", "message": str(ex)})


@socketio.on(events.GAME_UNO)
def on_game_uno(data: Dict[str, Any]):
    try:
        payloads = room_manager.call_uno(data["room"], data["player_id"])
        _emit_payloads(data["room"], payloads)
    except Exception as ex:
        emit(events.GAME_NOTIFY, {"type": "error", "message": str(ex)})


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
