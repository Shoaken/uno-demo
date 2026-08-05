import { RoomSnapshot, SessionMeta } from "../types";

const BASE_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:5000";

async function safeJson(response: Response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.error || payload?.message || "服务器请求失败");
  }
  return payload;
}

export async function createRoom(roomId: string, hostName: string): Promise<{ events: any[]; meta: SessionMeta }> {
  const response = await fetch(`${BASE_URL}/api/rooms/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ room_id: roomId, host_name: hostName }),
  });
  return safeJson(response);
}

export async function joinRoom(roomId: string, playerName: string): Promise<{ events: any[]; meta: SessionMeta }> {
  const response = await fetch(`${BASE_URL}/api/rooms/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ room_id: roomId, player_name: playerName }),
  });
  return safeJson(response);
}

export async function getRoomSnapshot(roomId: string): Promise<{ room: RoomSnapshot }> {
  const response = await fetch(`${BASE_URL}/api/rooms/${encodeURIComponent(roomId)}`);
  return safeJson(response);
}

export async function leaveRoom(roomId: string, playerId: string): Promise<void> {
  const response = await fetch(`${BASE_URL}/api/rooms/leave`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ room_id: roomId, player_id: playerId }),
  });
  await safeJson(response);
}
