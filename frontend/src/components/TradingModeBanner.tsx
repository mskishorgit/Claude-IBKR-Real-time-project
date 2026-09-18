import type { TradingSafetyStatus } from "../types";

interface Props {
  status: TradingSafetyStatus | null;
  pending: boolean;
  onSetArmed: (armed: boolean) => void;
}

/** Always rendered when connected to a live account — informational (amber)
 * while unarmed, escalating to an unmissable red banner once armed (i.e.
 * once real orders can actually go through). Paper mode renders nothing:
 * paper is the safe default and doesn't need a warning. */
export function TradingModeBanner({ status, pending, onSetArmed }: Props) {
  if (!status || status.trading_mode !== "live") return null;

  if (status.live_armed) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border-2 border-red-500 bg-red-950 px-4 py-3">
        <div className="text-sm font-bold text-red-200">
          LIVE TRADING ARMED — orders submitted here are real and will use real money.
        </div>
        <button
          type="button"
          onClick={() => onSetArmed(false)}
          disabled={pending}
          className="rounded bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-50"
        >
          Disarm live trading
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3">
      <div className="text-sm text-amber-300">
        Connected to a LIVE IBKR account. Orders are blocked until you explicitly arm live trading.
      </div>
      <button
        type="button"
        onClick={() => onSetArmed(true)}
        disabled={pending}
        className="rounded bg-amber-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-amber-500 disabled:opacity-50"
      >
        Arm live trading
      </button>
    </div>
  );
}
