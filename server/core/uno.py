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


class GameOverReason(str, Enum):
    WON = "won"


class Game:
    MIN_PLAYERS = 2
    MAX_PLAYERS = 10

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

        self._rng = random.Random(seed)
        self._draw_pile = self._build_shuffled_deck()
        self.hands: Dict[str, List[Card]] = {player.id: [] for player in self.players}
        self.discard_pile: List[Card] = []

        self._deal_initial_hands()
        self._initialize_discard_pile()

    def _build_shuffled_deck(self) -> List[Card]:
        colors = ["red", "blue", "green", "yellow"]
        deck: List[Card] = []
        card_index = 0

        for color in colors:
            for value in range(10):
                repeat = 1 if value == 0 else 2
                for _ in range(repeat):
                    deck.append(Card(id=f"card-{card_index}", color=color, value=str(value)))
                    card_index += 1

        self._rng.shuffle(deck)
        return deck

    def _deal_initial_hands(self) -> None:
        for _ in range(self.hand_size):
            for player in self.players:
                self.hands[player.id].append(self._draw_from_deck())

    def _initialize_discard_pile(self) -> None:
        self.discard_pile.append(self._draw_from_deck())

    def _draw_from_deck(self) -> Card:
        if not self._draw_pile:
            self._reshuffle_discard_into_draw_pile()
        if not self._draw_pile:
            raise RuntimeError("deck is empty")
        return self._draw_pile.pop()

    def _reshuffle_discard_into_draw_pile(self) -> None:
        if len(self.discard_pile) <= 1:
            return

        top_card = self.discard_pile.pop()
        self._draw_pile = self.discard_pile[:]
        self._rng.shuffle(self._draw_pile)
        self.discard_pile = [top_card]

    def _current_player_id(self) -> str:
        return self.players[self.turn_index].id

    def _advance_turn(self) -> None:
        self.turn_index = (self.turn_index + self.direction) % len(self.players)
        self.player_drew_this_turn = False

    def _validate_turn(self, player_id: str) -> None:
        if player_id != self._current_player_id():
            raise ValueError(f"not player's turn, expected {self._current_player_id()}")

    def _can_play(self, card: Card, top_card: Card) -> bool:
        return card.color == top_card.color or card.value == top_card.value

    def get_state(self) -> dict:
        return {
            "hands": {pid: [card.__dict__ for card in cards] for pid, cards in self.hands.items()},
            "top_card": self.discard_pile[-1].__dict__,
            "current_player_id": self._current_player_id(),
            "direction": self.direction,
            "allow_immediate_play_after_draw": self.allow_immediate_play_after_draw,
        }

    def draw(self, player_id: str) -> dict:
        self._validate_turn(player_id)
        if self.player_drew_this_turn:
            raise ValueError("player can only draw once per turn")

        card = self._draw_from_deck()
        self.hands[player_id].append(card)
        self.player_drew_this_turn = True

        top_card = self.discard_pile[-1]
        playable = self._can_play(card, top_card)

        if not self.allow_immediate_play_after_draw or not playable:
            self._advance_turn()

        return {"card": card.__dict__, "can_play_immediately": playable}

    def play(self, player_id: str, card_id: str) -> Optional[dict]:
        self._validate_turn(player_id)

        hand = self.hands[player_id]
        card_idx = next((idx for idx, card in enumerate(hand) if card.id == card_id), -1)
        if card_idx < 0:
            raise ValueError("card not found in player's hand")

        card = hand[card_idx]
        top_card = self.discard_pile[-1]

        if not self._can_play(card, top_card):
            raise ValueError("card does not match top card by color or number")

        hand.pop(card_idx)
        self.discard_pile.append(card)

        if len(hand) == 0:
            return {"reason": GameOverReason.WON.value, "winner": player_id}

        self._advance_turn()
        return None
