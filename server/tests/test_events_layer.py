from pathlib import Path
import sys

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

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


def _attach_socket_client(name: str, room_id: str):
    client = socketio.test_client(app, flask_test_client=app.test_client())
    client.emit(events.PLAYER_JOIN, {"room": room_id, "name": name})
    return client


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
