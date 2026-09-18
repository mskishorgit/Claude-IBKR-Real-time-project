import type { JournalTradeData } from "../types";

interface Props {
  date: string;
  trades: JournalTradeData[];
  loading: boolean;
}

function fmt(value: number, digits = 2): string {
  return value.toFixed(digits);
}

function pnlClass(value: number): string {
  return value >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function contractLabel(trade: JournalTradeData): string {
  if (trade.sec_type !== "OPT" || trade.strike === null || trade.expiry === null || trade.right === null) {
    return trade.symbol;
  }
  return `${trade.symbol} ${trade.expiry} ${trade.strike}${trade.right}`;
}

export function JournalDayTrades({ date, trades, loading }: Props) {
  const dayTotal = trades.reduce((sum, t) => sum + t.realized_pnl, 0);

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-slate-800 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-300">{date}</h3>
        <span className={`font-mono text-sm font-semibold ${pnlClass(dayTotal)}`}>
          {dayTotal >= 0 ? "+" : ""}
          {fmt(dayTotal)}
        </span>
      </div>

      {loading && <p className="text-xs text-slate-500">Loading trades…</p>}
      {!loading && trades.length === 0 && <p className="text-xs text-slate-500">No closed trades on this day.</p>}

      {!loading && trades.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-slate-800">
          <table className="w-full text-right text-xs">
            <thead className="bg-slate-900 text-slate-400">
              <tr>
                <th className="px-2 py-1.5 text-left">Contract</th>
                <th className="px-2 py-1.5">Dir</th>
                <th className="px-2 py-1.5">Qty</th>
                <th className="px-2 py-1.5">Entry</th>
                <th className="px-2 py-1.5">Exit</th>
                <th className="px-2 py-1.5">P/L</th>
                <th className="px-2 py-1.5 text-left">Signal</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {trades.map((trade) => (
                <tr key={trade.id}>
                  <td className="px-2 py-1.5 text-left font-mono font-medium text-slate-100">
                    {contractLabel(trade)}
                  </td>
                  <td className="px-2 py-1.5 uppercase text-slate-400">{trade.direction}</td>
                  <td className="px-2 py-1.5 font-mono">{trade.quantity}</td>
                  <td className="px-2 py-1.5 font-mono text-slate-300">
                    {fmt(trade.entry_price)}
                    <div className="text-[10px] text-slate-500">{fmtTime(trade.entry_time)}</div>
                  </td>
                  <td className="px-2 py-1.5 font-mono text-slate-300">
                    {fmt(trade.exit_price)}
                    <div className="text-[10px] text-slate-500">{fmtTime(trade.exit_time)}</div>
                  </td>
                  <td className={`px-2 py-1.5 font-mono ${pnlClass(trade.realized_pnl)}`}>{fmt(trade.realized_pnl)}</td>
                  <td className="px-2 py-1.5 text-left text-slate-400">{trade.signal_rule ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
