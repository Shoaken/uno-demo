// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { createRoom, getRoomSnapshot, leaveRoom } from "./lib/api";
import {
  EVENT_GAME_DRAW,
  EVENT_GAME_PLAY,
  EVENT_GAME_ROOM,
  EVENT_GAME_STATE,
  EVENT_GAME_UNO,
  EVENT_PLAYER_JOIN,
  EVENT_PLAYER_READY,
  EVENT_SESSION_INFO,
} from "./lib/socket";
import type { GameState, RoomSnapshot } from "./types";

type SocketHandler = (payload?: unknown) => void;

const localStorageShim = (() => {
  const store = new Map<string, string>();

  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(String(key), String(value));
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(String(key));
    }),
    clear: vi.fn(() => {
      store.clear();
    }),
    key: vi.fn((index: number) => Array.from(store.keys())[index] ?? null),
    get length() {
      return store.size;
    },
  };
})();

if (typeof globalThis.localStorage === "undefined") {
  Object.defineProperty(globalThis, "localStorage", {
    value: localStorageShim,
    configurable: true,
  });
}

const socketHarness = vi.hoisted(() => {
  const handlers = new Map<string, SocketHandler>();
  const emitCalls: Array<[string, unknown]> = [];
  const socket: any = {};

  socket.on = vi.fn((event: string, handler: SocketHandler) => {
    handlers.set(event, handler);
    return socket;
  });
  socket.emit = vi.fn((event: string, payload?: unknown) => {
    emitCalls.push([event, payload]);
    return socket;
  });
  socket.connect = vi.fn(() => {
    handlers.get("connect")?.();
    return socket;
  });
  socket.disconnect = vi.fn(() => {
    handlers.get("disconnect")?.();
    return socket;
  });

  return {
    handlers,
    emitCalls,
    socket,
    reset() {
      handlers.clear();
      emitCalls.length = 0;
    },
  };
});

vi.mock("socket.io-client", () => ({
  io: vi.fn(() => socketHarness.socket),
}));

vi.mock("./lib/api", () => ({
  createRoom: vi.fn(),
  getRoomSnapshot: vi.fn(),
  joinRoom: vi.fn(),
  leaveRoom: vi.fn(),
}));

const createRoomMock = vi.mocked(createRoom);
const getRoomSnapshotMock = vi.mocked(getRoomSnapshot);
const leaveRoomMock = vi.mocked(leaveRoom);

const hostRoomSnapshot: RoomSnapshot = {
  players: [
    { id: "p-1", name: "Alice" },
    { id: "p-2", name: "Bob" },
  ],
  host_id: "p-1",
  ready: {
    "p-1": false,
    "p-2": true,
  },
  connected: {
    "p-1": true,
    "p-2": true,
  },
};

const gameState: GameState = {
  hands: {
    "p-1": [{ id: "c-1", color: "red", value: "5" }],
    "p-2": [{ id: "c-2", color: "blue", value: "skip" }],
  },
  top_card: { id: "top-1", color: "yellow", value: "2" },
  current_player_id: "p-1",
  direction: 1,
  allow_immediate_play_after_draw: true,
};

beforeEach(() => {
  socketHarness.reset();
  localStorage.clear();
  vi.clearAllMocks();
  createRoomMock.mockReset();
  getRoomSnapshotMock.mockReset();
  leaveRoomMock.mockReset();
});

function bootstrapSession(roomId = "room-1", playerName = "Alice") {
  createRoomMock.mockResolvedValue({
    events: [],
    meta: {
      player_id: "p-1",
      reconnect_token: "rt-1",
    },
  });
  getRoomSnapshotMock.mockResolvedValue({ room: hostRoomSnapshot });

  render(<App />);

  fireEvent.change(screen.getByPlaceholderText("例如 room-1"), {
    target: { value: roomId },
  });
  fireEvent.change(screen.getByPlaceholderText("例如 alice"), {
    target: { value: playerName },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建房间" }));
}

describe("frontend contract and recovery flow", () => {
  it("creates a session, joins with the reconnect token, and refreshes recovery messaging", async () => {
    bootstrapSession(" room-7 ", " Alice ");

    await waitFor(() => {
      expect(createRoomMock).toHaveBeenCalledWith("room-7", "Alice");
    });

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(socketHarness.emitCalls).toContainEqual([
        EVENT_PLAYER_JOIN,
        {
          room: "room-7",
          player_id: "p-1",
          reconnect_token: "rt-1",
        },
      ]);
    });

    expect(screen.getByText(/房间: room-7/)).toBeTruthy();

    socketHarness.handlers.get(EVENT_SESSION_INFO)?.({
      player_id: "p-1",
      reconnect_token: "rt-2",
    });

    await waitFor(() => {
      expect(screen.getByText(/reconnect token: rt-2/)).toBeTruthy();
    });

    socketHarness.handlers.get("disconnect")?.();

    expect(screen.getByText("已断线。刷新页面后会自动尝试恢复会话。")).toBeTruthy();
  });

  it("matches the backend lobby and game socket contract", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);

    await waitFor(() => {
      expect(screen.getByText("房间大厅")).toBeTruthy();
    });
    expect(screen.getByText("Alice", { selector: "strong" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "准备" }));

    expect(socketHarness.emitCalls).toContainEqual([
      EVENT_PLAYER_READY,
      {
        room: "room-1",
        player_id: "p-1",
        ready: true,
      },
    ]);

    socketHarness.handlers.get(EVENT_GAME_STATE)?.(gameState);

    await waitFor(() => {
      expect(screen.getByText("游戏进行中")).toBeTruthy();
    });
    expect(screen.getByText("YELLOW 2")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "摸牌" }));
    fireEvent.click(screen.getByRole("button", { name: "UNO" }));
    fireEvent.click(screen.getByRole("button", { name: "RED 5 点击出牌" }));

    expect(socketHarness.emitCalls).toContainEqual([
      EVENT_GAME_DRAW,
      {
        room: "room-1",
        player_id: "p-1",
      },
    ]);

    expect(socketHarness.emitCalls).toContainEqual([
      EVENT_GAME_UNO,
      {
        room: "room-1",
        player_id: "p-1",
      },
    ]);

    expect(socketHarness.emitCalls).toContainEqual([
      EVENT_GAME_PLAY,
      {
        room: "room-1",
        player_id: "p-1",
        card_id: "c-1",
      },
    ]);

    expect(screen.getByText("当前 reconnect token 已保存于本地，重连时无需手动输入。")).toBeTruthy();
  });

  it("clears the stored session when leaving the room", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);

    fireEvent.click(screen.getByRole("button", { name: "退出游戏" }));

    await waitFor(() => {
      expect(leaveRoomMock).toHaveBeenCalledWith("room-1", "p-1");
    });

    expect(localStorage.getItem("uno-demo-session")).toBeNull();
    expect(screen.getByRole("button", { name: "创建房间" })).toBeTruthy();
  });
});