import { useEffect, useState } from "react";
import { getTradingSafety, setLiveTradingArmed } from "./api";
import type { TradingSafetyStatus } from "./types";

/** Paper-by-default trading-mode gate: `trading_mode` is fixed for the
 * backend process (from IBKR_TRADING_MODE); `live_armed` is the runtime
 * toggle a human must explicitly flip before a *live* order can go
 * through — see backend/app/options/safety.py for what this does and
 * doesn't protect. */
export function useTradingSafety() {
  const [status, setStatus] = useState<TradingSafetyStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getTradingSafety()
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function setArmed(armed: boolean) {
    setPending(true);
    setError(null);
    try {
      const result = await setLiveTradingArmed(armed);
      setStatus(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  return { status, error, pending, setArmed };
}
