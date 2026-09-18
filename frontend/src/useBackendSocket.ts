import { useEffect, useRef, useState } from "react";
import type { BarMessage, IbkrState, ServerMessage, TickerErrorMessage } from "./types";

const WS_URL = import.meta.env.VITE_BACKEND_WS_URL ?? "ws://localhost:8000/ws/bars";

export type SocketState = "connecting" | "open" | "reconnecting";

const MAX_BARS = 200;
const MAX_BARS_PER_SYMBOL = 500;
const MAX_TICKER_ERRORS = 20;
const RECONNECT_DELAY_MS = 3000;

export type BarsBySymbol = Record<string, BarMessage[]>;

export function useBackendSocket() {
  const [socketState, setSocketState] = useState<SocketState>("connecting");
  const [ibkrState, setIbkrState] = useState<IbkrState>("disconnected");
  const [ibkrError, setIbkrError] = useState<string | null>(null);
  const [tickers, setTickers] = useState<string[]>([]);
  const [bars, setBars] = useState<BarMessage[]>([]);
  const [barsBySymbol, setBarsBySymbol] = useState<BarsBySymbol>({});
  const [tickerErrors, setTickerErrors] = useState<TickerErrorMessage[]>([]);

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
        let message: ServerMessage;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        switch (message.type) {
          case "status":
            setIbkrState(message.state);
            setIbkrError(message.error);
            break;
          case "tickers": {
            const nextTickers = message.tickers;
            setTickers(nextTickers);
            const tickerSet = new Set(nextTickers);
            setBarsBySymbol((prev) => {
              const next: BarsBySymbol = {};
              for (const symbol of Object.keys(prev)) {
                if (tickerSet.has(symbol)) next[symbol] = prev[symbol];
              }
              return next;
            });
            break;
          }
          case "bar":
            setBars((prev) => [message, ...prev].slice(0, MAX_BARS));
            setBarsBySymbol((prev) => {
              const existing = prev[message.symbol] ?? [];
              const last = existing[existing.length - 1];
              let updated: BarMessage[];
              if (last && last.timestamp === message.timestamp) {
                updated = existing.slice(0, -1).concat(message);
              } else {
                updated = existing.concat(message);
                if (updated.length > MAX_BARS_PER_SYMBOL) {
                  updated = updated.slice(updated.length - MAX_BARS_PER_SYMBOL);
                }
              }
              return { ...prev, [message.symbol]: updated };
            });
            break;
          case "ticker_error":
            setTickerErrors((prev) => [message, ...prev].slice(0, MAX_TICKER_ERRORS));
            break;
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setSocketState("reconnecting");
        setIbkrState("disconnected");
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

  return { socketState, ibkrState, ibkrError, tickers, bars, barsBySymbol, tickerErrors };
}
