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

// --- Options trading panel --------------------------------------------------

export type OptionRight = "C" | "P";
export type OrderAction = "BUY" | "SELL";
export type OrderKind = "MKT" | "LMT";
export type StopTargetKind = "pct" | "abs";
export type TradingMode = "paper" | "live";

export interface StopTargetConfig {
  kind: StopTargetKind;
  value: number;
}

export interface TradingSafetyStatus {
  trading_mode: TradingMode;
  live_armed: boolean;
  live_at_risk: boolean;
}

export interface OptionQuoteData {
  symbol: string;
  expiry: string;
  strike: number;
  right: OptionRight;
  bid: number | null;
  ask: number | null;
  last: number | null;
  delta: number | null;
  implied_vol: number | null;
  underlying_price: number | null;
  timestamp: string;
}

export interface OptionQuoteMessage extends OptionQuoteData {
  type: "option_quote";
}

export interface OrderPreview {
  preview_id: string;
  symbol: string;
  expiry: string;
  strike: number;
  right: OptionRight;
  action: OrderAction;
  order_type: OrderKind;
  quantity: number;
  limit_price: number | null;
  quote: OptionQuoteData;
  trading_mode: TradingMode;
  created_at: string;
  expires_at: string;
}

export type PositionStatus = "open" | "closing" | "closed";

export interface OptionPositionData {
  id: string;
  symbol: string;
  expiry: string;
  strike: number;
  right: OptionRight;
  direction: "long" | "short";
  quantity: number;
  entry_price: number;
  entry_time: string;
  stop_price: number | null;
  target_price: number | null;
  status: PositionStatus;
  stop_alert_fired: boolean;
  target_alert_fired: boolean;
  last_quote: OptionQuoteData | null;
  unrealized_pnl: number | null;
  close_price: number | null;
  close_time: string | null;
  realized_pnl: number | null;
}

export interface PositionUpdateMessage extends OptionPositionData {
  type: "position_update";
}

export interface StopTargetAlertMessage extends OptionPositionData {
  type: "stop_target_alert";
  level: "stop" | "target";
}

export interface PositionsSnapshotMessage {
  type: "positions_snapshot";
  positions: OptionPositionData[];
}

export type PositionsServerMessage =
  | PositionUpdateMessage
  | StopTargetAlertMessage
  | PositionsSnapshotMessage;

// --- Portfolio & account summary --------------------------------------------

export interface AccountPositionData {
  con_id: number;
  symbol: string;
  sec_type: string;
  exchange: string;
  currency: string;
  quantity: number;
  avg_cost: number;
  market_price: number;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
}

export interface AccountOptionPositionData extends AccountPositionData {
  expiry: string;
  strike: number;
  right: OptionRight;
  delta: number | null;
  implied_vol: number | null;
  underlying_price: number | null;
}

export interface AccountSummaryData {
  account: string;
  net_liquidation: number | null;
  buying_power: number | null;
  total_cash_value: number | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
}

export interface AccountPositionUpdateMessage extends AccountPositionData {
  type: "position_update";
}

export interface AccountOptionPositionUpdateMessage extends AccountOptionPositionData {
  type: "option_position_update";
}

export interface AccountSummaryMessage extends AccountSummaryData {
  type: "account_summary";
}

export interface PortfolioSnapshotMessage {
  type: "portfolio_snapshot";
  positions: AccountPositionData[];
  option_positions: AccountOptionPositionData[];
  summary: AccountSummaryData;
}

export type PortfolioServerMessage =
  | AccountPositionUpdateMessage
  | AccountOptionPositionUpdateMessage
  | AccountSummaryMessage
  | PortfolioSnapshotMessage;

// --- Trading journal ---------------------------------------------------

export type JournalTradeSource = "execution" | "options_panel";

export interface JournalTradeData {
  id: string;
  symbol: string;
  sec_type: string;
  direction: SignalDirection;
  quantity: number;
  entry_time: string;
  entry_price: number;
  exit_time: string;
  exit_price: number;
  realized_pnl: number;
  source: JournalTradeSource;
  expiry: string | null;
  strike: number | null;
  right: OptionRight | null;
  signal_rule: string | null;
  signal_timestamp: string | null;
}

export interface DayPnlData {
  date: string;
  realized_pnl: number;
  trade_count: number;
}

export interface WeeklyPnlData {
  week_start: string;
  realized_pnl: number;
}

export interface MonthStatsData {
  year: number;
  month: number;
  total_pnl: number;
  trade_count: number;
  win_count: number;
  loss_count: number;
  win_rate: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  largest_win: number | null;
  largest_loss: number | null;
  weekly_pnl: WeeklyPnlData[];
}

export interface TradeRecordedMessage extends JournalTradeData {
  type: "trade_recorded";
}

export type JournalServerMessage = TradeRecordedMessage;
