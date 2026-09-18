import { useState } from "react";
import type { OptionPositionData } from "../types";

interface Props {
  positions: OptionPositionData[];
  onClose: (positionId: string) => Promise<void>;
}

function pnlColor(pnl: number | null): string {
  if (pnl === null) return "text-slate-400";
  return pnl >= 0 ? "text-emerald-400" : "text-red-400";
}

function PositionRow({ position, onClose }: { position: OptionPositionData; onClose: (id: string) => Promise<void> }) {
  const [closing, setClosing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClose() {
    setClosing(true);
    setError(null);
    try {
      await onClose(position.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setClosing(false);
    }
  }

  const pnl = position.status === "open" ? position.unrealized_pnl : position.realized_pnl;
  const alertLevel = position.stop_alert_fired ? "stop" : position.target_alert_fired ? "target" : null;

  return (
    <div
      className={`flex flex-col gap-2 rounded-lg border p-3 ${
        alertLevel === "stop"
          ? "border-red-500 bg-red-950/40"
          : alertLevel === "target"
            ? "border-emerald-500 bg-emerald-950/40"
            : "border-slate-800"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-mono text-sm font-semibold text-slate-100">
          {position.symbol} {position.expiry} {position.strike}
          {position.right}{" "}
          <span className={position.direction === "long" ? "text-emerald-400" : "text-red-400"}>
            {position.direction.toUpperCase()}
          </span>{" "}
          x{position.quantity}
        </div>
        <div className={`font-mono text-sm font-semibold ${pnlColor(pnl)}`}>
          {pnl === null ? "—" : `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`}
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
        <span>entry {position.entry_price.toFixed(2)}</span>
        {position.last_quote && (
          <span>
            now {position.last_quote.bid ?? "—"}/{position.last_quote.ask ?? "—"}
          </span>
        )}
        {position.stop_price !== null && <span>stop {position.stop_price.toFixed(2)}</span>}
        {position.target_price !== null && <span>target {position.target_price.toFixed(2)}</span>}
        <span className="capitalize">{position.status}</span>
      </div>

      {alertLevel && (
        <div className={`text-xs font-semibold ${alertLevel === "stop" ? "text-red-400" : "text-emerald-400"}`}>
          {alertLevel === "stop" ? "Stop level hit" : "Profit target hit"} — flagged only, not auto-closed.
        </div>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}

      {position.status === "open" && (
        <button
          type="button"
          onClick={handleClose}
          disabled={closing}
          className="self-start rounded bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-500 disabled:opacity-50"
        >
          {closing ? "Closing…" : "Close position (market)"}
        </button>
      )}
    </div>
  );
}

export function OpenPositionsPanel({ positions, onClose }: Props) {
  if (positions.length === 0) {
    return <p className="text-sm text-slate-500">No positions yet.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {positions.map((position) => (
        <PositionRow key={position.id} position={position} onClose={onClose} />
      ))}
    </div>
  );
}
