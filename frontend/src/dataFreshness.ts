import type { IbkrState } from "./types";
import type { SocketState } from "./useBackendSocket";

/** True whenever whatever prices/positions/P&L are currently on screen
 * could be frozen rather than live: either the backend itself lost its
 * IBKR connection (bars/quotes/account updates all stop, but the last
 * values stay rendered), or this browser tab lost its own WebSocket to the
 * backend. Either way, the UI must say so rather than let a frozen number
 * keep looking live — see the reconnect-logic hardening pass. */
export function isDataStale(ibkrState: IbkrState, socketStates: SocketState[]): boolean {
  if (ibkrState !== "connected") return true;
  return socketStates.some((s) => s !== "open");
}
