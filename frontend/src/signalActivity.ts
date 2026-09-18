import type { SignalDirection, SignalMessage } from "./types";

/** How long a fired signal keeps a watchlist tile highlighted. A signal is
 * a point-in-time event, not a persisting state, so "currently active" is
 * approximated as "fired within this window" rather than something IBKR or
 * the signal engine tracks as an ongoing flag. */
export const SIGNAL_ACTIVE_WINDOW_MS = 5 * 60_000;

export interface ActiveSignal {
  rule: string;
  direction: SignalDirection;
  timestamp: string;
}

/** The most recent still-active signal for `symbol`, or null. `signals` is
 * expected newest-first (matches useSignalStream's shape), so the first
 * match found is the most recent one for that ticker. */
export function findActiveSignal(
  signals: SignalMessage[],
  symbol: string,
  nowMs: number = Date.now(),
): ActiveSignal | null {
  for (const signal of signals) {
    if (signal.ticker !== symbol) continue;
    const age = nowMs - new Date(signal.timestamp).getTime();
    if (age < 0 || age > SIGNAL_ACTIVE_WINDOW_MS) continue;
    return { rule: signal.rule, direction: signal.direction, timestamp: signal.timestamp };
  }
  return null;
}
