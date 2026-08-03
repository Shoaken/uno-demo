from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Player:
    id: str
    name: str


@dataclass(frozen=True)
class Card:
    id: str
    color: str
    value: str

    def is_black(self) -> bool:
        return self.color == "black"

    def is_wild(self) -> bool:
        return self.value == "wild"

    def is_wild_draw_four(self) -> bool:
        return self.value == "draw-four"

    def is_skip(self) -> bool:
        return self.value == "skip"

    def is_reverse(self) -> bool:
        return self.value == "reverse"

    def is_draw_two(self) -> bool:
        return self.value == "draw-two"


class GameOverReason(str, Enum):
    WON = "won"


class Game:
    MIN_PLAYERS = 2
    MAX_PLAYERS = 10
    COLORS = ["red", "blue", "green", "yellow"]
    ACTION_CARDS = ["skip", "reverse", "draw-two"]
    WILD_CARDS = ["wild", "draw-four"]

    def __init__(
        self,
        room: str,
        players: List[Player],
        hand_size: int = 7,
        allow_immediate_play_after_draw: bool = True,
        seed: Optional[int] = None,
    ):
        if len(players) < self.MIN_PLAYERS:
            raise ValueError(f"need at least {self.MIN_PLAYERS} players")
        if len(players) > self.MAX_PLAYERS:
            raise ValueError(f"max supported players: {self.MAX_PLAYERS}")
        if hand_size <= 0:
            raise ValueError("hand_size must be greater than 0")

        self.room = room
        self.players = players[:]
        self.hand_size = hand_size
        self.allow_immediate_play_after_draw = allow_immediate_play_after_draw
        self.direction = 1
        self.turn_index = 0
        self.player_drew_this_turn = False
        self.last_drawn_card_id: Optional[str] = None
        self.uno_called: Dict[str, bool] = {player.id: False for player in self.players}
        self.pending_uno_player_id: Optional[str] = None

        self._rng = random.Random(seed)
        self._draw_pile = self._build_shuffled_deck()
        self.hands: Dict[str, List[Card]] = {player.id: [] for player in self.players}
        self.discard_pile: List[Card] = []

        self._deal_initial_hands()
        self._initialize_discard_pile()

    def _build_shuffled_deck(self) -> List[Card]:
        deck: List[Card] = []
        card_index = 0

        for color in self.COLORS:
            deck.append(Card(id=f"card-{card_index}", color=color, value="0"))
            card_index += 1
            for value in range(10):
                if value == 0:
                    continue

                for _ in range(2):
                    deck.append(Card(id=f"card-{card_index}", color=color, value=str(value)))
                    card_index += 1

            for action in self.ACTION_CARDS:
                for _ in range(2):
                    deck.append(Card(id=f"card-{card_index}", color=color, value=action))
                    card_index += 1

        for wild in self.WILD_CARDS:
            for _ in range(4):
                deck.append(Card(id=f"card-{card_index}", color="black", value=wild))
                card_index += 1

        self._rng.shuffle(deck)
        return deck

    def _deal_initial_hands(self) -> None:
        for _ in range(self.hand_size):
            for player in self.players:
                self._draw_cards(player.id, 1)

    def _initialize_discard_pile(self) -> None:
        top_card = self._draw_from_deck()
        while top_card.is_black():
            self._draw_pile.insert(0, top_card)
            top_card = self._draw_from_deck()

        self.discard_pile.append(top_card)

    def _draw_from_deck(self) -> Card:
        if not self._draw_pile:
            self._reshuffle_discard_into_draw_pile()
        if not self._draw_pile:
            raise RuntimeError("deck is empty")
        return self._draw_pile.pop()

    def _draw_cards(self, player_id: str, count: int) -> List[Card]:
        drawn_cards = []

        for _ in range(count):
            card = self._draw_from_deck()
            self.hands[player_id].append(card)
            drawn_cards.append(card)

        self.player_drew_this_turn = False
        self.last_drawn_card_id = None
        if len(self.hands[player_id]) != 1:
            self.uno_called[player_id] = False
        return drawn_cards

    def _resolve_pending_uno_penalty(self) -> None:
        pending_player_id = self.pending_uno_player_id
        if pending_player_id is None:
            return

        if self.uno_called.get(pending_player_id, False):
            self.pending_uno_player_id = None
            return

        if len(self.hands[pending_player_id]) == 1:
            self.pending_uno_player_id = None
            self._draw_cards(pending_player_id, 2)

    def _reshuffle_discard_into_draw_pile(self) -> None:
        if len(self.discard_pile) <= 1:
            return

        top_card = self.discard_pile.pop()
        self._draw_pile = self.discard_pile[:]
        self._rng.shuffle(self._draw_pile)
        self.discard_pile = [top_card]

    def _current_player_id(self) -> str:
        return self.players[self.turn_index].id

    def _next_player_index(self) -> int:
        return (self.turn_index + self.direction) % len(self.players)

    def _next_player_id(self) -> str:
        return self.players[self._next_player_index()].id

    def _advance_turn(self, steps: int = 1) -> None:
        self.turn_index = (self.turn_index + (steps * self.direction)) % len(self.players)
        self.player_drew_this_turn = False
        self.last_drawn_card_id = None

    def _apply_uno_penalty_if_needed(self, player_id: str) -> None:
        if len(self.hands[player_id]) == 1 and not self.uno_called[player_id]:
            self.pending_uno_player_id = player_id

    def _validate_uno_call(self, player_id: str) -> None:
        if self.pending_uno_player_id != player_id:
            raise ValueError("UNO can only be called by the player who has one card")
        if len(self.hands[player_id]) != 1:
            raise ValueError("UNO can only be called when the player has exactly one card")

    def _normalize_played_card(self, card: Card, chosen_color: Optional[str]) -> Card:
        if card.is_wild() or card.is_wild_draw_four():
            if chosen_color not in self.COLORS:
                raise ValueError("wild cards require a chosen color")
            return Card(id=card.id, color=chosen_color, value=card.value)

        if chosen_color is not None:
            raise ValueError("chosen color is only allowed for wild cards")

        return card

    def _has_non_wild_matching_card(self, player_id: str, top_card: Card) -> bool:
        return any(
            not card.is_black() and (card.color == top_card.color or card.value == top_card.value)
            for card in self.hands[player_id]
        )

    def _validate_turn(self, player_id: str) -> None:
        if player_id != self._current_player_id():
            raise ValueError(f"not player's turn, expected {self._current_player_id()}")

    def _can_play(self, player_id: str, card: Card, top_card: Card) -> bool:
        if card.is_wild():
            return True

        if card.is_wild_draw_four():
            return not self._has_non_wild_matching_card(player_id, top_card)

        return card.color == top_card.color or card.value == top_card.value

    def get_state(self) -> dict:
        return {
            "hands": {pid: [card.__dict__ for card in cards] for pid, cards in self.hands.items()},
            "top_card": self.discard_pile[-1].__dict__,
            "current_player_id": self._current_player_id(),
            "direction": self.direction,
            "allow_immediate_play_after_draw": self.allow_immediate_play_after_draw,
        }

    def to_snapshot(self) -> dict:
        return {
            "room": self.room,
            "players": [player.__dict__ for player in self.players],
            "hand_size": self.hand_size,
            "allow_immediate_play_after_draw": self.allow_immediate_play_after_draw,
            "direction": self.direction,
            "turn_index": self.turn_index,
            "player_drew_this_turn": self.player_drew_this_turn,
            "last_drawn_card_id": self.last_drawn_card_id,
            "uno_called": self.uno_called,
            "pending_uno_player_id": self.pending_uno_player_id,
            "draw_pile": [card.__dict__ for card in self._draw_pile],
            "hands": {pid: [card.__dict__ for card in cards] for pid, cards in self.hands.items()},
            "discard_pile": [card.__dict__ for card in self.discard_pile],
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict) -> "Game":
        game = cls.__new__(cls)
        game.room = snapshot["room"]
        game.players = [Player(**player) for player in snapshot["players"]]
        game.hand_size = snapshot["hand_size"]
        game.allow_immediate_play_after_draw = snapshot["allow_immediate_play_after_draw"]
        game.direction = snapshot["direction"]
        game.turn_index = snapshot["turn_index"]
        game.player_drew_this_turn = snapshot["player_drew_this_turn"]
        game.last_drawn_card_id = snapshot["last_drawn_card_id"]
        game.uno_called = {pid: bool(value) for pid, value in snapshot["uno_called"].items()}
        game.pending_uno_player_id = snapshot["pending_uno_player_id"]
        game._rng = random.Random()
        game._draw_pile = [Card(**card) for card in snapshot["draw_pile"]]
        game.hands = {
            pid: [Card(**card) for card in cards]
            for pid, cards in snapshot["hands"].items()
        }
        game.discard_pile = [Card(**card) for card in snapshot["discard_pile"]]
        return game

    def draw(self, player_id: str) -> dict:
        self._resolve_pending_uno_penalty()
        self._validate_turn(player_id)
        if self.player_drew_this_turn:
            raise ValueError("player can only draw once per turn")

        card = self._draw_from_deck()
        self.hands[player_id].append(card)
        self.player_drew_this_turn = True
        self.last_drawn_card_id = card.id

        top_card = self.discard_pile[-1]
        playable = self._can_play(player_id, card, top_card)

        if not self.allow_immediate_play_after_draw or not playable:
            self._apply_uno_penalty_if_needed(player_id)
            self._advance_turn()

        return {"card": card.__dict__, "can_play_immediately": playable}

    def call_uno(self, player_id: str) -> dict:
        self._validate_uno_call(player_id)
        self.uno_called[player_id] = True
        self.pending_uno_player_id = None
        return {"player_id": player_id, "called_uno": True}

    def play(self, player_id: str, card_id: str, chosen_color: Optional[str] = None) -> Optional[dict]:
        self._resolve_pending_uno_penalty()
        self._validate_turn(player_id)

        hand = self.hands[player_id]
        card_idx = next((idx for idx, card in enumerate(hand) if card.id == card_id), -1)
        if card_idx < 0:
            raise ValueError("card not found in player's hand")

        card = hand[card_idx]
        top_card = self.discard_pile[-1]

        if self.player_drew_this_turn and self.last_drawn_card_id != card_id:
            raise ValueError("after drawing, only the drawn card can be played")

        if not self._can_play(player_id, card, top_card):
            raise ValueError("card does not match top card by color or number")

        played_card = self._normalize_played_card(card, chosen_color)

        hand.pop(card_idx)
        self.discard_pile.append(played_card)

        if len(hand) == 0:
            self.uno_called[player_id] = False
            self.pending_uno_player_id = None
            return {"reason": GameOverReason.WON.value, "winner": player_id}

        advance_steps = 1
        draw_penalty = 0

        if played_card.is_skip():
            advance_steps = 2
        elif played_card.is_reverse():
            self.direction *= -1
            advance_steps = 0 if len(self.players) == 2 else 1
        elif played_card.is_draw_two():
            draw_penalty = 2
            advance_steps = 2
        elif played_card.is_wild_draw_four():
            draw_penalty = 4
            advance_steps = 2

        if draw_penalty:
            self._draw_cards(self._next_player_id(), draw_penalty)

        self._apply_uno_penalty_if_needed(player_id)
        self._advance_turn(advance_steps)

        return None
