from pathlib import Path
import sys

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import app as app_module
from app import app, room_manager, socketio
from core.uno import Card
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

    _http_json(client, "/api/rooms/create", {"room_id": "room-error", "host_name": "alice"})

    body = _http_json_error(client, "/api/rooms/create", {"room_id": "room-error", "host_name": "alice2"})
    assert "already exists" in body["error"]

    body = _http_json_error(client, "/api/rooms/join", {"room_id": "room-error", "player_name": "alice"})
    assert "already taken" in body["error"]

    body = _http_json_error(client, "/api/rooms/ready", {"room_id": "room-error", "player_id": "player-bob", "ready": True})
    assert "not in room" in body["error"]

    body = _http_json_error(client, "/api/rooms/start", {"room_id": "room-error", "started_by_player_id": "player-alice"})
    assert "not enough players" in body["error"]


def test_socket_player_ready_updates_room_state_and_broadcasts_room_snapshot():
    client = app.test_client()
    room_id = "room-ready"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})

    socket_client = _attach_socket_client("alice", room_id)
    socket_client.get_received()

    emitted: list[tuple[str, dict, str | None]] = []

    def fake_emit(event_name, data=None, to=None):
        emitted.append((event_name, data or {}, to))

    original_emit = app_module.emit
    app_module.emit = fake_emit
    try:
        socket_client.emit(events.PLAYER_READY, {"room": room_id, "player_id": _player_id("alice"), "ready": True})
    finally:
        app_module.emit = original_emit

    room = room_manager.rooms[room_id]
    assert _player_id("alice") in room.ready_player_ids
    assert any(event_name == events.GAME_ROOM and to == room_id for event_name, _, to in emitted)


def test_socket_gameplay_handles_skip_reverse_and_draw_two():
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

    host_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 7})
    host_socket.get_received()

    game = room_manager.rooms[room_id].game
    assert game is not None

    top_color = game.discard_pile[-1].color
    skip_card = Card(id="event-skip", color=top_color, value="skip")
    reverse_card = Card(id="event-reverse", color=top_color, value="reverse")
    draw_two_card = Card(id="event-draw-two", color=top_color, value="draw-two")

    game.hands[_player_id("alice")][0] = skip_card
    game.hands[_player_id("bob")][0] = reverse_card
    game.hands[_player_id("charlie")][0] = draw_two_card

    host_socket.emit(events.GAME_PLAY, {"room": room_id, "player_id": _player_id("alice"), "card_id": skip_card.id})
    assert game.get_state()["current_player_id"] == _player_id("charlie")

    game.discard_pile[-1] = Card(id="event-top-2", color=top_color, value="2")
    game.turn_index = 2
    host_socket.emit(events.GAME_PLAY, {"room": room_id, "player_id": _player_id("charlie"), "card_id": draw_two_card.id})
    assert len(game.hands[_player_id("alice")]) >= 2

    game.discard_pile[-1] = Card(id="event-top-3", color=top_color, value="5")
    game.turn_index = 1
    host_socket.emit(events.GAME_PLAY, {"room": room_id, "player_id": _player_id("bob"), "card_id": reverse_card.id})
    assert game.get_state()["direction"] == -1


def test_socket_gameplay_handles_wild_draw_four_and_uno():
    client = app.test_client()
    room_id = "room-wild-uno"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})

    host_socket = _attach_socket_client("alice", room_id)
    _attach_socket_client("bob", room_id)

    host_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 11})
    host_socket.get_received()

    game = room_manager.rooms[room_id].game
    assert game is not None

    top_color = game.discard_pile[-1].color
    wild_draw_four = Card(id="event-draw-four", color="black", value="draw-four")
    support_color = next(color for color in ["red", "blue", "green", "yellow"] if color != top_color)
    support_value = next(value for value in ["1", "2", "3", "4", "5", "6", "7", "8", "9"] if value != game.discard_pile[-1].value)
    support_card = Card(id="event-support", color=support_color, value=support_value)
    game.hands[_player_id("alice")] = [wild_draw_four, support_card]

    host_socket.emit(
        events.GAME_PLAY,
        {
            "room": room_id,
            "player_id": _player_id("alice"),
            "card_id": wild_draw_four.id,
            "chosen_color": "blue",
        },
    )

    assert game.discard_pile[-1].color == "blue"
    assert game.pending_uno_player_id == _player_id("alice")

    host_socket.emit(events.GAME_UNO, {"room": room_id, "player_id": _player_id("alice")})

    assert game.pending_uno_player_id is None
    assert game.uno_called[_player_id("alice")] is True


def test_socket_gameplay_rejects_wild_without_chosen_color():
    client = app.test_client()
    room_id = "room-wild-error"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("alice"), "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": _player_id("bob"), "ready": True})

    host_socket = _attach_socket_client("alice", room_id)
    host_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": _player_id("alice"), "hand_size": 2, "seed": 19})
    host_socket.get_received()

    game = room_manager.rooms[room_id].game
    assert game is not None

    wild = Card(id="event-wild", color="black", value="wild")
    game.hands[_player_id("alice")][0] = wild

    emitted: list[tuple[str, dict, str | None]] = []

    def fake_emit(event_name, data=None, to=None):
        emitted.append((event_name, data or {}, to))

    original_emit = app_module.emit
    app_module.emit = fake_emit
    host_socket.emit(events.GAME_PLAY, {"room": room_id, "player_id": _player_id("alice"), "card_id": wild.id})
    app_module.emit = original_emit

    assert any(event == events.GAME_NOTIFY for event, _, _ in emitted)
    assert any("chosen color" in data.get("message", "") for event, data, _ in emitted if event == events.GAME_NOTIFY)


def test_socket_gameplay_handles_draw_two_and_broadcasts_state():
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

    host_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": "player-alice", "hand_size": 2, "seed": 7})
    game = room_manager.rooms[room_id].game
    assert game is not None
    assert game.get_state()["current_player_id"] == "player-alice"

    top_color = game.discard_pile[-1].color
    draw_two = Card(id="event-draw-two", color=top_color, value="draw-two")
    game.hands["player-alice"][0] = draw_two
    bob_hand_before = len(game.hands["player-bob"])

    host_socket.emit(
        events.GAME_PLAY,
        {"room": room_id, "player_id": "player-alice", "card_id": draw_two.id},
    )

    assert len(game.hands["player-bob"]) == bob_hand_before + 2
    assert game.get_state()["current_player_id"] == "player-charlie"
    assert host_socket.is_connected()
    assert bob_socket.is_connected()


def test_socket_gameplay_handles_wild_and_uno():
    client = app.test_client()
    room_id = "room-socket-wild"

    _http_json(client, "/api/rooms/create", {"room_id": room_id, "host_name": "alice"})
    _http_json(client, "/api/rooms/join", {"room_id": room_id, "player_name": "bob"})

    host_socket = _attach_socket_client("alice", room_id)
    bob_socket = _attach_socket_client("bob", room_id)

    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": "player-alice", "ready": True})
    _http_json(client, "/api/rooms/ready", {"room_id": room_id, "player_id": "player-bob", "ready": True})

    host_socket.emit(events.GAME_START, {"room": room_id, "started_by_player_id": "player-alice", "hand_size": 2, "seed": 11})
    host_socket.get_received()
    bob_socket.get_received()

    game = room_manager.rooms[room_id].game
    assert game is not None
    wild = Card(id="event-wild", color="black", value="wild")
    support_card = Card(id="event-support", color="green", value="5")
    game.hands["player-alice"] = [wild, support_card]

    host_socket.emit(
        events.GAME_PLAY,
        {
            "room": room_id,
            "player_id": "player-alice",
            "card_id": wild.id,
            "chosen_color": "blue",
        },
    )

    assert game.discard_pile[-1].color == "blue"
    assert game.pending_uno_player_id == "player-alice"

    host_socket.emit(events.GAME_UNO, {"room": room_id, "player_id": "player-alice"})

    assert game.pending_uno_player_id is None
    assert game.uno_called["player-alice"] is True
    assert host_socket.is_connected()
    assert bob_socket.is_connected()
