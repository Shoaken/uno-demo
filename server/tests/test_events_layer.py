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


def _http_json_error(client, path: str, payload: dict):
    response = client.post(path, json=payload)
    assert response.status_code == 400
    body = response.get_json()
    assert "error" in body
    return body


def _attach_socket_client(name: str, room_id: str):
    client = socketio.test_client(app, flask_test_client=app.test_client())
    client.emit(events.PLAYER_JOIN, {"room": room_id, "name": name})
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

    body = _http_json_error(client, "/api/rooms/draw", {"room_id": "missing", "player_id": "player-bob"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/play", {"room_id": "missing", "player_id": "player-bob", "card_id": "card-1"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/uno", {"room_id": "missing", "player_id": "player-bob"})
    assert "game does not exist" in body["error"]

    _http_json(client, "/api/rooms/create", {"room_id": "room-error", "host_name": "alice"})

    body = _http_json_error(client, "/api/rooms/draw", {"room_id": "room-error", "player_id": "player-alice"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/play", {"room_id": "room-error", "player_id": "player-alice", "card_id": "card-1"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/uno", {"room_id": "room-error", "player_id": "player-alice"})
    assert "game does not exist" in body["error"]

    body = _http_json_error(client, "/api/rooms/create", {"room_id": "room-error", "host_name": "alice2"})
    assert "already exists" in body["error"]

    body = _http_json_error(client, "/api/rooms/join", {"room_id": "room-error", "player_name": "alice"})
    assert "already taken" in body["error"]

    body = _http_json_error(client, "/api/rooms/ready", {"room_id": "room-error", "player_id": "player-bob", "ready": True})
    assert "not in room" in body["error"]

    body = _http_json_error(client, "/api/rooms/start", {"room_id": "room-error", "started_by_player_id": "player-alice"})
    assert "not enough players" in body["error"]


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
    assert "room does not exist" in notify_events[0]["data"]["message"]


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
