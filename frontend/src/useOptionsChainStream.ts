import { useEffect, useRef, useState } from "react";
import type { OptionQuoteData, OptionQuoteMessage } from "./types";
import type { SocketState } from "./useBackendSocket";

const WS_URL = import.meta.env.VITE_BACKEND_OPTIONS_WS_URL ?? "ws://localhost:8000/ws/options";

const RECONNECT_DELAY_MS = 3000;

export function quoteKey(q: { symbol: string; expiry: string; strike: number; right: string }): string {
  return `${q.symbol}|${q.expiry}|${q.strike}|${q.right}`;
}

/** Live quotes for whatever option chain(s) are currently subscribed via
 * the REST subscribe/unsubscribe calls — this connection only streams,
 * it doesn't itself decide what's subscribed. */
export function useOptionsChainStream() {
  const [socketState, setSocketState] = useState<SocketState>("connecting");
  const [quotesByKey, setQuotesByKey] = useState<Record<string, OptionQuoteData>>({});

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
        let message: OptionQuoteMessage;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        if (message.type !== "option_quote") return;
        setQuotesByKey((prev) => ({ ...prev, [quoteKey(message)]: message }));
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

  return { socketState, quotesByKey };
}
