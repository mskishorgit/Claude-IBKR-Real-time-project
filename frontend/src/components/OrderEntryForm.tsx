import { useState } from "react";
import type { OrderAction, OrderKind, StopTargetConfig, StopTargetKind } from "../types";

export interface OrderFormValues {
  action: OrderAction;
  orderType: OrderKind;
  quantity: number;
  limitPrice: number | null;
  stopLoss: StopTargetConfig | null;
  profitTarget: StopTargetConfig | null;
}

interface Props {
  symbol: string;
  expiry: string;
  strike: number;
  right: "C" | "P";
  onSubmit: (values: OrderFormValues) => Promise<void>;
  onCancel: () => void;
  submitting: boolean;
  error: string | null;
}

function StopTargetInput({
  label,
  enabled,
  kind,
  value,
  onChange,
}: {
  label: string;
  enabled: boolean;
  kind: StopTargetKind;
  value: number;
  onChange: (next: { enabled: boolean; kind: StopTargetKind; value: number }) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
      <label className="flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onChange({ enabled: e.target.checked, kind, value })}
          className="accent-emerald-500"
        />
        {label}
      </label>
      {enabled && (
        <>
          <input
            type="number"
            min={0}
            step="any"
            value={value}
            onChange={(e) => onChange({ enabled, kind, value: Number(e.target.value) })}
            className="w-20 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
          />
          <select
            value={kind}
            onChange={(e) => onChange({ enabled, kind: e.target.value as StopTargetKind, value })}
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
          >
            <option value="pct">%</option>
            <option value="abs">$/contract</option>
          </select>
        </>
      )}
    </div>
  );
}

export function OrderEntryForm({ symbol, expiry, strike, right, onSubmit, onCancel, submitting, error }: Props) {
  const [action, setAction] = useState<OrderAction>("BUY");
  const [orderType, setOrderType] = useState<OrderKind>("MKT");
  const [quantity, setQuantity] = useState(1);
  const [limitPrice, setLimitPrice] = useState<number>(0);
  const [stopLoss, setStopLoss] = useState({ enabled: false, kind: "pct" as StopTargetKind, value: 25 });
  const [profitTarget, setProfitTarget] = useState({ enabled: false, kind: "pct" as StopTargetKind, value: 50 });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await onSubmit({
      action,
      orderType,
      quantity,
      limitPrice: orderType === "LMT" ? limitPrice : null,
      stopLoss: stopLoss.enabled ? { kind: stopLoss.kind, value: stopLoss.value } : null,
      profitTarget: profitTarget.enabled ? { kind: profitTarget.kind, value: profitTarget.value } : null,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-lg border border-slate-700 bg-slate-900/50 p-4">
      <div className="font-mono text-sm font-semibold text-slate-100">
        {symbol} {expiry} {strike}
        {right}
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
        <label className="flex items-center gap-1.5">
          Action
          <select
            value={action}
            onChange={(e) => setAction(e.target.value as OrderAction)}
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          >
            <option value="BUY">Buy (open long)</option>
            <option value="SELL">Sell (open short)</option>
          </select>
        </label>

        <label className="flex items-center gap-1.5">
          Order type
          <select
            value={orderType}
            onChange={(e) => setOrderType(e.target.value as OrderKind)}
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          >
            <option value="MKT">Market</option>
            <option value="LMT">Limit</option>
          </select>
        </label>

        {orderType === "LMT" && (
          <label className="flex items-center gap-1.5">
            Limit price
            <input
              type="number"
              min={0}
              step="any"
              value={limitPrice}
              onChange={(e) => setLimitPrice(Number(e.target.value))}
              className="w-24 rounded border border-slate-700 bg-slate-900 px-2 py-1"
            />
          </label>
        )}

        <label className="flex items-center gap-1.5">
          Qty
          <input
            type="number"
            min={1}
            step={1}
            value={quantity}
            onChange={(e) => setQuantity(Math.max(1, Math.round(Number(e.target.value))))}
            className="w-16 rounded border border-slate-700 bg-slate-900 px-2 py-1"
          />
        </label>
      </div>

      <div className="flex flex-col gap-2 border-t border-slate-800 pt-3">
        <p className="text-xs text-slate-500">
          Optional: flags this position when hit — it does not auto-close it (see README).
        </p>
        <StopTargetInput
          label="Stop-loss"
          enabled={stopLoss.enabled}
          kind={stopLoss.kind}
          value={stopLoss.value}
          onChange={setStopLoss}
        />
        <StopTargetInput
          label="Profit target"
          enabled={profitTarget.enabled}
          kind={profitTarget.kind}
          value={profitTarget.value}
          onChange={setProfitTarget}
        />
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {submitting ? "Loading quote…" : "Preview order"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded bg-slate-800 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
