export type IbkrState = "disconnected" | "connecting" | "connected" | "reconnecting";

export interface StatusMessage {
  type: "status";
  state: IbkrState;
  error: string | null;
}

export interface TickersMessage {
  type: "tickers";
  tickers: string[];
}

export interface BarMessage {
  type: "bar";
  symbol: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TickerErrorMessage {
  type: "ticker_error";
  symbol: string | null;
  code: number;
  message: string;
}

export type SignalDirection = "long" | "short";

export interface SignalMessage {
  type: "signal";
  ticker: string;
  rule: string;
  direction: SignalDirection;
  price: number;
  volume: number;
  timestamp: string;
  details: Record<string, unknown>;
}

export type ServerMessage = StatusMessage | TickersMessage | BarMessage | TickerErrorMessage;
