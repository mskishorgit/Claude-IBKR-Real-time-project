import type { MonthStatsData } from "../types";

interface Props {
  stats: MonthStatsData;
}

function fmtMoney(value: number | null): string {
  if (value === null) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(0)}%`;
}

interface Tile {
  label: string;
  value: string;
  colorClass?: string;
}

/** Stat tiles for reviewing whether the scalping rules are working this
 * month — same tile pattern as AccountSummaryStrip, reused rather than a
 * new visual language for the same "row of headline numbers" case. */
export function JournalStatsPanel({ stats }: Props) {
  const tiles: Tile[] = [
    { label: "Trades", value: String(stats.trade_count) },
    { label: "Win rate", value: fmtPct(stats.win_rate) },
    { label: "Avg win", value: fmtMoney(stats.avg_win), colorClass: "text-emerald-400" },
    { label: "Avg loss", value: fmtMoney(stats.avg_loss), colorClass: "text-red-400" },
    { label: "Largest win", value: fmtMoney(stats.largest_win), colorClass: "text-emerald-400" },
    { label: "Largest loss", value: fmtMoney(stats.largest_loss), colorClass: "text-red-400" },
  ];

  return (
    <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
      {tiles.map((tile) => (
        <div key={tile.label} className="rounded-lg border border-slate-800 p-3">
          <div className="text-xs text-slate-500">{tile.label}</div>
          <div className={`mt-1 font-mono text-base font-semibold ${tile.colorClass ?? "text-slate-100"}`}>
            {tile.value}
          </div>
        </div>
      ))}
    </div>
  );
}
