import { useEffect, useRef, useState } from "react";
import type { AccountOptionPositionData, AccountPositionData, AccountSummaryData, PortfolioServerMessage } from "./types";
import type { SocketState } from "./useBackendSocket";

const WS_URL = import.meta.env.VITE_BACKEND_PORTFOLIO_WS_URL ?? "ws://localhost:8000/ws/portfolio";

const RECONNECT_DELAY_MS = 3000;

const EMPTY_SUMMARY: AccountSummaryData = {
  account: "",
  net_liquidation: null,
  buying_power: null,
  total_cash_value: null,
  realized_pnl: null,
  unrealized_pnl: null,
};

/** Live IBKR account positions (equity + options, kept separate) and the
 * account summary strip — a dedicated connection from useOptionsChainStream
 * / usePositionsStream, since this reflects the account's true holdings,
 * not just positions opened through this app's own order flow. */
export function usePortfolioStream() {
  const [socketState, setSocketState] = useState<SocketState>("connecting");
  const [positionsById, setPositionsById] = useState<Record<number, AccountPositionData>>({});
  const [optionPositionsById, setOptionPositionsById] = useState<Record<number, AccountOptionPositionData>>({});
  const [summary, setSummary] = useState<AccountSummaryData>(EMPTY_SUMMARY);

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
        let message: PortfolioServerMessage;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        switch (message.type) {
          case "portfolio_snapshot": {
            const equities: Record<number, AccountPositionData> = {};
            for (const position of message.positions) equities[position.con_id] = position;
            const options: Record<number, AccountOptionPositionData> = {};
            for (const position of message.option_positions) options[position.con_id] = position;
            setPositionsById(equities);
            setOptionPositionsById(options);
            setSummary(message.summary);
            break;
          }
          case "position_update": {
            const { type: _type, ...position } = message;
            setPositionsById((prev) => ({ ...prev, [position.con_id]: position }));
            break;
          }
          case "option_position_update": {
            const { type: _type, ...position } = message;
            setOptionPositionsById((prev) => ({ ...prev, [position.con_id]: position }));
            break;
          }
          case "account_summary": {
            const { type: _type, ...rest } = message;
            setSummary(rest);
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

  const positions = Object.values(positionsById).sort((a, b) => a.symbol.localeCompare(b.symbol));
  const optionPositions = Object.values(optionPositionsById).sort((a, b) => a.symbol.localeCompare(b.symbol));

  return { socketState, positions, optionPositions, summary };
}
