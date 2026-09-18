import type { TradingSafetyStatus } from "../types";

interface Props {
  status: TradingSafetyStatus | null;
}

/** Surfaces the account/mode cross-check added in a hardening pass (see
 * backend/app/options/safety.py's account_mode_mismatch): IBKR_TRADING_MODE
 * is only ever what .env *says* — this is what confirms it against which
 * account TWS/Gateway is actually logged into. All orders are already
 * blocked server-side while this is true; the banner exists so a human
 * notices immediately rather than only discovering it from a failed order. */
export function AccountMismatchBanner({ status }: Props) {
  if (!status || !status.account_mode_mismatch) return null;

  return (
    <div className="flex flex-col gap-1 rounded-lg border-2 border-red-500 bg-red-950 px-4 py-3">
      <div className="text-sm font-bold text-red-200">
        ACCOUNT/MODE MISMATCH — all orders are blocked.
      </div>
      <div className="text-xs text-red-300">
        This backend is configured for <span className="font-mono">{status.trading_mode}</span>{" "}
        trading, but IBKR reports the connected account as{" "}
        <span className="font-mono">{status.account_id}</span>, which doesn't look like it
        matches. Check <span className="font-mono">IBKR_TRADING_MODE</span> in{" "}
        <span className="font-mono">backend/.env</span> against which account TWS/Gateway is
        actually logged into, then restart the backend.
      </div>
    </div>
  );
}
