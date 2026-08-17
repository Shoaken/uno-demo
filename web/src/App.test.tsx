// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { createRoom, getRoomSnapshot, leaveRoom } from "./lib/api";
import {
  EVENT_GAME_DRAW,
  EVENT_GAME_OVER,
  EVENT_GAME_NOTIFY,
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
  cleanup();
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

  fireEvent.change(screen.getByPlaceholderText("e.g. room-1"), {
    target: { value: roomId },
  });
  fireEvent.change(screen.getByPlaceholderText("e.g. alice"), {
    target: { value: playerName },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create room" }));
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

    expect(screen.getByText(/Room: room-7/)).toBeTruthy();

    socketHarness.handlers.get(EVENT_SESSION_INFO)?.({
      player_id: "p-1",
      reconnect_token: "rt-2",
    });

    await waitFor(() => {
      expect(screen.getByText(/reconnect token: rt-2/)).toBeTruthy();
    });

    socketHarness.handlers.get("disconnect")?.();

    await waitFor(() => {
      expect(screen.getByText("Session recovery failed. Please create or join a room again.")).toBeTruthy();
    });
    expect(screen.getByRole("button", { name: "Create room" })).toBeTruthy();
  });

  it("matches the backend lobby and game socket contract", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);

    await waitFor(() => {
      expect(screen.getByText("Room lobby")).toBeTruthy();
    });
    expect(screen.getByText("Alice", { selector: "strong" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Ready" }));

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
      expect(screen.getByText("Game in progress")).toBeTruthy();
    });
    expect(screen.getByText("YELLOW 2")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Draw" }));
    fireEvent.click(screen.getByRole("button", { name: "UNO" }));
    fireEvent.click(screen.getByRole("button", { name: "RED 5 Play card" }));

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

    expect(screen.getByText("The current reconnect token is saved locally, so no manual input is needed when reconnecting.")).toBeTruthy();
  });

  it("clears the stored session when leaving the room", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Leave room" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "Leave room" }));

    await waitFor(() => {
      expect(leaveRoomMock).toHaveBeenCalledWith("room-1", "p-1");
    });

    expect(localStorage.getItem("uno-demo-session")).toBeNull();
    expect(screen.getByRole("button", { name: "Create room" })).toBeTruthy();
  });

  it("shows game over message and disables game actions", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);
    socketHarness.handlers.get(EVENT_GAME_STATE)?.(gameState);

    await waitFor(() => {
      expect(screen.getByText("Game in progress")).toBeTruthy();
    });

    socketHarness.handlers.get(EVENT_GAME_OVER)?.({
      reason: "won",
      winner: "p-1",
    });

    await waitFor(() => {
      expect(screen.getByText("Alice wins. Game over.")).toBeTruthy();
    });

    expect(screen.getByRole("button", { name: "Draw" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "UNO" }).hasAttribute("disabled")).toBe(true);
  });

  it("shows UNO tag next to player after UNO broadcast", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);
    socketHarness.handlers.get(EVENT_GAME_STATE)?.(gameState);

    await waitFor(() => {
      expect(screen.getByText("Game in progress")).toBeTruthy();
    });

    socketHarness.handlers.get(EVENT_GAME_NOTIFY)?.({
      type: "info",
      code: "uno_called",
      player_id: "p-2",
      message: "Bob called UNO.",
    });

    await waitFor(() => {
      expect(screen.getByText("UNO!")).toBeTruthy();
    });
  });

  it("clears stale UNO status when the player leaves the one-card state", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);
    socketHarness.handlers.get(EVENT_GAME_STATE)?.(gameState);

    await waitFor(() => {
      expect(screen.getByText("Game in progress")).toBeTruthy();
    });

    socketHarness.handlers.get(EVENT_GAME_NOTIFY)?.({
      type: "info",
      code: "uno_called",
      player_id: "p-2",
      message: "Bob called UNO.",
    });

    await waitFor(() => {
      expect(screen.getByText("UNO!")).toBeTruthy();
    });

    socketHarness.handlers.get(EVENT_GAME_STATE)?.({
      ...gameState,
      hands: {
        ...gameState.hands,
        "p-2": [
          { id: "c-1", color: "red", value: "5" },
          { id: "c-2", color: "blue", value: "7" },
        ],
      },
    });

    await waitFor(() => {
      expect(screen.queryByText("UNO!")).toBeNull();
    });

    socketHarness.handlers.get(EVENT_GAME_NOTIFY)?.({
      type: "info",
      code: "uno_pending",
      player_id: "p-2",
      message: "Bob has 1 card left and should call UNO.",
    });

    await waitFor(() => {
      expect(screen.getByText("UNO?")).toBeTruthy();
    });
  });

  it("supports local hand reordering action", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);
    socketHarness.handlers.get(EVENT_GAME_STATE)?.({
      ...gameState,
      hands: {
        ...gameState.hands,
        "p-1": [
          { id: "c-1", color: "red", value: "5" },
          { id: "c-3", color: "blue", value: "1" },
        ],
      },
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Shuffle hand" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "Shuffle hand" }));
    expect(screen.getByText("Shuffling only reorders the local display, not the server-side card order.")).toBeTruthy();
  });

  it("shows last player remaining message when opponent leaves", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);
    socketHarness.handlers.get(EVENT_GAME_STATE)?.(gameState);

    await waitFor(() => {
      expect(screen.getByText("Game in progress")).toBeTruthy();
    });

    socketHarness.handlers.get(EVENT_GAME_OVER)?.({
      reason: "last_player_remaining",
      winner: "p-1",
    });

    await waitFor(() => {
      expect(screen.getByText("The opponent left, so the game ended and you were awarded the win.")).toBeTruthy();
    });
  });

  it("exits in-game without calling leave api", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_ROOM)?.(hostRoomSnapshot);
    socketHarness.handlers.get(EVENT_GAME_STATE)?.(gameState);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Exit game" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "Exit game" }));

    expect(leaveRoomMock).not.toHaveBeenCalled();
    expect(localStorage.getItem("uno-demo-session")).toBeNull();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Create room" })).toBeTruthy();
    });
  });

  it("resets stale session on invalid reconnect token notify", async () => {
    bootstrapSession();

    await waitFor(() => {
      expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1);
    });

    socketHarness.handlers.get(EVENT_GAME_NOTIFY)?.({
      type: "error",
      message: "invalid reconnect token",
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Create room" })).toBeTruthy();
    });
  });
});
