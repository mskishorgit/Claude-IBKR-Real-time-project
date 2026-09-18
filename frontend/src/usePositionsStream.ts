import { useEffect, useRef, useState } from "react";
import type { OptionPositionData, PositionsServerMessage, StopTargetAlertMessage } from "./types";
import type { SocketState } from "./useBackendSocket";

const WS_URL = import.meta.env.VITE_BACKEND_POSITIONS_WS_URL ?? "ws://localhost:8000/ws/positions";

const RECONNECT_DELAY_MS = 3000;
const MAX_ALERTS = 20;

/** Live P/L for open option positions, plus stop/target alerts — a
 * separate connection from useOptionsChainStream so a position keeps
 * updating regardless of what's being browsed in the chain. */
export function usePositionsStream() {
  const [socketState, setSocketState] = useState<SocketState>("connecting");
  const [positionsById, setPositionsById] = useState<Record<string, OptionPositionData>>({});
  const [alerts, setAlerts] = useState<StopTargetAlertMessage[]>([]); // newest first

  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    let ws: WebSocket | null = null;

    function connect() {
      if (cancelled) return;
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        if (cancelled) return;
        setSocketState("open");
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        let message: PositionsServerMessage;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        switch (message.type) {
          case "positions_snapshot": {
            const byId: Record<string, OptionPositionData> = {};
            for (const position of message.positions) byId[position.id] = position;
            setPositionsById(byId);
            break;
          }
          case "position_update": {
            const { type: _type, ...position } = message;
            setPositionsById((prev) => ({ ...prev, [position.id]: position }));
            break;
          }
          case "stop_target_alert": {
            const { type: _type, level: _level, ...position } = message;
            setPositionsById((prev) => ({ ...prev, [position.id]: position }));
            setAlerts((prev) => [message, ...prev].slice(0, MAX_ALERTS));
            break;
          }
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setSocketState("reconnecting");
        reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
      };

      ws.onerror = () => {
        ws?.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      ws?.close();
    };
  }, []);

  function dismissAlert(index: number) {
    setAlerts((prev) => prev.filter((_, i) => i !== index));
  }

  const positions = Object.values(positionsById).sort((a, b) => b.entry_time.localeCompare(a.entry_time));

  return { socketState, positions, alerts, dismissAlert };
}
