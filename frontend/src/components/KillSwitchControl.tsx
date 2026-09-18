import { useState } from "react";
import type { KillSwitchEngageResult, TradingSafetyStatus } from "../types";

interface Props {
  status: TradingSafetyStatus | null;
  pending: boolean;
  lastResult: KillSwitchEngageResult | null;
  onEngage: () => void;
  onReset: () => void;
}

/** Always visible, regardless of trading mode — an emergency stop is worth
 * having in paper mode too (if only to know it works before you need it
 * live). Engaging requires a second confirming click (not a single
 * accidental one) since it immediately cancels every open order at the
 * IBKR level. See backend/app/options/safety.py's KillSwitchService for
 * exactly what it does and doesn't do (it never closes positions). */
export function KillSwitchControl({ status, pending, lastResult, onEngage, onReset }: Props) {
  const [confirming, setConfirming] = useState(false);

  if (!status) return null;

  if (status.kill_switch_engaged) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border-2 border-red-500 bg-red-950 px-4 py-3">
        <div className="text-sm text-red-200">
          <span className="font-bold">KILL SWITCH ENGAGED</span> — all new order submission is
          blocked.
          {lastResult && (
            <span className="block text-xs text-red-300">
              {lastResult.ibkr_reachable
                ? `Cancelled ${lastResult.cancelled_orders} open order(s) at IBKR.`
                : "IBKR was unreachable — nothing could be cancelled remotely. Check TWS/Gateway directly."}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onReset}
          disabled={pending}
          className="rounded bg-slate-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-slate-600 disabled:opacity-50"
        >
          Reset kill switch
        </button>
      </div>
    );
  }

  if (confirming) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border-2 border-red-500 bg-red-950 px-4 py-3">
        <div className="text-sm font-bold text-red-200">
          Cancel every open order and block new orders until manually reset?
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded bg-slate-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-slate-600"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              setConfirming(false);
              onEngage();
            }}
            disabled={pending}
            className="rounded bg-red-600 px-3 py-1.5 text-sm font-bold text-white hover:bg-red-500 disabled:opacity-50"
          >
            Yes, kill everything
          </button>
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      className="flex w-fit items-center gap-2 rounded-lg border border-red-500/50 bg-red-500/10 px-3 py-1.5 text-sm font-semibold text-red-300 hover:bg-red-500/20"
    >
      🛑 Kill switch
    </button>
  );
}
