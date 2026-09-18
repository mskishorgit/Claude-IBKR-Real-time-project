import type { IbkrState } from "../types";
import type { SocketState } from "../useBackendSocket";

interface Props {
  socketState: SocketState;
  ibkrState: IbkrState;
  ibkrError: string | null;
}

type Visual = "connected" | "pending" | "disconnected";

const DOT_STYLES: Record<Visual, string> = {
  connected: "bg-emerald-400",
  pending: "bg-amber-400",
  disconnected: "bg-red-400",
};

const PILL_STYLES: Record<Visual, string> = {
  connected: "bg-emerald-500/15 text-emerald-400 border-emerald-500/40",
  pending: "bg-amber-500/15 text-amber-400 border-amber-500/40",
  disconnected: "bg-red-500/15 text-red-400 border-red-500/40",
};

export function ConnectionStatus({ socketState, ibkrState, ibkrError }: Props) {
  let label: string;
  let visual: Visual;

  if (socketState !== "open") {
    label = socketState === "connecting" ? "Connecting to backend…" : "Reconnecting to backend…";
    visual = "pending";
  } else {
    switch (ibkrState) {
      case "connected":
        label = "Connected to IBKR";
        visual = "connected";
        break;
      case "connecting":
        label = "Connecting to IBKR…";
        visual = "pending";
        break;
      case "reconnecting":
        label = "Reconnecting to IBKR…";
        visual = "pending";
        break;
      default:
        label = "Disconnected from IBKR";
        visual = "disconnected";
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <div
        className={`inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1 text-sm font-medium ${PILL_STYLES[visual]}`}
      >
        <span className="relative flex h-2 w-2">
          {visual === "connected" && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          )}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${DOT_STYLES[visual]}`} />
        </span>
        {label}
      </div>
      {ibkrError && <p className="max-w-xl text-xs text-slate-400">{ibkrError}</p>}
    </div>
  );
}
