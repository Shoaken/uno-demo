export interface Player {
  id: string;
  name: string;
}

export interface RoomSnapshot {
  players: Player[];
  host_id: string;
  ready: Record<string, boolean>;
  connected: Record<string, boolean>;
}

export interface Card {
  id: string;
  color: string;
  value: string;
}

export interface GameState {
  hands: Record<string, Card[]>;
  top_card: Card;
  current_player_id: string;
  direction: number;
  allow_immediate_play_after_draw: boolean;
}

export interface SessionMeta {
  player_id: string;
  reconnect_token: string;
}
