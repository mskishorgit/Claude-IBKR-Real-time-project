import type {
  OptionPositionData,
  OptionQuoteData,
  OptionRight,
  OrderAction,
  OrderKind,
  OrderPreview,
  StopTargetConfig,
  TradingSafetyStatus,
} from "./types";

const HTTP_URL = import.meta.env.VITE_BACKEND_HTTP_URL ?? "http://localhost:8000";

async function parseErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    // FastAPI/pydantic validation errors (422) shape `detail` as a list of
    // {msg, loc, ...} objects rather than a plain string.
    if (Array.isArray(body?.detail) && body.detail.length > 0 && typeof body.detail[0]?.msg === "string") {
      return body.detail[0].msg;
    }
    return fallback;
  } catch {
    return fallback;
  }
}

async function requestJson<T>(path: string, init: RequestInit, fallback: string): Promise<T> {
  const res = await fetch(`${HTTP_URL}${path}`, init);
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, `${fallback} (HTTP ${res.status})`));
  }
  return res.json();
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export async function addTicker(symbol: string): Promise<{ tickers: string[] }> {
  return requestJson(
    "/api/tickers",
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ symbol }) },
    "Failed to add ticker",
  );
}

export async function removeTicker(symbol: string): Promise<{ tickers: string[] }> {
  return requestJson(`/api/tickers/${encodeURIComponent(symbol)}`, { method: "DELETE" }, "Failed to remove ticker");
}

// --- Trading safety (paper/live gate) ------------------------------------

export async function getTradingSafety(): Promise<TradingSafetyStatus> {
  return requestJson("/api/trading-safety", {}, "Failed to load trading safety status");
}

export async function setLiveTradingArmed(armed: boolean): Promise<TradingSafetyStatus> {
  return requestJson(
    "/api/trading-safety/arm",
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ armed }) },
    "Failed to update live-trading arming",
  );
}

// --- Options chain --------------------------------------------------------

export async function getOptionExpiries(symbol: string): Promise<{ symbol: string; expiries: string[] }> {
  return requestJson(
    `/api/options/expiries?symbol=${encodeURIComponent(symbol)}`,
    {},
    "Failed to load option expiries",
  );
}

export async function subscribeOptionChain(
  symbol: string,
  expiry: string,
): Promise<{ quotes: OptionQuoteData[] }> {
  return requestJson(
    "/api/options/chain/subscribe",
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ symbol, expiry }) },
    "Failed to subscribe to option chain",
  );
}

export async function unsubscribeOptionChain(symbol: string): Promise<{ status: string }> {
  return requestJson(
    "/api/options/chain/unsubscribe",
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ symbol }) },
    "Failed to unsubscribe option chain",
  );
}

// --- Orders -----------------------------------------------------------------

export interface CreateOrderPreviewParams {
  symbol: string;
  expiry: string;
  strike: number;
  right: OptionRight;
  action: OrderAction;
  orderType: OrderKind;
  quantity: number;
  limitPrice?: number | null;
  stopLoss?: StopTargetConfig | null;
  profitTarget?: StopTargetConfig | null;
}

export async function createOrderPreview(params: CreateOrderPreviewParams): Promise<OrderPreview> {
  return requestJson(
    "/api/options/orders/preview",
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        symbol: params.symbol,
        expiry: params.expiry,
        strike: params.strike,
        right: params.right,
        action: params.action,
        order_type: params.orderType,
        quantity: params.quantity,
        limit_price: params.limitPrice ?? null,
        stop_loss: params.stopLoss ?? null,
        profit_target: params.profitTarget ?? null,
      }),
    },
    "Failed to preview order",
  );
}

export async function confirmOrder(previewId: string): Promise<{ order_id: number; status: string }> {
  return requestJson(
    `/api/options/orders/${encodeURIComponent(previewId)}/confirm`,
    { method: "POST" },
    "Failed to submit order",
  );
}

export async function discardOrderPreview(previewId: string): Promise<void> {
  await fetch(`${HTTP_URL}/api/options/orders/preview/${encodeURIComponent(previewId)}`, { method: "DELETE" });
}

// --- Positions ----------------------------------------------------------------

export async function listOptionPositions(): Promise<{ positions: OptionPositionData[] }> {
  return requestJson("/api/options/positions", {}, "Failed to load positions");
}

export async function closeOptionPosition(positionId: string): Promise<{ order_id: number; status: string }> {
  return requestJson(
    `/api/options/positions/${encodeURIComponent(positionId)}/close`,
    { method: "POST" },
    "Failed to close position",
  );
}
