import { useState } from "react";
import type { FormEvent, MouseEvent } from "react";
import type { SignalMessage } from "../types";
import type { BarsBySymbol } from "../useBackendSocket";
import { findActiveSignal } from "../signalActivity";
import { Sparkline } from "./Sparkline";

const SPARKLINE_BARS = 60;

interface Props {
  tickers: string[];
  barsBySymbol: BarsBySymbol;
  signals: SignalMessage[];
  selectedSymbol: string | null;
  onSelectSymbol: (symbol: string) => void;
  onAdd: (symbol: string) => Promise<void>;
  onRemove: (symbol: string) => Promise<void>;
}

function fmtPrice(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

function fmtPct(value: number | null): string {
  if (value === null) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function WatchlistGrid({
  tickers,
  barsBySymbol,
  signals,
  selectedSymbol,
  onSelectSymbol,
  onAdd,
  onRemove,
}: Props) {
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    const symbol = value.trim();
    if (!symbol) return;
    setPending(true);
    setError(null);
    try {
      await onAdd(symbol);
      setValue("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  async function handleRemove(symbol: string, e: MouseEvent) {
    e.stopPropagation();
    setError(null);
    try {
      await onRemove(symbol);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <form onSubmit={handleAdd} className="flex gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value.toUpperCase())}
          placeholder="Add ticker, e.g. NVDA"
          className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Add
        </button>
      </form>
      {error && <p className="text-xs text-red-400">{error}</p>}

      {tickers.length === 0 ? (
        <p className="text-sm text-slate-500">No tickers tracked yet.</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {tickers.map((symbol) => {
            const bars = barsBySymbol[symbol] ?? [];
            const lastBar = bars[bars.length - 1];
            const lastPrice = lastBar ? lastBar.close : null;
            const dayOpen = bars[0] ? bars[0].open : null;
            const pctChange =
              dayOpen !== null && lastPrice !== null ? ((lastPrice - dayOpen) / dayOpen) * 100 : null;
            const sparklineValues = bars.slice(-SPARKLINE_BARS).map((b) => b.close);
            const active = findActiveSignal(signals, symbol);
            const isSelected = symbol === selectedSymbol;

            const borderClass = active
              ? active.direction === "long"
                ? "border-2 border-emerald-500"
                : "border-2 border-red-500"
              : isSelected
                ? "border border-slate-500"
                : "border border-slate-800 hover:border-slate-700";

            return (
              <div key={symbol} className={`relative rounded-lg bg-slate-900/50 p-3 transition-colors ${borderClass}`}>
                <button
                  type="button"
                  onClick={() => onSelectSymbol(symbol)}
                  className="flex w-full flex-col gap-1.5 text-left"
                >
                  <div className="flex items-center justify-between pr-4">
                    <span className="font-mono text-sm font-semibold text-slate-100">{symbol}</span>
                    {active && (
                      <span
                        className={`rounded px-1 py-0.5 text-[9px] font-bold uppercase ${
                          active.direction === "long"
                            ? "bg-emerald-500/20 text-emerald-400"
                            : "bg-red-500/20 text-red-400"
                        }`}
                      >
                        {active.direction}
                      </span>
                    )}
                  </div>

                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-lg text-slate-100">{fmtPrice(lastPrice)}</span>
                    <span
                      className={`font-mono text-xs ${
                        pctChange === null ? "text-slate-500" : pctChange >= 0 ? "text-emerald-400" : "text-red-400"
                      }`}
                    >
                      {fmtPct(pctChange)}
                    </span>
                  </div>

                  <Sparkline values={sparklineValues} positive={(pctChange ?? 0) >= 0} />
                </button>

                <button
                  type="button"
                  onClick={(e) => handleRemove(symbol, e)}
                  aria-label={`Remove ${symbol} from watchlist`}
                  className="absolute right-1.5 top-1.5 text-slate-500 hover:text-red-400"
                >
                  ×
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
