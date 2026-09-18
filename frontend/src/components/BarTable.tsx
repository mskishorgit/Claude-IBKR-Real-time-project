import type { BarMessage } from "../types";

interface Props {
  bars: BarMessage[];
}

export function BarTable({ bars }: Props) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-900 text-slate-400">
          <tr>
            <th className="px-3 py-2">Symbol</th>
            <th className="px-3 py-2">Time</th>
            <th className="px-3 py-2 text-right">Open</th>
            <th className="px-3 py-2 text-right">High</th>
            <th className="px-3 py-2 text-right">Low</th>
            <th className="px-3 py-2 text-right">Close</th>
            <th className="px-3 py-2 text-right">Volume</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {bars.length === 0 && (
            <tr>
              <td colSpan={7} className="px-3 py-6 text-center text-slate-500">
                Waiting for bar data…
              </td>
            </tr>
          )}
          {bars.map((bar, i) => (
            <tr key={`${bar.symbol}-${bar.timestamp}-${i}`} className="text-slate-200">
              <td className="px-3 py-1.5 font-mono font-medium">{bar.symbol}</td>
              <td className="px-3 py-1.5 font-mono text-slate-400">{bar.timestamp}</td>
              <td className="px-3 py-1.5 text-right font-mono">{bar.open.toFixed(2)}</td>
              <td className="px-3 py-1.5 text-right font-mono">{bar.high.toFixed(2)}</td>
              <td className="px-3 py-1.5 text-right font-mono">{bar.low.toFixed(2)}</td>
              <td className="px-3 py-1.5 text-right font-mono">{bar.close.toFixed(2)}</td>
              <td className="px-3 py-1.5 text-right font-mono">{bar.volume}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
