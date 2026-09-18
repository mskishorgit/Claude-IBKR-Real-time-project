import { useState } from "react";
import type { FormEvent } from "react";

interface Props {
  tickers: string[];
  onAdd: (symbol: string) => Promise<void>;
  onRemove: (symbol: string) => Promise<void>;
}

export function TickerControls({ tickers, onAdd, onRemove }: Props) {
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

  async function handleRemove(symbol: string) {
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
      <div className="flex flex-wrap gap-2">
        {tickers.map((symbol) => (
          <span
            key={symbol}
            className="inline-flex items-center gap-1 rounded-full bg-slate-800 px-3 py-1 font-mono text-xs text-slate-200"
          >
            {symbol}
            <button
              type="button"
              onClick={() => handleRemove(symbol)}
              className="text-slate-400 hover:text-red-400"
              aria-label={`Remove ${symbol}`}
            >
              ×
            </button>
          </span>
        ))}
        {tickers.length === 0 && <span className="text-xs text-slate-500">No tickers tracked</span>}
      </div>
    </div>
  );
}
