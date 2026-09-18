import { useEffect, useRef, useState } from "react";
import type { JournalServerMessage } from "./types";
import type { SocketState } from "./useBackendSocket";

const WS_URL = import.meta.env.VITE_BACKEND_JOURNAL_WS_URL ?? "ws://localhost:8000/ws/journal";

const RECONNECT_DELAY_MS = 3000;

/** Carries no journal data of its own — REST (getJournalCalendar/Day/Stats)
 * stays the source of truth. This just bumps `version` whenever a new
 * round-trip trade lands in the journal DB, so JournalPanel knows to
 * refetch the currently-viewed month/day without polling. */
export function useJournalStream() {
  const [socketState, setSocketState] = useState<SocketState>("connecting");
  const [version, setVersion] = useState(0);

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
        let message: JournalServerMessage;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        if (message.type === "trade_recorded") {
          setVersion((v) => v + 1);
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

  return { socketState, version };
}
