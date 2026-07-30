from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.uno import Game, Player
from lib import events


@dataclass
class RoomState:
    room_id: str
    host_id: str
    players: Dict[str, Player] = field(default_factory=dict)
    ready_player_ids: set[str] = field(default_factory=set)
    game: Optional[Game] = None


class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, RoomState] = {}

    def _events_for_room(self, room: RoomState) -> List[dict]:
        return [
            {
                "event": events.GAME_ROOM,
                "data": {
                    "players": [player.__dict__ for player in room.players.values()],
                    "host_id": room.host_id,
                    "ready": {pid: pid in room.ready_player_ids for pid in room.players},
                },
            }
        ]

    def create_room(self, room_id: str, host_name: str) -> List[dict]:
        if room_id in self.rooms:
            raise ValueError("room already exists")

        host = Player(id=f"player-{host_name}", name=host_name)
        room = RoomState(room_id=room_id, host_id=host.id, players={host.id: host})
        self.rooms[room_id] = room
        return self._events_for_room(room)

    def join_room(self, room_id: str, player_name: str) -> List[dict]:
        room = self.rooms.get(room_id)
        if room is None:
            raise ValueError("room does not exist")
        if room.game is not None:
            raise ValueError("game has already started")

        player = Player(id=f"player-{player_name}", name=player_name)
        if player.id in room.players:
            raise ValueError("player name already taken")

        room.players[player.id] = player
        return self._events_for_room(room)

    def set_ready(self, room_id: str, player_id: str, ready: bool) -> List[dict]:
        room = self.rooms.get(room_id)
        if room is None:
            raise ValueError("room does not exist")
        if player_id not in room.players:
            raise ValueError("player not in room")

        if ready:
            room.ready_player_ids.add(player_id)
        else:
            room.ready_player_ids.discard(player_id)

        return self._events_for_room(room)

    def start_game(
        self,
        room_id: str,
        started_by_player_id: str,
        hand_size: int = 7,
        allow_immediate_play_after_draw: bool = True,
        seed: Optional[int] = None,
    ) -> List[dict]:
        room = self.rooms.get(room_id)
        if room is None:
            raise ValueError("room does not exist")
        if room.game is not None:
            raise ValueError("game already started")
        if started_by_player_id != room.host_id:
            raise ValueError("only host can start the game")
        if len(room.players) < Game.MIN_PLAYERS:
            raise ValueError("not enough players")

        everyone_ready = all(pid in room.ready_player_ids for pid in room.players)
        if not everyone_ready:
            raise ValueError("all players must be ready before game starts")

        ordered_players = list(room.players.values())
        room.game = Game(
            room=room_id,
            players=ordered_players,
            hand_size=hand_size,
            allow_immediate_play_after_draw=allow_immediate_play_after_draw,
            seed=seed,
        )

        return [
            {"event": events.GAME_START, "data": {"room": room_id}},
            {"event": events.GAME_STATE, "data": room.game.get_state()},
        ]

    def draw(self, room_id: str, player_id: str) -> List[dict]:
        room = self.rooms.get(room_id)
        if room is None or room.game is None:
            raise ValueError("game does not exist")

        room.game.draw(player_id)
        return [{"event": events.GAME_STATE, "data": room.game.get_state()}]

    def play(self, room_id: str, player_id: str, card_id: str) -> List[dict]:
        room = self.rooms.get(room_id)
        if room is None or room.game is None:
            raise ValueError("game does not exist")

        game_over = room.game.play(player_id, card_id)
        payload = [{"event": events.GAME_STATE, "data": room.game.get_state()}]

        if game_over is not None:
            payload.append({"event": events.GAME_OVER, "data": game_over})

        return payload
