import type { AccountOptionPositionData, AccountPositionData, AccountSummaryData } from "../types";

interface Props {
  positions: AccountPositionData[];
  optionPositions: AccountOptionPositionData[];
  summary: AccountSummaryData;
}

function fmt(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

function pnlClass(value: number): string {
  return value >= 0 ? "text-emerald-400" : "text-red-400";
}

function pctOfAccount(marketValue: number, netLiq: number | null): string {
  if (!netLiq) return "—";
  return `${((Math.abs(marketValue) / netLiq) * 100).toFixed(1)}%`;
}

export function PortfolioTable({ positions, optionPositions, summary }: Props) {
  if (positions.length === 0 && optionPositions.length === 0) {
    return <p className="text-sm text-slate-500">No open IBKR account positions.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      {positions.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">Equities / ETFs</h3>
          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full text-right text-xs">
              <thead className="bg-slate-900 text-slate-400">
                <tr>
                  <th className="px-2 py-1.5 text-left">Symbol</th>
                  <th className="px-2 py-1.5">Qty</th>
                  <th className="px-2 py-1.5">Avg cost</th>
                  <th className="px-2 py-1.5">Price</th>
                  <th className="px-2 py-1.5">Mkt value</th>
                  <th className="px-2 py-1.5">Unrealized P/L</th>
                  <th className="px-2 py-1.5">% acct</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {positions.map((p) => (
                  <tr key={p.con_id}>
                    <td className="px-2 py-1.5 text-left font-mono font-medium text-slate-100">{p.symbol}</td>
                    <td className="px-2 py-1.5 font-mono">{p.quantity}</td>
                    <td className="px-2 py-1.5 font-mono">{fmt(p.avg_cost)}</td>
                    <td className="px-2 py-1.5 font-mono">{fmt(p.market_price)}</td>
                    <td className="px-2 py-1.5 font-mono">{fmt(p.market_value)}</td>
                    <td className={`px-2 py-1.5 font-mono ${pnlClass(p.unrealized_pnl)}`}>
                      {fmt(p.unrealized_pnl)}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-slate-400">
                      {pctOfAccount(p.market_value, summary.net_liquidation)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {optionPositions.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">Options</h3>
          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full text-right text-xs">
              <thead className="bg-slate-900 text-slate-400">
                <tr>
                  <th className="px-2 py-1.5 text-left">Contract</th>
                  <th className="px-2 py-1.5">Qty</th>
                  <th className="px-2 py-1.5">Avg cost</th>
                  <th className="px-2 py-1.5">Price</th>
                  <th className="px-2 py-1.5">Delta</th>
                  <th className="px-2 py-1.5">IV</th>
                  <th className="px-2 py-1.5">Mkt value</th>
                  <th className="px-2 py-1.5">Unrealized P/L</th>
                  <th className="px-2 py-1.5">% acct</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {optionPositions.map((p) => (
                  <tr key={p.con_id}>
                    <td className="px-2 py-1.5 text-left font-mono font-medium text-slate-100">
                      {p.symbol} {p.expiry} {p.strike}
                      {p.right}
                    </td>
                    <td className="px-2 py-1.5 font-mono">{p.quantity}</td>
                    <td className="px-2 py-1.5 font-mono">{fmt(p.avg_cost)}</td>
                    <td className="px-2 py-1.5 font-mono">{fmt(p.market_price)}</td>
                    <td className="px-2 py-1.5 font-mono text-slate-400">{fmt(p.delta)}</td>
                    <td className="px-2 py-1.5 font-mono text-slate-400">
                      {p.implied_vol ? `${(p.implied_vol * 100).toFixed(0)}%` : "—"}
                    </td>
                    <td className="px-2 py-1.5 font-mono">{fmt(p.market_value)}</td>
                    <td className={`px-2 py-1.5 font-mono ${pnlClass(p.unrealized_pnl)}`}>
                      {fmt(p.unrealized_pnl)}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-slate-400">
                      {pctOfAccount(p.market_value, summary.net_liquidation)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
