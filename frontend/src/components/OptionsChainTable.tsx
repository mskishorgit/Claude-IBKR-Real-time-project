import type { OptionQuoteData } from "../types";

interface Props {
  strikes: number[];
  quotesByKey: Record<string, OptionQuoteData>;
  symbol: string;
  expiry: string;
  underlyingPrice: number | null;
  onSelectContract: (strike: number, right: "C" | "P") => void;
}

function fmt(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

function quoteFor(
  quotesByKey: Record<string, OptionQuoteData>,
  symbol: string,
  expiry: string,
  strike: number,
  right: "C" | "P",
): OptionQuoteData | undefined {
  return quotesByKey[`${symbol}|${expiry}|${strike}|${right}`];
}

export function OptionsChainTable({
  strikes,
  quotesByKey,
  symbol,
  expiry,
  underlyingPrice,
  onSelectContract,
}: Props) {
  if (strikes.length === 0) {
    return <p className="text-sm text-slate-500">No strikes subscribed yet.</p>;
  }

  const atmStrike =
    underlyingPrice === null
      ? null
      : strikes.reduce((closest, strike) =>
          Math.abs(strike - underlyingPrice) < Math.abs(closest - underlyingPrice) ? strike : closest,
        );

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-right text-xs">
        <thead className="bg-slate-900 text-slate-400">
          <tr>
            <th className="px-2 py-2 text-left" colSpan={4}>
              Call
            </th>
            <th className="px-2 py-2 text-center">Strike</th>
            <th className="px-2 py-2 text-right" colSpan={4}>
              Put
            </th>
          </tr>
          <tr className="text-[11px]">
            <th className="px-2 py-1">Delta</th>
            <th className="px-2 py-1">IV</th>
            <th className="px-2 py-1">Bid</th>
            <th className="px-2 py-1">Ask</th>
            <th className="px-2 py-1 text-center"> </th>
            <th className="px-2 py-1">Bid</th>
            <th className="px-2 py-1">Ask</th>
            <th className="px-2 py-1">Delta</th>
            <th className="px-2 py-1">IV</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {strikes.map((strike) => {
            const call = quoteFor(quotesByKey, symbol, expiry, strike, "C");
            const put = quoteFor(quotesByKey, symbol, expiry, strike, "P");
            const isAtm = strike === atmStrike;
            return (
              <tr key={strike} className={isAtm ? "bg-emerald-500/5" : undefined}>
                <td className="px-2 py-1.5 text-slate-400">{fmt(call?.delta)}</td>
                <td className="px-2 py-1.5 text-slate-400">
                  {call?.implied_vol ? `${(call.implied_vol * 100).toFixed(0)}%` : "—"}
                </td>
                <td className="px-2 py-1.5 font-mono">
                  <button
                    type="button"
                    onClick={() => onSelectContract(strike, "C")}
                    className="rounded px-1.5 py-0.5 text-red-300 hover:bg-red-500/20"
                  >
                    {fmt(call?.bid)}
                  </button>
                </td>
                <td className="px-2 py-1.5 font-mono">
                  <button
                    type="button"
                    onClick={() => onSelectContract(strike, "C")}
                    className="rounded px-1.5 py-0.5 text-emerald-300 hover:bg-emerald-500/20"
                  >
                    {fmt(call?.ask)}
                  </button>
                </td>
                <td
                  className={`px-2 py-1.5 text-center font-mono font-semibold ${
                    isAtm ? "text-emerald-400" : "text-slate-200"
                  }`}
                >
                  {strike}
                </td>
                <td className="px-2 py-1.5 font-mono">
                  <button
                    type="button"
                    onClick={() => onSelectContract(strike, "P")}
                    className="rounded px-1.5 py-0.5 text-red-300 hover:bg-red-500/20"
                  >
                    {fmt(put?.bid)}
                  </button>
                </td>
                <td className="px-2 py-1.5 font-mono">
                  <button
                    type="button"
                    onClick={() => onSelectContract(strike, "P")}
                    className="rounded px-1.5 py-0.5 text-emerald-300 hover:bg-emerald-500/20"
                  >
                    {fmt(put?.ask)}
                  </button>
                </td>
                <td className="px-2 py-1.5 text-slate-400">{fmt(put?.delta)}</td>
                <td className="px-2 py-1.5 text-slate-400">
                  {put?.implied_vol ? `${(put.implied_vol * 100).toFixed(0)}%` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
