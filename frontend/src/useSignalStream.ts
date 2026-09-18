import { useEffect, useRef, useState } from "react";
import type { SignalMessage } from "./types";
import type { SocketState } from "./useBackendSocket";

const WS_URL = import.meta.env.VITE_BACKEND_SIGNALS_WS_URL ?? "ws://localhost:8000/ws/signals";

const MAX_SIGNALS = 200;
const RECONNECT_DELAY_MS = 3000;

/** Connects to the backend's dedicated /ws/signals channel — separate from
 * useBackendSocket's /ws/bars connection, matching the backend's split. */
export function useSignalStream() {
  const [socketState, setSocketState] = useState<SocketState>("connecting");
  const [signals, setSignals] = useState<SignalMessage[]>([]); // newest first

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
        let message: SignalMessage;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        if (message.type !== "signal") return;
        setSignals((prev) => [message, ...prev].slice(0, MAX_SIGNALS));
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

  return { socketState, signals };
}
