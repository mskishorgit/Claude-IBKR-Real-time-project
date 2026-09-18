import type { IbkrState } from "../types";

interface Props {
  ibkrState: IbkrState;
  ibkrError: string | null;
  backendReachable: boolean;
}

/** Unmissable — not just the small ConnectionStatus pill in the header —
 * because the whole point is that a price/position that stopped updating
 * still looks identical to a live one unless something says otherwise. See
 * the WS-reconnect hardening pass: previously only the header pill
 * reflected connection state, and every price tile/chart/table kept
 * showing its last-known values with nothing marking them as frozen. */
export function StaleDataBanner({ ibkrState, ibkrError, backendReachable }: Props) {
  if (!backendReachable) {
    return (
      <div className="rounded-lg border-2 border-amber-500 bg-amber-950 px-4 py-3 text-sm font-bold text-amber-200">
        ⚠ Not connected to the backend — all data shown below may be stale. Reconnecting…
      </div>
    );
  }

  if (ibkrState !== "connected") {
    return (
      <div className="rounded-lg border-2 border-amber-500 bg-amber-950 px-4 py-3">
        <div className="text-sm font-bold text-amber-200">
          ⚠ Backend lost its IBKR connection — prices, positions, and account figures below may
          be stale, not live.
        </div>
        {ibkrError && <div className="mt-1 text-xs text-amber-300">{ibkrError}</div>}
      </div>
    );
  }

  return null;
}
