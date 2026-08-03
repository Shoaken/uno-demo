from pathlib import Path
import sys

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import app as app_module
from app import app, room_manager, socketio
from core.uno import Card, GameOverReason
from lib import events


@pytest.fixture(autouse=True)
def clear_rooms():
    room_manager.rooms.clear()
    yield
    room_manager.rooms.clear()


def _http_json(client, path: str, payload: dict):
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _http_get(client, path: str):
    response = client.get(path)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _http_json_error(client, path: str, payload: dict):
    response = client.post(path, json=payload)
    assert response.status_code == 400
    body = response.get_json()
    assert "error" in body
    return body


def _attach_socket_client(name: str, room_id: str):
    client = socketio.test_client(app, flask_test_client=app.test_client())
    client.emit(events.PLAYER_JOIN, {"room": room_id, "name": name})
    # consume session::info if present
    client.get_received()
    return client


def _player_id(name: str) -> str:
    return f"player-{name}"


def _capture_emits(monkeypatch):
    emitted: list[dict] = []

    def fake_emit(event_name, data=None, to=None):
        emitted.append({"event": event_name, "data": data or {}, "to": to})

    monkeypatch.setattr(app_module, "emit", fake_emit)
    return emitted


def _event_payloads(emitted: list[dict], event_name: str) -> list[dict]:
    return [event for event in emitted if event["event"] == event_name]


def _prepare_started_room(client, room_id: str, *, allow_immediate_play_after_draw: bool = True, seed: int = 42):
    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})

    start_response = _http_json(
        client,
        "/api/rooms/start",
        {
            "room_id": room_id,
            "started_by_player_id": _player_id("alice"),
            "hand_size": 2,
            "seed": seed,
            "allow_immediate_play_after_draw": allow_immediate_play_after_draw,
        },
    )

    game = room_manager.rooms[room_id].game
    assert game is not None
    return game, start_response


def test_http_room_lifecycle_exposes_game_state():
    client = app.test_client()

    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}

    _http_json(client, "/api/rooms/create", {"room_id": "room-http", "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": "room-http", "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": "room-http", "player_id": "player-alice", "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": "room-http", "player_id": "player-bob", "ready": True})

    start_response = _http_json(
        client,
        "/api/rooms/start",
        {"room_id": "room-http", "started_by_player_id": "player-alice", "hand_size": 2, "seed": 42},
    )

    assert [event["event"] for event in start_response["events"]] == [events.GAME_START, events.GAME_STATE]
    assert start_response["events"][0]["data"] == {"room": "room-http"}
    state = start_response["events"][1]["data"]
    assert set(state.keys()) == {
        "hands",
        "top_card",
        "current_player_id",
        "direction",
        "allow_immediate_play_after_draw",
    }
    assert state["current_player_id"] == "player-alice"
    assert len(state["hands"]) == 2


def test_http_room_actions_reject_invalid_input_and_missing_room():
    client = app.test_client()

    body = _http_json_error(client, "/api/rooms/join", {"room_id": "missing", "player_name": "bob"})
    assert "does not exist" in body["error"]
    assert body["code"] == "room_not_found"

    body = _http_json_error(client, "/api/rooms/draw", {"room_id": "missing", "player_id": "player-bob"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/play", {"room_id": "missing", "player_id": "player-bob", "card_id": "card-1"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/uno", {"room_id": "missing", "player_id": "player-bob"})
    assert "game does not exist" in body["error"]
    assert body["code"] == "game_not_started"

    _http_json(client, "/api/rooms/create", {"room_id": "room-error", "host_name": "alice"})

    body = _http_json_error(client, "/api/rooms/draw", {"room_id": "room-error", "player_id": "player-alice"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/play", {"room_id": "room-error", "player_id": "player-alice", "card_id": "card-1"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/uno", {"room_id": "room-error", "player_id": "player-alice"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/create", {"room_id": "room-error", "host_name": "alice2"})
    assert "already exists" in body["error"]
    assert body["code"] == "room_exists"

    body = _http_json_error(client, "/api/rooms/join", {"room_id": "room-error", "player_name": "alice"})
    assert "already taken" in body["error"]

    body = _http_json_error(client, "/api/rooms/ready", {"room_id": "room-error", "player_id": "player-bob", "ready": True})
    assert "not in room" in body["error"]

    body = _http_json_error(client, "/api/rooms/start", {"room_id": "room-error", "started_by_player_id": "player-alice"})
    assert "not enough players" in body["error"]
    assert body["code"] == "not_enough_players"


def test_http_room_actions_reject_missing_parameters_and_invalid_chosen_color():
    client = app.test_client()

    body = _http_json_error(client, "/api/rooms/draw", {})
    assert "room_id" in body["error"]

    body = _http_json_error(client, "/api/rooms/play", {"room_id": "room-missing-fields"})
    assert "player_id" in body["error"] or "card_id" in body["error"]

    body = _http_json_error(client, "/api/rooms/uno", {"room_id": "room-missing-fields"})
    assert "player_id" in body["error"]

    game, _ = _prepare_started_room(client, "room-invalid-color")
    current_player_id = game.get_state()["current_player_id"]
    top_card = game.discard_pile[-1]
    wild_card = Card(id="invalid-color-wild", color="black", value="wild")
    game.hands[current_player_id] = [wild_card]
    game.discard_pile[-1] = Card(id="invalid-color-top", color=top_card.color, value=top_card.value)

    body = _http_json_error(
        client,
        "/api/rooms/play",
        {
            "room_id": "room-invalid-color",
            "player_id": current_player_id,
            "card_id": wild_card.id,
            "chosen_color": "purple",
        },
    )
    assert "chosen color" in body["error"]
    assert body["code"] == "invalid_chosen_color"


def test_http_and_socket_draw_keep_immediate_play_disabled(monkeypatch):
    client = app.test_client()
    room_id = "room-no-immediate-play"
    game, start_response = _prepare_started_room(client, room_id, allow_immediate_play_after_draw=False, seed=7)

    assert start_response["events"][1]["data"]["allow_immediate_play_after_draw"] is False

    current_player_id = game.get_state()["current_player_id"]
    http_draw_response = _http_json(client, "/api/rooms/draw", {"room_id": room_id, "player_id": current_player_id})
    http_state = http_draw_response["events"][0]["data"]
    assert http_state["current_player_id"] == _player_id("bob")

    socket_room_id = "room-no-immediate-play-socket"
    socket_game, _ = _prepare_started_room(client, socket_room_id, allow_immediate_play_after_draw=False, seed=11)
    host_socket = _attach_socket_client("alice", socket_room_id)
    _attach_socket_client("bob", socket_room_id)
    emitted = _capture_emits(monkeypatch)

    host_socket.emit(events.GAME_DRAW, {"room": socket_room_id, "player_id": socket_game.get_state()["current_player_id"]})

    state_events = _event_payloads(emitted, events.GAME_STATE)
    assert len(state_events) == 1
    assert state_events[0]["to"] == socket_room_id
    assert state_events[0]["data"]["current_player_id"] == _player_id("bob")


def test_socket_player_ready_updates_room_state_and_broadcasts_room_snapshot(monkeypatch):
    client = app.test_client()
    room_id = "room-ready"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})

    socket_client = _attach_socket_client("alice", room_id)
    emitted = _capture_emits(monkeypatch)

    socket_client.emit(events.PLAYER_READY, {"room": room_id, "player_id": _player_id("alice"), "ready": True})
    ready_events = _event_payloads(emitted, events.GAME_ROOM)
    assert len(ready_events) == 1
    assert ready_events[0]["to"] == room_id
    assert ready_events[0]["data"]["ready"] == {"player-alice": True, "player-bob": False}
    assert ready_events[0]["data"]["connected"]["player-alice"] is True
    assert _player_id("alice") in room_manager.rooms[room_id].ready_player_ids

    emitted.clear()
    socket_client.emit(events.PLAYER_READY, {"room": room_id, "player_id": _player_id("alice"), "ready": False})
    unready_events = _event_payloads(emitted, events.GAME_ROOM)
    assert len(unready_events) == 1
    assert unready_events[0]["data"]["ready"] == {"player-alice": False, "player-bob": False}
    assert _player_id("alice") not in room_manager.rooms[room_id].ready_player_ids


def test_socket_player_join_is_idempotent_and_reports_missing_room(monkeypatch):
    client = app.test_client()
    room_id = "room-join"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})

    bob_socket = socketio.test_client(app, flask_test_client=app.test_client())
    emitted = _capture_emits(monkeypatch)

    bob_socket.emit(events.PLAYER_JOIN, {"room": room_id, "name": "bob"})
    join_events = _event_payloads(emitted, events.GAME_ROOM)
    assert len(join_events) == 1
    assert join_events[0]["to"] == room_id
    assert join_events[0]["data"]["connected"]["player-bob"] is True
    assert len(room_manager.rooms[room_id].players) == 2

    emitted.clear()
    bob_socket.emit(events.PLAYER_JOIN, {"room": room_id, "name": "bob"})
    repeat_join_events = _event_payloads(emitted, events.GAME_ROOM)
    assert len(repeat_join_events) == 1
    assert len(room_manager.rooms[room_id].players) == 2

    emitted.clear()
    ghost_socket = socketio.test_client(app, flask_test_client=app.test_client())
    ghost_socket.emit(events.PLAYER_JOIN, {"room": "missing-room", "name": "ghost"})
    notify_events = _event_payloads(emitted, events.GAME_NOTIFY)
    assert len(notify_events) == 1
    assert notify_events[0]["data"]["type"] == "error"
    assert notify_events[0]["data"]["code"] == "room_not_found"
    assert "room does not exist" in notify_events[0]["data"]["message"]


def test_socket_disconnect_broadcasts_leave_and_marks_player_offline(monkeypatch):
    client = app.test_client()
    room_id = "room-disconnect"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    alice_socket = _attach_socket_client("alice", room_id)
    emitted = _capture_emits(monkeypatch)

    alice_socket.disconnect()

    leave_events = _event_payloads(emitted, events.PLAYER_LEAVE)
    assert len(leave_events) == 1
    assert leave_events[0]["to"] == room_id
    assert leave_events[0]["data"] == {"room": room_id, "player_id": _player_id("alice")}

    room_snapshot_events = _event_payloads(emitted, events.GAME_ROOM)
    assert len(room_snapshot_events) == 1
    assert room_snapshot_events[0]["data"]["connected"]["player-alice"] is False
    assert _player_id("alice") not in room_manager.rooms[room_id].connected_player_ids


def test_socket_rejoin_restores_room_and_game_state(monkeypatch):
    client = app.test_client()
    room_id = "room-reconnect"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})

    alice_socket = _attach_socket_client("alice", room_id)
    bob_socket = _attach_socket_client("bob", room_id)
    emitted = _capture_emits(monkeypatch)

    alice_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 31})
    emitted.clear()

    bob_socket.disconnect()
    emitted.clear()

    reconnect_socket = socketio.test_client(app, flask_test_client=app.test_client())
    # attempt reconnect using token
    # retrieve token from room_manager
    token = room_manager.rooms[room_id].reconnect_tokens[_player_id("bob")]
    reconnect_socket.emit(events.PLAYER_JOIN, {"room": room_id, "player_id": _player_id("bob"), "reconnect_token": token})

    room_events = _event_payloads(emitted, events.GAME_ROOM)
    state_events = _event_payloads(emitted, events.GAME_STATE)
    assert len(room_events) == 1
    assert len(state_events) == 1
    assert room_events[0]["data"]["connected"]["player-bob"] is True
    assert state_events[0]["data"] == room_manager.rooms[room_id].game.get_state()


def test_socket_join_emits_session_info_to_joining_client():
    client = app.test_client()
    room_id = "room-session-info"

    create_resp = _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    join_resp = _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})

    # join via socket and verify session::info received
    bob_socket = socketio.test_client(app, flask_test_client=app.test_client())
    session_info = bob_socket.emit(events.PLAYER_JOIN, {"room": room_id, "name": "bob"}, callback=True)
    meta = join_resp.get("meta")
    assert meta is not None
    assert session_info["player_id"] == meta["player_id"]
    assert session_info["reconnect_token"] == meta["reconnect_token"]


def test_http_meta_allows_socket_reconnect(monkeypatch):
    client = app.test_client()
    room_id = "room-meta-reconnect"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    join_resp = _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    meta = join_resp.get("meta")
    assert meta and "reconnect_token" in meta

    # attach sockets and start a game so GAME_STATE exists
    alice_socket = _attach_socket_client("alice", room_id)
    bob_socket = _attach_socket_client("bob", room_id)
    emitted = _capture_emits(monkeypatch)

    alice_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 31})
    emitted.clear()

    bob_socket.disconnect()
    emitted.clear()

    reconnect_socket = socketio.test_client(app, flask_test_client=app.test_client())
    reconnect_socket.emit(events.PLAYER_JOIN, {"room": room_id, "player_id": _player_id("bob"), "reconnect_token": meta["reconnect_token"]})

    room_events = _event_payloads(emitted, events.GAME_ROOM)
    state_events = _event_payloads(emitted, events.GAME_STATE)
    assert len(room_events) == 1
    assert len(state_events) == 1
    assert room_events[0]["data"]["connected"]["player-bob"] is True


def test_leave_removes_reconnect_token():
    client = app.test_client()
    room_id = "room-leave-token"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    join_resp = _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    meta = join_resp.get("meta")
    assert meta and "reconnect_token" in meta

    # bob leaves
    resp = client.post("/api/rooms/leave", json={"room_id": room_id, "player_id": _player_id("bob")})
    assert resp.status_code == 200

    room = room_manager.rooms.get(room_id)
    # token should be removed
    if room is not None:
        assert _player_id("bob") not in room.reconnect_tokens



def test_socket_player_ready_rejects_missing_room_and_supports_unready_toggle(monkeypatch):
    client = app.test_client()
    room_id = "room-ready-boundary"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})

    bob_socket = _attach_socket_client("bob", room_id)
    bob_socket.get_received()
    emitted = _capture_emits(monkeypatch)

    bob_socket.emit(events.PLAYER_READY, {"room": room_id, "player_id": _player_id("bob"), "ready": True})
    bob_socket.emit(events.PLAYER_READY, {"room": room_id, "player_id": _player_id("bob"), "ready": True})
    assert _player_id("bob") in room_manager.rooms[room_id].ready_player_ids

    bob_socket.emit(events.PLAYER_READY, {"room": room_id, "player_id": _player_id("bob"), "ready": False})
    assert _player_id("bob") not in room_manager.rooms[room_id].ready_player_ids

    emitted.clear()
    ghost_socket = socketio.test_client(app, flask_test_client=app.test_client())
    ghost_socket.emit(events.PLAYER_READY, {"room": "missing-room", "player_id": _player_id("ghost"), "ready": True})
    notify_events = _event_payloads(emitted, events.GAME_NOTIFY)
    assert len(notify_events) == 1
    assert notify_events[0]["data"]["type"] == "error"
    assert "room does not exist" in notify_events[0]["data"]["message"]


def test_socket_gameplay_handles_skip_reverse_and_draw_two(monkeypatch):
    client = app.test_client()
    room_id = "room-actions"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "charlie"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("charlie"), "ready": True})

    host_socket = _attach_socket_client("alice", room_id)
    _attach_socket_client("bob", room_id)
    _attach_socket_client("charlie", room_id)
    emitted = _capture_emits(monkeypatch)

    host_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 7})
    start_events = _event_payloads(emitted, events.GAME_START) + _event_payloads(emitted, events.GAME_STATE)
    assert [event["event"] for event in start_events] == [events.GAME_START, events.GAME_STATE]
    assert start_events[0]["data"] == {"room": room_id}
    assert set(start_events[1]["data"].keys()) == {
        "hands",
        "top_card",
        "current_player_id",
        "direction",
        "allow_immediate_play_after_draw",
    }

    game = room_manager.rooms[room_id].game
    assert game is not None

    top_color = game.discard_pile[-1].color
    skip_card = Card(id="event-skip", color=top_color, value="skip")
    reverse_card = Card(id="event-reverse", color=top_color, value="reverse")
    draw_two_card = Card(id="event-draw-two", color=top_color, value="draw-two")

    game.hands[_player_id("alice")][0] = skip_card
    game.hands[_player_id("bob")][0] = reverse_card
    game.hands[_player_id("charlie")][0] = draw_two_card

    emitted.clear()
    host_socket.emit(events.GAME_PLAY, {"room": room_id, "player_id": _player_id("alice"), "card_id": skip_card.id})
    skip_events = _event_payloads(emitted, events.GAME_STATE)
    assert len(skip_events) == 1
    assert skip_events[0]["to"] == room_id
    assert game.get_state()["current_player_id"] == _player_id("charlie")

    game.discard_pile[-1] = Card(id="event-top-2", color=top_color, value="2")
    game.turn_index = 2
    emitted.clear()
    host_socket.emit(events.GAME_PLAY, {"room": room_id, "player_id": _player_id("charlie"), "card_id": draw_two_card.id})
    draw_two_events = _event_payloads(emitted, events.GAME_STATE)
    assert len(draw_two_events) == 1
    assert draw_two_events[0]["data"]["current_player_id"] == _player_id("bob")
    assert len(game.hands[_player_id("alice")]) >= 2

    game.discard_pile[-1] = Card(id="event-top-3", color=top_color, value="5")
    game.turn_index = 1
    emitted.clear()
    host_socket.emit(events.GAME_PLAY, {"room": room_id, "player_id": _player_id("bob"), "card_id": reverse_card.id})
    reverse_events = _event_payloads(emitted, events.GAME_STATE)
    assert len(reverse_events) == 1
    assert game.get_state()["direction"] == -1


def test_socket_gameplay_handles_wild_draw_four_and_uno(monkeypatch):
    client = app.test_client()
    room_id = "room-wild-uno"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})

    host_socket = _attach_socket_client("alice", room_id)
    _attach_socket_client("bob", room_id)
    emitted = _capture_emits(monkeypatch)

    host_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 11})
    start_events = _event_payloads(emitted, events.GAME_START) + _event_payloads(emitted, events.GAME_STATE)
    assert [event["event"] for event in start_events] == [events.GAME_START, events.GAME_STATE]

    game = room_manager.rooms[room_id].game
    assert game is not None

    top_color = game.discard_pile[-1].color
    wild_draw_four = Card(id="event-draw-four", color="black", value="draw-four")
    support_color = next(color for color in ["red", "blue", "green", "yellow"] if color != top_color)
    support_value = next(value for value in ["1", "2", "3", "4", "5", "6", "7", "8", "9"] if value != game.discard_pile[-1].value)
    support_card = Card(id="event-support", color=support_color, value=support_value)
    game.hands[_player_id("alice")] = [wild_draw_four, support_card]

    emitted.clear()
    host_socket.emit(
        events.GAME_PLAY,
        {
            "room": room_id,
            "player_id": _player_id("alice"),
            "card_id": wild_draw_four.id,
            "chosen_color": "blue",
        },
    )

    play_events = _event_payloads(emitted, events.GAME_STATE)
    assert len(play_events) == 1
    assert play_events[0]["data"]["top_card"]["color"] == "blue"
    assert game.discard_pile[-1].color == "blue"
    assert game.pending_uno_player_id == _player_id("alice")

    emitted.clear()
    host_socket.emit(events.GAME_UNO, {"room": room_id, "player_id": _player_id("alice")})
    uno_events = _event_payloads(emitted, events.GAME_STATE)
    assert len(uno_events) == 1
    assert game.pending_uno_player_id is None
    assert game.uno_called[_player_id("alice")] is True


def test_socket_gameplay_rejects_wild_without_chosen_color(monkeypatch):
    client = app.test_client()
    room_id = "room-wild-error"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})

    host_socket = _attach_socket_client("alice", room_id)
    host_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 19})

    game = room_manager.rooms[room_id].game
    assert game is not None

    wild = Card(id="event-wild", color="black", value="wild")
    game.hands[_player_id("alice")][0] = wild
    emitted = _capture_emits(monkeypatch)

    host_socket.emit(events.GAME_PLAY, {"room": room_id, "player_id": _player_id("alice"), "card_id": wild.id})

    notify_events = _event_payloads(emitted, events.GAME_NOTIFY)
    assert len(notify_events) == 1
    assert notify_events[0]["data"]["type"] == "error"
    assert "chosen color" in notify_events[0]["data"]["message"]


def test_socket_gameplay_handles_draw_two_and_broadcasts_state(monkeypatch):
    client = app.test_client()
    room_id = "room-socket-draw-two"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "charlie"})

    host_socket = _attach_socket_client("alice", room_id)
    bob_socket = _attach_socket_client("bob", room_id)

    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": "player-alice", "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": "player-bob", "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": "player-charlie", "ready": True})

    emitted = _capture_emits(monkeypatch)
    host_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": "player-alice", "hand_size": 2, "seed": 7})

    game = room_manager.rooms[room_id].game
    assert game is not None
    assert game.get_state()["current_player_id"] == "player-alice"

    top_color = game.discard_pile[-1].color
    draw_two = Card(id="event-draw-two", color=top_color, value="draw-two")
    game.hands["player-alice"] = [draw_two, Card(id="event-support", color="green", value="5")]
    bob_hand_before = len(game.hands["player-bob"])

    emitted.clear()
    host_socket.emit(
        events.GAME_PLAY,
        {"room": room_id, "player_id": "player-alice", "card_id": draw_two.id},
    )

    state_events = _event_payloads(emitted, events.GAME_STATE)
    assert len(state_events) == 1
    assert state_events[0]["to"] == room_id
    assert game.get_state()["current_player_id"] == "player-charlie"
    assert len(game.hands["player-bob"]) >= bob_hand_before
    assert host_socket.is_connected()
    assert bob_socket.is_connected()


def test_socket_room_broadcasts_same_state_to_multiple_clients(monkeypatch):
    client = app.test_client()
    room_id = "room-broadcast"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})

    alice_socket = _attach_socket_client("alice", room_id)
    bob_socket = _attach_socket_client("bob", room_id)
    alice_socket.get_received()
    bob_socket.get_received()
    emitted = _capture_emits(monkeypatch)

    alice_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 5})
    start_states = _event_payloads(emitted, events.GAME_STATE)
    assert len(start_states) == 1
    assert start_states[0]["to"] == room_id

    game = room_manager.rooms[room_id].game
    assert game is not None
    emitted.clear()
    alice_socket.emit(events.GAME_DRAW, {"room": room_id, "player_id": _player_id("alice")})

    draw_states = _event_payloads(emitted, events.GAME_STATE)
    assert len(draw_states) == 1
    assert draw_states[0]["to"] == room_id
    assert draw_states[0]["data"] == room_manager.rooms[room_id].game.get_state()


def test_http_game_over_payload_contains_winner_details():
    client = app.test_client()
    room_id = "room-http-over"

    game, _ = _prepare_started_room(client, room_id, seed=23)
    current_player_id = game.get_state()["current_player_id"]
    top_card = game.discard_pile[-1]
    winning_card = Card(id="winning-card", color=top_card.color, value=top_card.value)
    game.hands[current_player_id] = [winning_card]

    response = _http_json(
        client,
        "/api/rooms/play",
        {"room_id": room_id, "player_id": current_player_id, "card_id": winning_card.id},
    )

    assert [event["event"] for event in response["events"]] == [events.GAME_STATE, events.GAME_OVER]
    state = response["events"][0]["data"]
    over = response["events"][1]["data"]
    assert set(state.keys()) == {
        "hands",
        "top_card",
        "current_player_id",
        "direction",
        "allow_immediate_play_after_draw",
    }
    assert over == {"reason": GameOverReason.WON.value, "winner": current_player_id}


def test_http_create_and_join_return_reconnect_meta():
    client = app.test_client()
    create_resp = _http_json(client, "/api/rooms/create", {"room_id": "r-meta", "host_name": "alice"})
    assert "meta" in create_resp
    assert "reconnect_token" in create_resp["meta"]
    assert "player_id" in create_resp["meta"]

    join_resp = _http_json(client, "/api/rooms/join", {"room_id": "r-meta", "player_name": "bob"})
    assert "meta" in join_resp
    assert "reconnect_token" in join_resp["meta"]
    assert join_resp["meta"]["player_id"] == _player_id("bob")


def test_http_list_and_get_room_endpoints():
    client = app.test_client()
    _http_json(client, "/api/rooms/create", {"room_id": "r-list", "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": "r-list", "player_name": "bob"})

    list_resp = _http_get(client, "/api/rooms")
    assert any(r["room_id"] == "r-list" for r in list_resp["rooms"])

    get_resp = client.get("/api/rooms/r-list")
    assert get_resp.status_code == 200
    body = get_resp.get_json()
    assert "room" in body
    assert body["room"]["host_id"] == _player_id("alice")
    assert any(p["id"] == _player_id("bob") for p in body["room"]["players"])


def test_http_leave_transfers_host_and_removes_room_when_empty():
    client = app.test_client()
    # create room with three players
    _http_json(client, "/api/rooms/create", {"room_id": "r-leave", "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": "r-leave", "player_name": "bob"})
    _http_json(client, "/api/rooms/join", {"room_id": "r-leave", "player_name": "charlie"})

    # alice leaves (host leaves)
    resp = client.post("/api/rooms/leave", json={"room_id": "r-leave", "player_id": _player_id("alice")})
    assert resp.status_code == 200
    data = resp.get_json()
    # ensure alice not in players and host changed
    room = room_manager.rooms.get("r-leave")
    assert room is not None
    assert _player_id("alice") not in room.players
    assert room.host_id != _player_id("alice")

    # remove remaining players
    client.post("/api/rooms/leave", json={"room_id": "r-leave", "player_id": _player_id("bob")})
    client.post("/api/rooms/leave", json={"room_id": "r-leave", "player_id": _player_id("charlie")})

    # now room should be removed
    get_resp = client.get("/api/rooms/r-leave")
    assert get_resp.status_code == 404


def test_socket_reconnect_with_invalid_token_emits_notify(monkeypatch):
    client = app.test_client()
    room_id = "r-invalid-token"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})

    emitted = _capture_emits(monkeypatch)
    # attempt reconnect with wrong token
    reconnect_socket = socketio.test_client(app, flask_test_client=app.test_client())
    reconnect_socket.emit(events.PLAYER_JOIN, {"room": room_id, "player_id": _player_id("bob"), "reconnect_token": "wrongtoken"})

    notify = _event_payloads(emitted, events.GAME_NOTIFY)
    assert len(notify) == 1
    assert "invalid reconnect token" in notify[0]["data"]["message"]


def test_classroom_demo_smoke_flow_create_join_start_play_and_leave():
    client = app.test_client()
    room_id = "room-demo-smoke"

    create_resp = _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    join_resp = _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})

    start_resp = _http_json(
        client,
        "/api/rooms/start",
        {"room_id": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 101},
    )

    game = room_manager.rooms[room_id].game
    assert game is not None
    current_player_id = game.get_state()["current_player_id"]
    top_card = game.discard_pile[-1]
    matching_card = Card(id="demo-play-card", color=top_card.color, value=top_card.value)
    filler_card = Card(id="demo-filler-card", color="blue", value="1")
    game.hands[current_player_id] = [matching_card, filler_card]

    play_resp = _http_json(
        client,
        "/api/rooms/play",
        {"room_id": room_id, "player_id": current_player_id, "card_id": matching_card.id},
    )

    assert [event["event"] for event in create_resp["events"]] == [events.GAME_ROOM]
    assert [event["event"] for event in join_resp["events"]] == [events.GAME_ROOM]
    assert [event["event"] for event in start_resp["events"]] == [events.GAME_START, events.GAME_STATE]
    assert [event["event"] for event in play_resp["events"]] == [events.GAME_STATE]

    _http_json(client, "/api/rooms/leave", {"room_id": room_id, "player_id": _player_id("bob")})
    _http_json(client, "/api/rooms/leave", {"room_id": room_id, "player_id": _player_id("alice")})

    assert client.get(f"/api/rooms/{room_id}").status_code == 404


def test_room_status_reflects_host_player_and_connection_state():
    client = app.test_client()
    room_id = "room-status-view"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})

    alice_socket = _attach_socket_client("alice", room_id)
    bob_socket = _attach_socket_client("bob", room_id)

    status_body = client.get(f"/api/rooms/{room_id}").get_json()["room"]
    assert status_body["host_id"] == _player_id("alice")
    assert status_body["connected"] == {"player-alice": True, "player-bob": True}
    assert {player["id"] for player in status_body["players"]} == {_player_id("alice"), _player_id("bob")}

    bob_socket.disconnect()
    status_after_disconnect = client.get(f"/api/rooms/{room_id}").get_json()["room"]
    assert status_after_disconnect["connected"]["player-bob"] is False
    assert status_after_disconnect["connected"]["player-alice"] is True

    alice_socket.disconnect()


def test_demo_error_paths_cover_missing_room_duplicate_join_and_non_current_player(monkeypatch):
    client = app.test_client()
    room_id = "room-demo-errors"

    missing_room_error = client.post("/api/rooms/join", json={"room_id": "missing-room", "player_name": "bob"})
    assert missing_room_error.status_code == 400
    assert missing_room_error.get_json()["code"] == "room_not_found"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    duplicate_join = client.post("/api/rooms/join", json={"room_id": room_id, "player_name": "alice"})
    assert duplicate_join.status_code == 400
    assert duplicate_join.get_json()["code"] == "player_taken"

    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})
    _http_json(
        client,
        "/api/rooms/start",
        {"room_id": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 77},
    )

    game = room_manager.rooms[room_id].game
    assert game is not None
    top_card = game.discard_pile[-1]
    bad_card = Card(id="demo-bad-card", color="red", value="1")
    game.hands[_player_id("bob")] = [bad_card]
    game.turn_index = 0

    not_current_player = client.post(
        "/api/rooms/play",
        json={"room_id": room_id, "player_id": _player_id("bob"), "card_id": bad_card.id},
    )
    assert not_current_player.status_code == 400
    assert "not player's turn" in not_current_player.get_json()["error"]

    game.hands[_player_id("alice")] = [Card(id="demo-illegal-card", color="yellow", value="9")]
    illegal_play = client.post(
        "/api/rooms/play",
        json={"room_id": room_id, "player_id": _player_id("alice"), "card_id": "demo-illegal-card"},
    )
    assert illegal_play.status_code == 400
    assert "does not match top card" in illegal_play.get_json()["error"]
