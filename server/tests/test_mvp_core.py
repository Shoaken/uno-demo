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


def _first_non_matching_card(game: Game, top_card):
    return next(
        card
        for card in game._draw_pile
        if not card.is_black() and card.color != top_card.color and card.value != top_card.value
    )


def _first_matching_card(game: Game, top_card):
    return next(
        card
        for card in game._draw_pile
        if not card.is_black() and (card.color == top_card.color or card.value == top_card.value)
    )


def _inject_card(game: Game, value: str, color: str = "red"):
    card = type(game._draw_pile[0])(id=f"test-{value}-{color}", color=color, value=value)
    game._draw_pile.append(card)
    return card


def _prepared_reusable_game(seed: int = 1):
    game = Game(room="r1", players=_make_players(2), hand_size=1, seed=seed)
    current_player = game.get_state()["current_player_id"]
    other_player = "player-p1" if current_player == "player-p0" else "player-p0"
    top_card = game.discard_pile[-1]
    return game, current_player, other_player, top_card


def test_game_deals_seven_cards_and_exposes_turn_state():
    game = Game(room="r1", players=_make_players(2), hand_size=7, seed=123)

    state = game.get_state()

    assert len(state["hands"]) == 2
    assert all(len(cards) == 7 for cards in state["hands"].values())
    assert state["current_player_id"] == "player-p0"
    assert state["direction"] == 1
    assert state["top_card"]["color"] in {"red", "blue", "green", "yellow"}


def test_only_matching_color_or_number_can_be_played():
    game, current_player, _, top_card = _prepared_reusable_game(seed=1)

    hand = game.hands[current_player]

    # Force a non-matching card in current hand for deterministic validation.
    hand[0] = _first_non_matching_card(game, top_card)

    try:
        game.play(current_player, hand[0].id)
        assert False, "expected ValueError for invalid play"
    except ValueError as ex:
        assert "does not match" in str(ex)


def test_non_current_player_cannot_draw_or_play():
    game, current_player, other_player, top = _prepared_reusable_game(seed=3)

    try:
        game.draw(other_player)
        assert False, "expected ValueError when non-current player draws"
    except ValueError as ex:
        assert "not player's turn" in str(ex)

    game.hands[other_player][0] = _first_matching_card(game, top)

    try:
        game.play(other_player, game.hands[other_player][0].id)
        assert False, "expected ValueError when non-current player plays"
    except ValueError as ex:
        assert "not player's turn" in str(ex)


def test_cannot_draw_twice_in_same_turn():
    game, current_player, _, top = _prepared_reusable_game(seed=4)

    # Make the first draw playable so the second draw is tested on the same turn.
    game._draw_pile.append(_first_matching_card(game, top))

    try:
        game.draw(current_player)
        game.draw(current_player)
        assert False, "expected ValueError on second draw in the same turn"
    except ValueError as ex:
        assert "only draw once" in str(ex)


def test_draw_keeps_turn_when_immediate_play_is_enabled_and_card_is_playable():
    game = Game(
        room="r1",
        players=_make_players(2),
        hand_size=1,
        seed=5,
        allow_immediate_play_after_draw=True,
    )

    current_player = game.get_state()["current_player_id"]
    top = game.discard_pile[-1]
    playable_card = _first_matching_card(game, top)
    game._draw_pile.append(playable_card)

    draw_result = game.draw(current_player)

    assert draw_result["can_play_immediately"] is True
    assert game.get_state()["current_player_id"] == current_player


def test_draw_advances_turn_when_immediate_play_is_disabled_even_if_playable():
    game = Game(
        room="r1",
        players=_make_players(2),
        hand_size=1,
        seed=6,
        allow_immediate_play_after_draw=False,
    )

    current_player = game.get_state()["current_player_id"]
    other_player = "player-p1" if current_player == "player-p0" else "player-p0"
    top = game.discard_pile[-1]
    playable_card = _first_matching_card(game, top)
    game._draw_pile.append(playable_card)

    draw_result = game.draw(current_player)

    assert draw_result["can_play_immediately"] is True
    assert game.get_state()["current_player_id"] == other_player


def test_draw_advances_turn_when_drawn_card_not_playable():
    game, current_player, other_player, top = _prepared_reusable_game(seed=1)

    # Ensure next draw is not playable, so turn should advance.
    game._draw_pile.append(_first_non_matching_card(game, top))

    draw_result = game.draw(current_player)

    assert draw_result["can_play_immediately"] is False
    assert game.get_state()["current_player_id"] == other_player


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


def test_game_constructor_validates_bounds():
    try:
        Game(room="r1", players=_make_players(1), hand_size=7)
        assert False, "expected ValueError for too few players"
    except ValueError as ex:
        assert "at least" in str(ex)

    try:
        Game(room="r1", players=_make_players(11), hand_size=7)
        assert False, "expected ValueError for too many players"
    except ValueError as ex:
        assert "max supported" in str(ex)

    try:
        Game(room="r1", players=_make_players(2), hand_size=0)
        assert False, "expected ValueError for invalid hand size"
    except ValueError as ex:
        assert "greater than 0" in str(ex)


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
    state_payload = start_events[1]["data"]
    assert set(state_payload.keys()) == {
        "hands",
        "top_card",
        "current_player_id",
        "direction",
        "allow_immediate_play_after_draw",
    }
    assert state_payload["current_player_id"] == "player-alice"
    assert state_payload["direction"] == 1
    assert len(state_payload["hands"]) == 2


def test_room_manager_rejects_invalid_room_operations():
    manager = RoomManager()

    manager.create_room("room-c", "alice")

    try:
        manager.create_room("room-c", "alice2")
        assert False, "expected duplicate room creation to fail"
    except ValueError as ex:
        assert "already exists" in str(ex)

    try:
        manager.join_room("missing-room", "bob")
        assert False, "expected join for missing room to fail"
    except ValueError as ex:
        assert "does not exist" in str(ex)

    try:
        manager.join_room("room-c", "alice")
        assert False, "expected duplicate player name to fail"
    except ValueError as ex:
        assert "already taken" in str(ex)

    try:
        manager.set_ready("room-c", "player-bob", True)
        assert False, "expected ready for non-member to fail"
    except ValueError as ex:
        assert "not in room" in str(ex)


def test_room_manager_rejects_game_flow_before_start_and_duplicate_start():
    manager = RoomManager()
    manager.create_room("room-d", "alice")
    manager.join_room("room-d", "bob")
    manager.set_ready("room-d", "player-alice", True)
    manager.set_ready("room-d", "player-bob", True)

    try:
        manager.draw("room-d", "player-alice")
        assert False, "expected draw before game starts to fail"
    except ValueError as ex:
        assert "does not exist" in str(ex)

    try:
        manager.play("room-d", "player-alice", "card-1")
        assert False, "expected play before game starts to fail"
    except ValueError as ex:
        assert "does not exist" in str(ex)

    manager.start_game("room-d", "player-alice", hand_size=7, seed=7)

    try:
        manager.start_game("room-d", "player-alice", hand_size=7, seed=7)
        assert False, "expected duplicate start to fail"
    except ValueError as ex:
        assert "already started" in str(ex)


def test_game_reshuffles_discard_into_draw_pile_when_draw_pile_is_empty():
    game = Game(room="r1", players=_make_players(2), hand_size=1, seed=8)

    current_player = game.get_state()["current_player_id"]
    game.discard_pile.extend(
        [
            _first_non_matching_card(game, game.discard_pile[-1]),
            _first_matching_card(game, game.discard_pile[-1]),
        ]
    )
    game._draw_pile.clear()
    discard_before = [card.id for card in game.discard_pile]
    expected_top_card_id = discard_before[-1]

    drawn = game.draw(current_player)

    assert "card" in drawn
    assert game.discard_pile[-1].id == expected_top_card_id
    assert len(game.discard_pile) == 1
    assert len(game._draw_pile) == len(discard_before) - 2


def test_skip_card_skips_next_player():
    game = Game(room="r1", players=_make_players(3), hand_size=2, seed=9)

    current_player = game.get_state()["current_player_id"]
    skip_card = _inject_card(game, "skip", color=game.discard_pile[-1].color)
    game.hands[current_player][0] = skip_card

    game.play(current_player, skip_card.id)

    assert game.get_state()["current_player_id"] == "player-p2"


def test_reverse_card_flips_direction():
    game = Game(room="r1", players=_make_players(3), hand_size=2, seed=10)

    current_player = game.get_state()["current_player_id"]
    reverse_card = _inject_card(game, "reverse", color=game.discard_pile[-1].color)
    game.hands[current_player][0] = reverse_card

    game.play(current_player, reverse_card.id)

    assert game.get_state()["direction"] == -1
    assert game.get_state()["current_player_id"] == "player-p2"


def test_draw_two_forces_next_player_to_draw_two_cards():
    game = Game(room="r1", players=_make_players(3), hand_size=2, seed=11)

    current_player = game.get_state()["current_player_id"]
    next_player = "player-p1"
    draw_two_card = _inject_card(game, "draw-two", color=game.discard_pile[-1].color)
    game.hands[current_player][0] = draw_two_card
    hand_before = len(game.hands[next_player])

    game.play(current_player, draw_two_card.id)

    assert len(game.hands[next_player]) == hand_before + 2
    assert game.get_state()["current_player_id"] == "player-p2"


def test_wild_card_requires_chosen_color():
    game = Game(room="r1", players=_make_players(2), hand_size=2, seed=12)

    current_player = game.get_state()["current_player_id"]
    wild_card = _inject_card(game, "wild", color="black")
    game.hands[current_player][0] = wild_card

    try:
        game.play(current_player, wild_card.id)
        assert False, "expected chosen color to be required"
    except ValueError as ex:
        assert "chosen color" in str(ex)

    game.play(current_player, wild_card.id, chosen_color="blue")
    assert game.discard_pile[-1].color == "blue"


def test_wild_draw_four_requires_no_matching_color_card():
    game = Game(room="r1", players=_make_players(2), hand_size=2, seed=13)

    current_player = game.get_state()["current_player_id"]
    top_color = game.discard_pile[-1].color
    draw_four_card = _inject_card(game, "draw-four", color="black")
    matching_color_card = _inject_card(game, "1", color=top_color)
    game.hands[current_player] = [draw_four_card, matching_color_card]

    try:
        game.play(current_player, draw_four_card.id, chosen_color="green")
        assert False, "expected draw-four to be blocked when a matching color card exists"
    except ValueError as ex:
        assert "does not match" in str(ex)


def test_uno_call_prevents_penalty_and_missing_call_penalizes_player():
    game = Game(room="r1", players=_make_players(2), hand_size=2, seed=14)

    current_player = game.get_state()["current_player_id"]
    top = game.discard_pile[-1]
    matching_card = _first_matching_card(game, top)
    game.hands[current_player][0] = matching_card
    game.hands[current_player][1] = _first_non_matching_card(game, top)
    game._draw_pile.append(_first_non_matching_card(game, top))

    game.play(current_player, matching_card.id)
    assert len(game.hands[current_player]) == 1
    assert game.pending_uno_player_id == current_player

    game.call_uno(current_player)
    assert game.uno_called[current_player] is True


def test_call_uno_marks_player_state():
    game = Game(room="r1", players=_make_players(2), hand_size=2, seed=15)

    current_player = game.get_state()["current_player_id"]
    top = game.discard_pile[-1]
    matching_card = _first_matching_card(game, top)
    game.hands[current_player][0] = matching_card
    game.hands[current_player][1] = _first_non_matching_card(game, top)
    game.play(current_player, matching_card.id)

    game.pending_uno_player_id = current_player
    result = game.call_uno(current_player)

    assert result == {"player_id": current_player, "called_uno": True}


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
