import type { AccountSummaryData } from "../types";

interface Props {
  summary: AccountSummaryData;
}

function fmtMoney(value: number | null): string {
  if (value === null) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pnlColor(value: number | null): string {
  if (value === null) return "text-slate-100";
  return value >= 0 ? "text-emerald-400" : "text-red-400";
}

interface Tile {
  label: string;
  value: number | null;
  colored?: boolean;
}

/** A row of stat tiles rather than a chart — each of these is a single
 * headline number, which is exactly the case dataviz calls "not a chart".
 * Values refresh live as account_summary messages stream in. */
export function AccountSummaryStrip({ summary }: Props) {
  const tiles: Tile[] = [
    { label: "Net liquidation", value: summary.net_liquidation },
    { label: "Buying power", value: summary.buying_power },
    { label: "Day realized P/L", value: summary.realized_pnl, colored: true },
    { label: "Day unrealized P/L", value: summary.unrealized_pnl, colored: true },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {tiles.map((tile) => (
        <div key={tile.label} className="rounded-lg border border-slate-800 p-3">
          <div className="text-xs text-slate-500">{tile.label}</div>
          <div className={`mt-1 font-mono text-lg font-semibold ${tile.colored ? pnlColor(tile.value) : "text-slate-100"}`}>
            {fmtMoney(tile.value)}
          </div>
        </div>
      ))}
    </div>
  );
}
