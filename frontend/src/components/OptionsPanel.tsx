import { useEffect, useRef, useState } from "react";
import {
  confirmOrder,
  createOrderPreview,
  discardOrderPreview,
  getOptionExpiries,
  subscribeOptionChain,
  unsubscribeOptionChain,
} from "../api";
import type { OptionPositionData, OptionQuoteData, OptionRight, OrderPreview } from "../types";
import { OpenPositionsPanel } from "./OpenPositionsPanel";
import { OptionsChainTable } from "./OptionsChainTable";
import { OrderConfirmationDialog } from "./OrderConfirmationDialog";
import { OrderEntryForm, type OrderFormValues } from "./OrderEntryForm";
import { quoteKey } from "../useOptionsChainStream";

interface Props {
  symbol: string | null;
  quotesByKey: Record<string, OptionQuoteData>;
  positions: OptionPositionData[];
  onClosePosition: (positionId: string) => Promise<void>;
}

export function OptionsPanel({ symbol, quotesByKey, positions, onClosePosition }: Props) {
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  const [strikes, setStrikes] = useState<number[]>([]);
  const [seedQuotes, setSeedQuotes] = useState<Record<string, OptionQuoteData>>({});
  const [chainError, setChainError] = useState<string | null>(null);

  const [selectedContract, setSelectedContract] = useState<{ strike: number; right: OptionRight } | null>(null);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [orderNotice, setOrderNotice] = useState<string | null>(null);

  const subscribedSymbolRef = useRef<string | null>(null);

  // Load near-term (0DTE/weekly) expiries whenever the underlying changes.
  useEffect(() => {
    let cancelled = false;
    setSelectedContract(null);
    setChainError(null);
    if (!symbol) {
      setExpiries([]);
      setSelectedExpiry(null);
      return;
    }
    getOptionExpiries(symbol)
      .then((result) => {
        if (cancelled) return;
        setExpiries(result.expiries);
        setSelectedExpiry(result.expiries[0] ?? null);
      })
      .catch((err) => {
        if (!cancelled) setChainError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  // Subscribe to the chain for the current symbol+expiry; unsubscribe the
  // previous symbol's chain if we just switched underlyings.
  useEffect(() => {
    let cancelled = false;
    const previousSymbol = subscribedSymbolRef.current;
    if (previousSymbol && previousSymbol !== symbol) {
      void unsubscribeOptionChain(previousSymbol);
      subscribedSymbolRef.current = null;
    }
    if (!symbol || !selectedExpiry) {
      setStrikes([]);
      setSeedQuotes({});
      return;
    }
    subscribeOptionChain(symbol, selectedExpiry)
      .then((result) => {
        if (cancelled) return;
        const uniqueStrikes = Array.from(new Set(result.quotes.map((q) => q.strike))).sort((a, b) => a - b);
        setStrikes(uniqueStrikes);
        // Paints the table immediately with the subscribe response's own
        // snapshot, rather than leaving it blank until the first live tick
        // arrives over /ws/options a moment later.
        const seed: Record<string, OptionQuoteData> = {};
        for (const quote of result.quotes) seed[quoteKey(quote)] = quote;
        setSeedQuotes(seed);
        subscribedSymbolRef.current = symbol;
      })
      .catch((err) => {
        if (!cancelled) setChainError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, selectedExpiry]);

  // Unsubscribe on unmount.
  useEffect(() => {
    return () => {
      if (subscribedSymbolRef.current) {
        void unsubscribeOptionChain(subscribedSymbolRef.current);
      }
    };
  }, []);

  async function handlePreview(values: OrderFormValues) {
    if (!symbol || !selectedExpiry || !selectedContract) return;
    setPreviewLoading(true);
    setPreviewError(null);
    setOrderNotice(null);
    try {
      const result = await createOrderPreview({
        symbol,
        expiry: selectedExpiry,
        strike: selectedContract.strike,
        right: selectedContract.right,
        action: values.action,
        orderType: values.orderType,
        quantity: values.quantity,
        limitPrice: values.limitPrice,
        stopLoss: values.stopLoss,
        profitTarget: values.profitTarget,
      });
      setPreview(result);
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleConfirm() {
    if (!preview) return;
    setConfirming(true);
    setConfirmError(null);
    try {
      const result = await confirmOrder(preview.preview_id);
      setOrderNotice(`Order submitted (IBKR order id ${result.order_id}, status ${result.status}).`);
      setPreview(null);
      setSelectedContract(null);
    } catch (err) {
      // Deliberately does not retry — a failure here means the human sees
      // exactly what happened and decides whether to re-quote and try again.
      setConfirmError(err instanceof Error ? err.message : String(err));
    } finally {
      setConfirming(false);
    }
  }

  function handleCancelPreview() {
    if (preview) void discardOrderPreview(preview.preview_id);
    setPreview(null);
    setConfirmError(null);
  }

  // Live WS data wins over the subscribe-response seed once it starts
  // flowing, but the seed keeps the table from rendering blank meanwhile.
  const displayQuotes = { ...seedQuotes, ...quotesByKey };

  const underlyingPrice =
    strikes.length > 0 && symbol && selectedExpiry
      ? (Object.values(displayQuotes).find(
          (q) => q.symbol === symbol && q.expiry === selectedExpiry && q.underlying_price !== null,
        )?.underlying_price ?? null)
      : null;

  if (!symbol) {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-slate-800 p-4">
        <h2 className="text-sm font-medium text-slate-300">Options</h2>
        <p className="text-sm text-slate-500">Select a ticker above to browse its options chain.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-slate-800 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-slate-300">
          Options — <span className="font-mono">{symbol}</span>
        </h2>
        <label className="flex items-center gap-1.5 text-sm text-slate-300">
          Expiry
          <select
            value={selectedExpiry ?? ""}
            onChange={(e) => setSelectedExpiry(e.target.value || null)}
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          >
            {expiries.length === 0 && <option value="">No expiries available</option>}
            {expiries.map((expiry) => (
              <option key={expiry} value={expiry}>
                {expiry}
              </option>
            ))}
          </select>
        </label>
      </div>

      {chainError && <p className="text-sm text-red-400">{chainError}</p>}
      {orderNotice && <p className="text-sm text-emerald-400">{orderNotice}</p>}

      {selectedExpiry && (
        <OptionsChainTable
          strikes={strikes}
          quotesByKey={displayQuotes}
          symbol={symbol}
          expiry={selectedExpiry}
          underlyingPrice={underlyingPrice}
          onSelectContract={(strike, right) => {
            setSelectedContract({ strike, right });
            setPreviewError(null);
            setOrderNotice(null);
          }}
        />
      )}

      {selectedContract && selectedExpiry && (
        <OrderEntryForm
          symbol={symbol}
          expiry={selectedExpiry}
          strike={selectedContract.strike}
          right={selectedContract.right}
          onSubmit={handlePreview}
          onCancel={() => setSelectedContract(null)}
          submitting={previewLoading}
          error={previewError}
        />
      )}

      <div className="border-t border-slate-800 pt-3">
        <h3 className="mb-2 text-sm font-medium text-slate-300">Open positions</h3>
        <OpenPositionsPanel positions={positions} onClose={onClosePosition} />
      </div>

      {preview && (
        <OrderConfirmationDialog
          preview={preview}
          onConfirm={handleConfirm}
          onCancel={handleCancelPreview}
          confirming={confirming}
          error={confirmError}
        />
      )}
    </div>
  );
}
