const HTTP_URL = import.meta.env.VITE_BACKEND_HTTP_URL ?? "http://localhost:8000";

async function parseErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    return typeof body?.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function addTicker(symbol: string): Promise<{ tickers: string[] }> {
  const res = await fetch(`${HTTP_URL}/api/tickers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, `Failed to add ticker (HTTP ${res.status})`));
  }
  return res.json();
}

export async function removeTicker(symbol: string): Promise<{ tickers: string[] }> {
  const res = await fetch(`${HTTP_URL}/api/tickers/${encodeURIComponent(symbol)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, `Failed to remove ticker (HTTP ${res.status})`));
  }
  return res.json();
}
