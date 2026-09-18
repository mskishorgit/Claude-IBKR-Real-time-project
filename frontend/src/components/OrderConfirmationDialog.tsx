import type { OrderPreview } from "../types";

interface Props {
  preview: OrderPreview;
  onConfirm: () => void;
  onCancel: () => void;
  confirming: boolean;
  error: string | null;
}

/** The one required confirmation step before any order reaches IBKR — per
 * spec, there is no one-click submission path for opening an order (unlike
 * closing one, which is deliberately one-click). Every field here is what
 * was actually captured at preview time, including a fresh quote, so this
 * is what the user is actually agreeing to submit. */
export function OrderConfirmationDialog({ preview, onConfirm, onCancel, confirming, error }: Props) {
  const isLive = preview.trading_mode === "live";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-900 p-5 shadow-xl">
        <h2 className="text-lg font-semibold text-slate-50">Confirm order</h2>

        {isLive && (
          <div className="mt-3 rounded border-2 border-red-500 bg-red-950 px-3 py-2 text-sm font-bold text-red-200">
            This is a LIVE order. Real money is at risk.
          </div>
        )}

        <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
          <dt className="text-slate-400">Contract</dt>
          <dd className="font-mono text-slate-100">
            {preview.symbol} {preview.expiry} {preview.strike}
            {preview.right}
          </dd>

          <dt className="text-slate-400">Action</dt>
          <dd className={preview.action === "BUY" ? "text-emerald-400" : "text-red-400"}>{preview.action}</dd>

          <dt className="text-slate-400">Quantity</dt>
          <dd className="text-slate-100">{preview.quantity} contract(s)</dd>

          <dt className="text-slate-400">Order type</dt>
          <dd className="text-slate-100">
            {preview.order_type === "MKT" ? "Market" : `Limit @ ${preview.limit_price}`}
          </dd>

          <dt className="text-slate-400">Quote at preview</dt>
          <dd className="font-mono text-slate-100">
            bid {preview.quote.bid ?? "—"} / ask {preview.quote.ask ?? "—"}
          </dd>

          <dt className="text-slate-400">Trading mode</dt>
          <dd className={isLive ? "font-bold text-red-400" : "text-emerald-400"}>
            {isLive ? "LIVE" : "Paper"}
          </dd>
        </dl>

        <p className="mt-3 text-xs text-slate-500">
          This preview expires a short time after it was created — if it expires, you'll need to
          re-quote before submitting.
        </p>

        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={confirming}
            className="rounded bg-slate-800 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirming}
            className={`rounded px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 ${
              isLive ? "bg-red-600 hover:bg-red-500" : "bg-emerald-600 hover:bg-emerald-500"
            }`}
          >
            {confirming ? "Submitting…" : isLive ? "Confirm & submit LIVE order" : "Confirm & submit"}
          </button>
        </div>
      </div>
    </div>
  );
}
