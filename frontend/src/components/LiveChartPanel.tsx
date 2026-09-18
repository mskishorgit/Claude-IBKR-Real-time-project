import { useState } from "react";
import type { BarsBySymbol } from "../useBackendSocket";
import { CandlestickChart } from "./CandlestickChart";
import type { ChartOverlays } from "./CandlestickChart";

interface Props {
  tickers: string[];
  barsBySymbol: BarsBySymbol;
  /** The caller (App) owns selection so a signal alert's click-through can
   * also switch this chart to that ticker, not just the tabs below. */
  selectedSymbol: string | null;
  onSelectSymbol: (symbol: string) => void;
}

const EMPTY_BARS: BarsBySymbol[string] = [];

export function LiveChartPanel({ tickers, barsBySymbol, selectedSymbol, onSelectSymbol }: Props) {
  const [overlays, setOverlays] = useState<Required<ChartOverlays>>({
    vwap: true,
    ema9: true,
    ema20: true,
  });

  // Fall back to the first tracked ticker whenever the caller's chosen
  // symbol isn't (or isn't yet) in the tracked list, without touching the
  // WebSocket connection that's feeding barsBySymbol.
  const selected =
    selectedSymbol && tickers.includes(selectedSymbol) ? selectedSymbol : (tickers[0] ?? null);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-slate-800 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Chart ticker">
          {tickers.length === 0 && <span className="text-xs text-slate-500">No tickers tracked</span>}
          {tickers.map((symbol) => (
            <button
              key={symbol}
              type="button"
              role="tab"
              aria-selected={symbol === selected}
              onClick={() => onSelectSymbol(symbol)}
              className={`rounded px-3 py-1.5 font-mono text-sm transition-colors ${
                symbol === selected
                  ? "bg-emerald-600 text-white"
                  : "bg-slate-900 text-slate-300 hover:bg-slate-800"
              }`}
            >
              {symbol}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-300">
          <OverlayToggle
            label="VWAP"
            color="#f59e0b"
            checked={overlays.vwap}
            onChange={(vwap) => setOverlays((prev) => ({ ...prev, vwap }))}
          />
          <OverlayToggle
            label="EMA 9"
            color="#38bdf8"
            checked={overlays.ema9}
            onChange={(ema9) => setOverlays((prev) => ({ ...prev, ema9 }))}
          />
          <OverlayToggle
            label="EMA 20"
            color="#c084fc"
            checked={overlays.ema20}
            onChange={(ema20) => setOverlays((prev) => ({ ...prev, ema20 }))}
          />
        </div>
      </div>

      {selected ? (
        <CandlestickChart
          key={selected}
          symbol={selected}
          bars={barsBySymbol[selected] ?? EMPTY_BARS}
          overlays={overlays}
        />
      ) : (
        <div className="flex h-[420px] items-center justify-center text-sm text-slate-500">
          Add a ticker above to see its chart.
        </div>
      )}
    </div>
  );
}

interface OverlayToggleProps {
  label: string;
  color: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

function OverlayToggle({ label, color, checked, onChange }: OverlayToggleProps) {
  return (
    <label className="flex cursor-pointer items-center gap-1.5 select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-emerald-500"
      />
      <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </label>
  );
}
