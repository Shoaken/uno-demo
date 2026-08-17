import React, { useEffect, useMemo, useState } from "react";
import { Socket } from "socket.io-client";
import {
  createRoom,
  getRoomSnapshot,
  joinRoom,
  leaveRoom,
} from "./lib/api";
import {
  buildJoinPayload,
  createSocket,
  EVENT_GAME_OVER,
  EVENT_GAME_NOTIFY,
  EVENT_GAME_ROOM,
  EVENT_GAME_PLAY,
  EVENT_GAME_DRAW,
  EVENT_GAME_START,
  EVENT_GAME_STATE,
  EVENT_GAME_UNO,
  EVENT_PLAYER_JOIN,
  EVENT_PLAYER_READY,
  EVENT_SESSION_INFO,
} from "./lib/socket";
import { Card, GameState, Player, RoomSnapshot, SessionMeta } from "./types";

const STORAGE_KEY = "uno-demo-session";

interface StoredSession extends SessionMeta {
  roomId: string;
  playerName: string;
}

type UnoFlag = "pending" | "called";

function getInitialSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw) as StoredSession;
  } catch {
    return null;
  }
}

function setStoredSession(session: StoredSession | null) {
  if (session) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

function partitionPlayers(players: Player[], currentId?: string) {
  const current = players.find((player) => player.id === currentId);
  const others = players.filter((player) => player.id !== currentId);
  return { current, others };
}

function cardLabel(card: Card) {
  if (card.color === "black") {
    return `${card.value.toUpperCase()}`;
  }
  return `${card.color.toUpperCase()} ${card.value}`;
}

function cardColorClass(card: Card) {
  if (card.color === "black") {
    return "wild";
  }
  return card.color;
}

function cardClassName(card: Card) {
  return `card-tile ${cardColorClass(card)}`;
}

function shuffleIds(ids: string[]) {
  const result = [...ids];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
  }
  return result;
}

function App() {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [connectionState, setConnectionState] = useState("disconnected");
  const [storedSession, setSession] = useState<StoredSession | null>(getInitialSession());
  const [room, setRoom] = useState<RoomSnapshot | null>(null);
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [unoFlags, setUnoFlags] = useState<Record<string, UnoFlag>>({});
  const [handOrder, setHandOrder] = useState<string[] | null>(null);
  const [winnerId, setWinnerId] = useState<string | null>(null);
  const [gameOverReason, setGameOverReason] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [roomIdInput, setRoomIdInput] = useState("");
  const [playerNameInput, setPlayerNameInput] = useState("");
  const [wildSelection, setWildSelection] = useState<Card | null>(null);

  const resetStaleSession = (
    message: string,
    socketRef?: Socket | null,
    skipDisconnect: boolean = false
  ) => {
    setErrorMessage(message);
    setSession(null);
    setRoom(null);
    setGameState(null);
    const activeSocket = socketRef ?? socket;
    if (!skipDisconnect && activeSocket) {
      activeSocket.disconnect();
    }
    setSocket(null);
  };

  const hostId = room?.host_id;
  const isHost = storedSession?.player_id === hostId;
  const currentReady = room?.ready?.[storedSession?.player_id ?? ""] ?? false;
  const canStart = Boolean(
    isHost &&
      room &&
      Object.values(room.ready).length >= 2 &&
      Object.values(room.ready).every(Boolean)
  );

  const playerHand = storedSession?.player_id ? gameState?.hands?.[storedSession.player_id] ?? [] : [];
  const currentPlayerId = storedSession?.player_id ?? "";
  const isUnoAlreadyCalled = Boolean(currentPlayerId && unoFlags[currentPlayerId] === "called");
  const canCallUno = Boolean(storedSession && playerHand.length === 1 && !winnerId && !isUnoAlreadyCalled);
  const playerHandSignature = playerHand.map((card) => card.id).join("|");
  const displayedHand = useMemo(() => {
    if (!handOrder) {
      return playerHand;
    }

    const cardById = new Map(playerHand.map((card) => [card.id, card]));
    const orderedCards = handOrder
      .map((cardId) => cardById.get(cardId))
      .filter((card): card is Card => Boolean(card));
    const remainingCards = playerHand.filter((card) => !handOrder.includes(card.id));
    return [...orderedCards, ...remainingCards];
  }, [handOrder, playerHand]);
  const { current, others } = useMemo(
    () => partitionPlayers(room?.players ?? [], storedSession?.player_id),
    [room, storedSession?.player_id]
  );

  useEffect(() => {
    setStoredSession(storedSession);
  }, [storedSession]);

  useEffect(() => {
    setHandOrder(null);
  }, [playerHandSignature, storedSession?.player_id]);

  useEffect(() => {
    if (!storedSession) {
      setConnectionState("disconnected");
      return;
    }
    if (socket) {
      return;
    }

    const nextSocket = createSocket();
    setSocket(nextSocket);

    nextSocket.on("connect", () => {
      setConnectionState("connected");
      if (storedSession) {
        const payload = buildJoinPayload(storedSession.roomId, storedSession);
        nextSocket.emit(EVENT_PLAYER_JOIN, payload);
      }
    });

    nextSocket.on("disconnect", () => {
      // If a restored session disconnects before room/game state is recovered,
      // treat it as a stale session and return to the entry screen.
      if (storedSession && !room && !gameState) {
        setConnectionState("disconnected");
        resetStaleSession("Session recovery failed. Please create or join a room again.", nextSocket, true);
        return;
      }
      setConnectionState("disconnected");
    });

    nextSocket.on("connect_error", (error) => {
      setConnectionState("disconnected");
      resetStaleSession(`Socket connection failed: ${error.message || error}`, nextSocket);
    });

    nextSocket.on(EVENT_GAME_ROOM, (snapshot: RoomSnapshot) => {
      setRoom(snapshot);
    });

    nextSocket.on(EVENT_GAME_STATE, (payload: any) => {
      if (payload && typeof payload === "object" && "hands" in payload) {
        const nextState = payload as GameState;
        setGameState(nextState);
        const maybeWinner = Object.entries(nextState.hands).find(([, cards]) => cards.length === 0);
        const winner = maybeWinner?.[0] ?? null;
        setWinnerId(winner);
        setGameOverReason(winner ? "won" : null);
        setUnoFlags((previousFlags) => {
          const nextFlags: Record<string, UnoFlag> = {};
          for (const playerId of Object.keys(nextState.hands)) {
            if ((nextState.hands[playerId] ?? []).length === 1 && previousFlags[playerId]) {
              nextFlags[playerId] = previousFlags[playerId];
            }
          }
          return nextFlags;
        });
      } else if (payload && typeof payload === "object" && "players" in payload) {
        setRoom(payload as RoomSnapshot);
        setGameState(null);
        setWinnerId(null);
        setGameOverReason(null);
        setUnoFlags({});
      }
    });

    nextSocket.on(EVENT_GAME_OVER, (payload: { winner?: string; reason?: string }) => {
      const winner = payload?.winner;
      if (winner) {
        setWinnerId(winner);
        setGameOverReason(payload.reason || "won");
      }
    });

    nextSocket.on(EVENT_GAME_NOTIFY, (payload: { type?: string; message: string; code?: string; player_id?: string }) => {
      const message = payload.message || "Server returned an error";
      const normalizedMessage = message.toLowerCase();
      if (
        payload.code === "invalid_reconnect_token" ||
        payload.code === "room_not_found" ||
        normalizedMessage.includes("invalid reconnect token") ||
        normalizedMessage.includes("room does not exist")
      ) {
        resetStaleSession(message, nextSocket);
        return;
      }

      if (payload.type === "info") {
          if (payload.code === "uno_pending" && payload.player_id) {
          setUnoFlags((previousFlags) => ({ ...previousFlags, [payload.player_id as string]: "pending" }));
        }
        if (payload.code === "uno_called" && payload.player_id) {
          setUnoFlags((previousFlags) => ({ ...previousFlags, [payload.player_id as string]: "called" }));
        }
        if (payload.player_id && payload.type === "info" && payload.code !== "uno_pending" && payload.code !== "uno_called") {
          setUnoFlags((previousFlags) => {
            const nextFlags = { ...previousFlags };
            delete nextFlags[payload.player_id as string];
            return nextFlags;
          });
        }
        return;
      }

      setErrorMessage(message);
    });

    nextSocket.on(EVENT_SESSION_INFO, (meta: SessionMeta) => {
      if (storedSession) {
        const nextSession = {
          ...storedSession,
          reconnect_token: meta.reconnect_token,
          player_id: meta.player_id,
        };
        setSession(nextSession);
      }
    });

    nextSocket.connect();

    return () => {
      nextSocket.disconnect();
    };
  }, [storedSession?.roomId, storedSession?.player_id]);

  useEffect(() => {
    if (storedSession && !room && !gameState && connectionState === "connected") {
      getRoomSnapshot(storedSession.roomId).catch(() => {
        // Ignore fallback errors; socket should recover the state.
      });
    }
  }, [storedSession, room, gameState, connectionState]);

  useEffect(() => {
    if (!storedSession || room || gameState || connectionState === "connected" || !socket) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      resetStaleSession("Session recovery failed. Please create or join a room again.", socket, true);
    }, 2000);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [storedSession, room, gameState, connectionState, socket]);

  const clearError = () => setErrorMessage(null);

  const updateSession = (session: StoredSession) => {
    setSession(session);
    setRoom(null);
    setGameState(null);
    setUnoFlags({});
    setHandOrder(null);
    setWinnerId(null);
    setGameOverReason(null);
    setErrorMessage(null);
  };

  const onCreateRoom = async () => {
    clearError();
    if (!roomIdInput || !playerNameInput) {
      setErrorMessage("Please enter a room code and player name.");
      return;
    }

    setIsLoading(true);
    try {
      const result = await createRoom(roomIdInput.trim(), playerNameInput.trim());
      updateSession({
        roomId: roomIdInput.trim(),
        playerName: playerNameInput.trim(),
        player_id: result.meta.player_id,
        reconnect_token: result.meta.reconnect_token,
      });
    } catch (error) {
      setErrorMessage((error as Error).message);
    } finally {
      setIsLoading(false);
    }
  };

  const onJoinRoom = async () => {
    clearError();
    if (!roomIdInput || !playerNameInput) {
      setErrorMessage("Please enter a room code and player name.");
      return;
    }

    setIsLoading(true);
    try {
      const result = await joinRoom(roomIdInput.trim(), playerNameInput.trim());
      updateSession({
        roomId: roomIdInput.trim(),
        playerName: playerNameInput.trim(),
        player_id: result.meta.player_id,
        reconnect_token: result.meta.reconnect_token,
      });
    } catch (error) {
      setErrorMessage((error as Error).message);
    } finally {
      setIsLoading(false);
    }
  };

  const onToggleReady = () => {
    if (!socket || !storedSession) {
      return;
    }
    clearError();
    socket.emit(EVENT_PLAYER_READY, {
      room: storedSession.roomId,
      player_id: storedSession.player_id,
      ready: !currentReady,
    });
  };

  const onStartGame = () => {
    if (!socket || !storedSession) {
      return;
    }
    clearError();
    socket.emit(EVENT_GAME_START, {
      room: storedSession.roomId,
      started_by_player_id: storedSession.player_id,
      hand_size: 7,
      seed: Date.now() + Math.floor(Math.random() * 1000000),
    });
  };

  const onDrawCard = () => {
    if (!socket || !storedSession) {
      return;
    }
    clearError();
    socket.emit(EVENT_GAME_DRAW, {
      room: storedSession.roomId,
      player_id: storedSession.player_id,
    });
  };

  const onPlayCard = (card: Card) => {
    if (!socket || !storedSession || winnerId) {
      return;
    }
    if (card.color === "black") {
      setWildSelection(card);
      return;
    }
    clearError();
    socket.emit(EVENT_GAME_PLAY, {
      room: storedSession.roomId,
      player_id: storedSession.player_id,
      card_id: card.id,
    });
  };

  const onChooseWildColor = (color: string) => {
    if (!socket || !storedSession || !wildSelection) {
      return;
    }
    clearError();
    socket.emit(EVENT_GAME_PLAY, {
      room: storedSession.roomId,
      player_id: storedSession.player_id,
      card_id: wildSelection.id,
      chosen_color: color,
    });
    setWildSelection(null);
  };

  const onCallUno = () => {
    if (!socket || !storedSession || !canCallUno) {
      if (isUnoAlreadyCalled) {
        setErrorMessage("You already called UNO and cannot call it again.");
      }
      return;
    }
    clearError();
    socket.emit(EVENT_GAME_UNO, {
      room: storedSession.roomId,
      player_id: storedSession.player_id,
    });
  };

  const onLeaveRoom = async () => {
    if (!storedSession) {
      return;
    }
    setIsLoading(true);
    clearError();
    try {
      await leaveRoom(storedSession.roomId, storedSession.player_id);
    } catch {
      // ignore leave errors, still clear session locally
    }
    setSession(null);
    setRoom(null);
    setGameState(null);
    setUnoFlags({});
    setHandOrder(null);
    if (socket) {
      socket.disconnect();
      setSocket(null);
    }
    setWinnerId(null);
    setGameOverReason(null);
    setIsLoading(false);
  };

  const onExitGame = () => {
    clearError();
    setSession(null);
    setRoom(null);
    setGameState(null);
    setUnoFlags({});
    setHandOrder(null);
    setWinnerId(null);
    setGameOverReason(null);
    if (socket) {
      socket.disconnect();
      setSocket(null);
    }
  };

  const onShuffleHand = () => {
    if (winnerId || playerHand.length < 2) {
      return;
    }
    setHandOrder(shuffleIds(playerHand.map((card) => card.id)));
  };

  const renderUnoTag = (playerId: string) => {
    const flag = unoFlags[playerId];
    if (!flag) {
      return null;
    }

    return (
      <span className={`status-pill ${flag === "called" ? "status-uno-called" : "status-uno-pending"}`}>
        {flag === "called" ? "UNO!" : "UNO?"}
      </span>
    );
  };

  const renderStatus = () => (
    <div className="action-bar">
      <span className={`status-pill ${connectionState === "connected" ? "status-online" : "status-offline"}`}>
        {connectionState === "connected" ? "Connected" : "Disconnected"}
      </span>
      {storedSession && (
        <span className="small-note">
          Room: {storedSession.roomId} · Player: {storedSession.playerName} · ID: {storedSession.player_id} · reconnect token: {storedSession.reconnect_token}
        </span>
      )}
      {storedSession && connectionState === "disconnected" && (
        <span className="small-note">
          Offline. Refresh the page to automatically restore the session.
        </span>
      )}
    </div>
  );

  const renderEntry = () => (
    <div className="panel">
      <h1 className="heading">UNO Demo</h1>
      <p className="subheading">Create a room or join an existing one and test reconnect behavior in the browser.</p>

      <label className="label">Room code</label>
      <input
        className="input"
        value={roomIdInput}
        onChange={(event) => setRoomIdInput(event.target.value)}
        placeholder="e.g. room-1"
      />
      <label className="label">Player name</label>
      <input
        className="input"
        value={playerNameInput}
        onChange={(event) => setPlayerNameInput(event.target.value)}
        placeholder="e.g. alice"
      />
      <div className="action-bar">
        <button className="button" onClick={onCreateRoom} disabled={isLoading}>
          Create room
        </button>
        <button className="button button-secondary" onClick={onJoinRoom} disabled={isLoading}>
          Join room
        </button>
      </div>
      <p className="small-note">Once you create or join a room, the page connects automatically and restores the session.</p>
    </div>
  );

  const renderLobby = () => (
    <div className="panel">
      <h1 className="heading">Room lobby</h1>
      <p className="subheading">Review players, readiness state, and start the game from the host view.</p>

      <div className="grid">
        <div className="player-row">
          <div>
            <strong>Host</strong>
            <span>{room?.players.find((player) => player.id === room.host_id)?.name || room?.host_id}</span>
          </div>
          <button className="button button-small button-secondary" onClick={onLeaveRoom} disabled={isLoading}>
            Leave room
          </button>
        </div>

        <div className="panel">
          <h2 className="subheading">Players</h2>
          {room?.players.map((player) => (
            <div key={player.id} className="player-row">
              <div>
                <strong>{player.name}</strong>
                <span className="small-note">ID: {player.id}</span>
              </div>
              <div className="action-bar">
                <span className={`status-pill ${room.connected[player.id] ? "status-online" : "status-offline"}`}>
                  {room.connected[player.id] ? "Online" : "Offline"}
                </span>
                <span className={`status-pill ${room.ready[player.id] ? "status-online" : "status-offline"}`}>
                  {room.ready[player.id] ? "Ready" : "Not ready"}
                </span>
              </div>
            </div>
          ))}
        </div>

        <div className="panel">
          <h2 className="subheading">Current player</h2>
          <p className="small-note">{current ? current.name : "Unknown player"}</p>
          <button className="button" onClick={onToggleReady}>
            {currentReady ? "Cancel ready" : "Ready"}
          </button>
          {isHost && (
            <button className="button button-secondary" onClick={onStartGame} disabled={!canStart}>
              Start game
            </button>
          )}
          <div className="small-note">
            {isHost ? "You are the host." : "Waiting for the host to start the game."}
          </div>
          <div className="small-note">
            Refresh after disconnecting and the app will restore the room using the current session.
          </div>
        </div>
      </div>
    </div>
  );

  const renderGameBoard = () => (
    <div className="panel">
      <h1 className="heading">Game in progress</h1>
      <p className="subheading">Play a card, draw, or call UNO according to the rules.</p>

      <div className="grid">
        <div className="player-row">
          <div>
            <strong>Current turn</strong>
            <span>
              {room?.players.find((player) => player.id === gameState?.current_player_id)?.name ||
                gameState?.current_player_id}
            </span>
          </div>
          <div>
            <strong>Your hand</strong>
            <span>{playerHand.length} cards</span>
          </div>
        </div>

        {winnerId && (
          <div className="toast">
            {gameOverReason === "last_player_remaining"
              ? "The opponent left, so the game ended and you were awarded the win."
              : `${room?.players.find((player) => player.id === winnerId)?.name || winnerId} wins. Game over.`}
          </div>
        )}

        <div className="panel">
          <h2 className="subheading">Discard pile</h2>
          <div className={cardClassName(gameState!.top_card)}>
            <strong>{cardLabel(gameState!.top_card)}</strong>
          </div>
        </div>

        <div className="panel">
          <h2 className="subheading">Your hand</h2>
          <div className="card-list">
            {displayedHand.map((card) => (
              <button
                key={card.id}
                type="button"
                className={cardClassName(card)}
                onClick={() => onPlayCard(card)}
                disabled={Boolean(winnerId)}
              >
                <strong>{cardLabel(card)}</strong>
                <span className="small-note">Play card</span>
              </button>
            ))}
          </div>
        </div>

        <div className="panel">
          <h2 className="subheading">Actions</h2>
          <div className="button-group">
            <button className="button" onClick={onDrawCard} disabled={Boolean(winnerId)}>
              Draw
            </button>
            <button className="button button-secondary" onClick={onShuffleHand} disabled={Boolean(winnerId) || playerHand.length < 2}>
              Shuffle hand
            </button>
            <button className="button button-secondary" onClick={onCallUno} disabled={!canCallUno}>
              UNO
            </button>
            <button className="button button-secondary" onClick={onExitGame} disabled={isLoading}>
              Exit game
            </button>
          </div>
          <p className="small-note">UNO is only available when you have exactly 1 card left and can be called only once.</p>
          <p className="small-note">Shuffling only reorders the local display, not the server-side card order.</p>
          <p className="small-note">If you disconnect, refreshing the page will restore the session and return you to the current game.</p>
          <p className="small-note">The current reconnect token is saved locally, so no manual input is needed when reconnecting.</p>
        </div>

        <div className="panel">
          <h2 className="subheading">Other players</h2>
          {others.map((player) => (
            <div key={player.id} className="player-row">
              <div>
                <div className="player-name-line">
                  <strong>{player.name}</strong>
                  {renderUnoTag(player.id)}
                </div>
                <span className="small-note">{gameState?.hands[player.id]?.length ?? 0} cards</span>
              </div>
              <span className={`status-pill ${room?.connected[player.id] ? "status-online" : "status-offline"}`}>
                {room?.connected[player.id] ? "Online" : "Offline"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <div className="app-shell">
      {renderStatus()}
      {errorMessage && <div className="toast">{errorMessage}</div>}
      {!storedSession && renderEntry()}
      {storedSession && room && !gameState && renderLobby()}
      {storedSession && gameState && renderGameBoard()}
      {!storedSession && <div className="small-note">Backend URL: {import.meta.env.VITE_BACKEND_URL || "http://localhost:5000"}</div>}
      {wildSelection && (
        <div className="panel">
          <h2 className="subheading">Choose a wild-card color</h2>
          <div className="button-group">
            {[
              "red",
              "blue",
              "green",
              "yellow",
            ].map((color) => (
              <button
                key={color}
                className={`button wild-color-button ${color}`}
                onClick={() => onChooseWildColor(color)}
              >
                {color}
              </button>
            ))}
          </div>
          <div className="small-note">Select a color for the wild card to complete the move.</div>
        </div>
      )}
    </div>
  );
}

export default App;
