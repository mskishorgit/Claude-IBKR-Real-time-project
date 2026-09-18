import type { ToastSignal } from "../useNotificationCenter";

interface Props {
  toasts: ToastSignal[];
  onDismiss: (id: string) => void;
  onSelectSymbol: (symbol: string) => void;
}

export function SignalAlertTray({ toasts, onDismiss, onSelectSymbol }: Props) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed right-4 top-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`flex items-start gap-2 rounded-lg border p-3 shadow-lg backdrop-blur ${
            toast.direction === "long"
              ? "border-emerald-500/40 bg-emerald-950/90"
              : "border-red-500/40 bg-red-950/90"
          }`}
        >
          <button
            type="button"
            className="flex-1 text-left"
            onClick={() => onSelectSymbol(toast.ticker)}
          >
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-semibold text-slate-100">{toast.ticker}</span>
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                  toast.direction === "long"
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "bg-red-500/20 text-red-400"
                }`}
              >
                {toast.direction}
              </span>
            </div>
            <div className="text-xs text-slate-400">
              {toast.rule.replace(/_/g, " ")} @ {toast.price}
            </div>
            <div className="text-[10px] text-slate-500">
              {new Date(toast.timestamp).toLocaleTimeString()}
            </div>
          </button>
          <button
            type="button"
            aria-label={`Dismiss ${toast.ticker} alert`}
            onClick={() => onDismiss(toast.id)}
            className="text-slate-500 hover:text-slate-300"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
