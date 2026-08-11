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

function cardClassName(card: Card) {
  if (card.color === "black") {
    return "card-tile wild";
  }
  return "card-tile";
}

function App() {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [connectionState, setConnectionState] = useState("disconnected");
  const [storedSession, setSession] = useState<StoredSession | null>(getInitialSession());
  const [room, setRoom] = useState<RoomSnapshot | null>(null);
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [roomIdInput, setRoomIdInput] = useState("");
  const [playerNameInput, setPlayerNameInput] = useState("");
  const [wildSelection, setWildSelection] = useState<Card | null>(null);

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
  const { current, others } = useMemo(
    () => partitionPlayers(room?.players ?? [], storedSession?.player_id),
    [room, storedSession?.player_id]
  );

  useEffect(() => {
    setStoredSession(storedSession);
  }, [storedSession]);

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
      setConnectionState("disconnected");
    });

    nextSocket.on("connect_error", (error) => {
      setConnectionState("disconnected");
      setErrorMessage(`Socket 连接失败：${error.message || error}`);
    });

    nextSocket.on(EVENT_GAME_ROOM, (snapshot: RoomSnapshot) => {
      setRoom(snapshot);
    });

    nextSocket.on(EVENT_GAME_STATE, (payload: any) => {
      if (payload && typeof payload === "object" && "hands" in payload) {
        setGameState(payload as GameState);
      } else if (payload && typeof payload === "object" && "players" in payload) {
        setRoom(payload as RoomSnapshot);
        setGameState(null);
      }
    });

    nextSocket.on(EVENT_GAME_NOTIFY, (payload: { message: string }) => {
      setErrorMessage(payload.message || "服务器返回错误");
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
  }, [storedSession, socket]);

  useEffect(() => {
    if (storedSession && !room && !gameState && connectionState === "connected") {
      getRoomSnapshot(storedSession.roomId).catch(() => {
        // Ignore fallback errors; socket should recover the state.
      });
    }
  }, [storedSession, room, gameState, connectionState]);

  const clearError = () => setErrorMessage(null);

  const updateSession = (session: StoredSession) => {
    setSession(session);
    setRoom(null);
    setGameState(null);
    setErrorMessage(null);
  };

  const onCreateRoom = async () => {
    clearError();
    if (!roomIdInput || !playerNameInput) {
      setErrorMessage("请输入房间编号和玩家名称。");
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
      setErrorMessage("请输入房间编号和玩家名称。");
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
      seed: 42,
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
    if (!socket || !storedSession) {
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
    if (!socket || !storedSession) {
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
    if (socket) {
      socket.disconnect();
      setSocket(null);
    }
    setIsLoading(false);
  };

  const renderStatus = () => (
    <div className="action-bar">
      <span className={`status-pill ${connectionState === "connected" ? "status-online" : "status-offline"}`}>
        {connectionState === "connected" ? "已连接" : "断开连接"}
      </span>
      {storedSession && (
        <span className="small-note">
          房间: {storedSession.roomId} · 玩家: {storedSession.playerName} · ID: {storedSession.player_id} · reconnect token: {storedSession.reconnect_token}
        </span>
      )}
      {storedSession && connectionState === "disconnected" && (
        <span className="small-note">
          已断线。刷新页面后会自动尝试恢复会话。
        </span>
      )}
    </div>
  );

  const renderEntry = () => (
    <div className="panel">
      <h1 className="heading">UNO Demo</h1>
      <p className="subheading">创建一个房间或加入一个已有房间，并在浏览器中演示断线重连。</p>

      <label className="label">房间编号</label>
      <input
        className="input"
        value={roomIdInput}
        onChange={(event) => setRoomIdInput(event.target.value)}
        placeholder="例如 room-1"
      />
      <label className="label">玩家名称</label>
      <input
        className="input"
        value={playerNameInput}
        onChange={(event) => setPlayerNameInput(event.target.value)}
        placeholder="例如 alice"
      />
      <div className="action-bar">
        <button className="button" onClick={onCreateRoom} disabled={isLoading}>
          创建房间
        </button>
        <button className="button button-secondary" onClick={onJoinRoom} disabled={isLoading}>
          加入房间
        </button>
      </div>
      <p className="small-note">创建或加入后，页面会自动连接到后端并恢复会话。</p>
    </div>
  );

  const renderLobby = () => (
    <div className="panel">
      <h1 className="heading">房间大厅</h1>
      <p className="subheading">在这里查看玩家、准备状态，并由房主开始游戏。</p>

      <div className="grid">
        <div className="player-row">
          <div>
            <strong>房主</strong>
            <span>{room?.players.find((player) => player.id === room.host_id)?.name || room?.host_id}</span>
          </div>
          <button className="button button-small button-secondary" onClick={onLeaveRoom} disabled={isLoading}>
            离开房间
          </button>
        </div>

        <div className="panel">
          <h2 className="subheading">玩家列表</h2>
          {room?.players.map((player) => (
            <div key={player.id} className="player-row">
              <div>
                <strong>{player.name}</strong>
                <span className="small-note">ID: {player.id}</span>
              </div>
              <div className="action-bar">
                <span className={`status-pill ${room.connected[player.id] ? "status-online" : "status-offline"}`}>
                  {room.connected[player.id] ? "在线" : "离线"}
                </span>
                <span className={`status-pill ${room.ready[player.id] ? "status-online" : "status-offline"}`}>
                  {room.ready[player.id] ? "已准备" : "未准备"}
                </span>
              </div>
            </div>
          ))}
        </div>

        <div className="panel">
          <h2 className="subheading">当前玩家</h2>
          <p className="small-note">{current ? current.name : "未知玩家"}</p>
          <button className="button" onClick={onToggleReady}>
            {currentReady ? "取消准备" : "准备"}
          </button>
          {isHost && (
            <button className="button button-secondary" onClick={onStartGame} disabled={!canStart}>
              开始游戏
            </button>
          )}
          <div className="small-note">
            {isHost ? "你是房主。" : "等待房主开始游戏。"}
          </div>
          <div className="small-note">
            断线后刷新页面，应用会自动使用当前会话恢复房间状态。
          </div>
        </div>
      </div>
    </div>
  );

  const renderGameBoard = () => (
    <div className="panel">
      <h1 className="heading">游戏进行中</h1>
      <p className="subheading">请按照规则出牌、摸牌或喊UNO。</p>

      <div className="grid">
        <div className="player-row">
          <div>
            <strong>当前回合</strong>
            <span>
              {room?.players.find((player) => player.id === gameState?.current_player_id)?.name ||
                gameState?.current_player_id}
            </span>
          </div>
          <div>
            <strong>你的手牌</strong>
            <span>{playerHand.length} 张</span>
          </div>
        </div>

        <div className="panel">
          <h2 className="subheading">弃牌堆顶牌</h2>
          <div className={cardClassName(gameState!.top_card)}>
            <strong>{cardLabel(gameState!.top_card)}</strong>
          </div>
        </div>

        <div className="panel">
          <h2 className="subheading">你的手牌</h2>
          <div className="card-list">
            {playerHand.map((card) => (
              <button key={card.id} type="button" className={cardClassName(card)} onClick={() => onPlayCard(card)}>
                <strong>{cardLabel(card)}</strong>
                <span className="small-note">点击出牌</span>
              </button>
            ))}
          </div>
        </div>

        <div className="panel">
          <h2 className="subheading">操作</h2>
          <div className="button-group">
            <button className="button" onClick={onDrawCard}>
              摸牌
            </button>
            <button className="button button-secondary" onClick={onCallUno}>
              UNO
            </button>
            <button className="button button-secondary" onClick={onLeaveRoom} disabled={isLoading}>
              退出游戏
            </button>
          </div>
          <p className="small-note">如果你断开连接，刷新页面后会自动恢复会话并尽量返回当前游戏。</p>
          <p className="small-note">当前 reconnect token 已保存于本地，重连时无需手动输入。</p>
        </div>

        <div className="panel">
          <h2 className="subheading">其他玩家手牌数量</h2>
          {others.map((player) => (
            <div key={player.id} className="player-row">
              <div>
                <strong>{player.name}</strong>
                <span className="small-note">{gameState?.hands[player.id]?.length ?? 0} 张</span>
              </div>
              <span className={`status-pill ${room?.connected[player.id] ? "status-online" : "status-offline"}`}>
                {room?.connected[player.id] ? "在线" : "离线"}
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
      {!storedSession && <div className="small-note">后端地址: {import.meta.env.VITE_BACKEND_URL || "http://localhost:5000"}</div>}
      {wildSelection && (
        <div className="panel">
          <h2 className="subheading">选择野牌颜色</h2>
          <div className="button-group">
            {[
              "red",
              "blue",
              "green",
              "yellow",
            ].map((color) => (
              <button
                key={color}
                className="button button-secondary"
                onClick={() => onChooseWildColor(color)}
              >
                {color}
              </button>
            ))}
          </div>
          <div className="small-note">请选择野牌的颜色以完成出牌操作。</div>
        </div>
      )}
    </div>
  );
}

export default App;
