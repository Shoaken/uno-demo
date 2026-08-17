import { io, Socket } from "socket.io-client";
import { GameState, RoomSnapshot, SessionMeta } from "../types";

const BASE_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:5000";

export const EVENT_PLAYER_JOIN = "player::join";
export const EVENT_PLAYER_READY = "player::ready";
export const EVENT_GAME_START = "game::start";
export const EVENT_GAME_DRAW = "game::draw";
export const EVENT_GAME_PLAY = "game::play";
export const EVENT_GAME_UNO = "game::uno";
export const EVENT_GAME_ROOM = "game::room";
export const EVENT_GAME_STATE = "game::state";
export const EVENT_GAME_OVER = "game::over";
export const EVENT_GAME_NOTIFY = "game::notify";
export const EVENT_SESSION_INFO = "session::info";
export const EVENT_PLAYER_LEAVE = "player::leave";

export function createSocket(): Socket {
  return io(BASE_URL, {
    autoConnect: false,
    transports: ["websocket"],
    reconnection: true,
  });
}

export function buildJoinPayload(roomId: string, session: SessionMeta) {
  return {
    room: roomId,
    player_id: session.player_id,
    reconnect_token: session.reconnect_token,
  };
}

export type RoomEventHandler = (snapshot: RoomSnapshot) => void;
export type GameStateHandler = (state: GameState) => void;
export type NotifyHandler = (payload: { type: string; code?: string; message: string }) => void;
