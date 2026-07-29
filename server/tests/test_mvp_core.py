from pathlib import Path
import sys

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from core.uno import Game, GameOverReason, Player
from lib import events
from lib.state import RoomManager


def _make_players(count: int):
    return [Player(id=f"player-p{i}", name=f"p{i}") for i in range(count)]


def test_game_deals_seven_cards_and_exposes_turn_state():
    game = Game(room="r1", players=_make_players(2), hand_size=7, seed=123)

    state = game.get_state()

    assert len(state["hands"]) == 2
    assert all(len(cards) == 7 for cards in state["hands"].values())
    assert state["current_player_id"] == "player-p0"
    assert state["direction"] == 1
    assert state["top_card"]["color"] in {"red", "blue", "green", "yellow"}


def test_only_matching_color_or_number_can_be_played():
    game = Game(room="r1", players=_make_players(2), hand_size=1, seed=1)

    current_player = game.get_state()["current_player_id"]
    hand = game.hands[current_player]
    top = game.discard_pile[-1]

    # Force a non-matching card in current hand for deterministic validation.
    hand[0] = next(
        card
        for card in game._draw_pile
        if card.color != top.color and card.value != top.value
    )

    try:
        game.play(current_player, hand[0].id)
        assert False, "expected ValueError for invalid play"
    except ValueError as ex:
        assert "does not match" in str(ex)


def test_draw_advances_turn_when_drawn_card_not_playable():
    game = Game(room="r1", players=_make_players(2), hand_size=1, seed=1)

    p0 = game.get_state()["current_player_id"]
    p1 = "player-p1"

    top = game.discard_pile[-1]
    # Ensure next draw is not playable, so turn should advance.
    game._draw_pile.append(
        next(
            card
            for card in game._draw_pile
            if card.color != top.color and card.value != top.value
        )
    )

    draw_result = game.draw(p0)

    assert draw_result["can_play_immediately"] is False
    assert game.get_state()["current_player_id"] == p1


def test_winner_triggers_game_over_payload():
    game = Game(room="r1", players=_make_players(2), hand_size=1, seed=2)
    current_player = game.get_state()["current_player_id"]
    top = game.discard_pile[-1]

    winning_card = next(
        card
        for card in game.hands[current_player]
        if card.color == top.color or card.value == top.value
    )

    game_over = game.play(current_player, winning_card.id)

    assert game_over == {"reason": GameOverReason.WON.value, "winner": current_player}


def test_room_flow_create_join_ready_host_start_and_state_broadcast():
    manager = RoomManager()

    create_events = manager.create_room("room-a", "alice")
    assert create_events[0]["event"] == events.GAME_ROOM

    join_events = manager.join_room("room-a", "bob")
    assert join_events[0]["data"]["host_id"] == "player-alice"

    manager.set_ready("room-a", "player-alice", True)
    manager.set_ready("room-a", "player-bob", True)

    start_events = manager.start_game("room-a", "player-alice", hand_size=7, seed=42)
    assert [evt["event"] for evt in start_events] == [events.GAME_START, events.GAME_STATE]


def test_only_host_can_start_and_everyone_must_be_ready():
    manager = RoomManager()
    manager.create_room("room-b", "alice")
    manager.join_room("room-b", "bob")

    manager.set_ready("room-b", "player-alice", True)

    try:
        manager.start_game("room-b", "player-bob")
        assert False, "expected non-host start to fail"
    except ValueError as ex:
        assert "only host" in str(ex)

    try:
        manager.start_game("room-b", "player-alice")
        assert False, "expected missing ready to fail"
    except ValueError as ex:
        assert "must be ready" in str(ex)
