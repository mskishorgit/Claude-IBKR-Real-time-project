# Scalp Dashboard

A full-stack project for building a live scalping dashboard on top of Interactive
Brokers TWS/Gateway. **This first step only proves the data pipeline**: IBKR →
FastAPI backend → WebSocket → React frontend, rendered as a raw table. There is
no charting or strategy logic yet.

```
scalp-dashboard/
├── backend/    FastAPI + ib_async, connects to TWS/IB Gateway and streams bars
└── frontend/   React + TypeScript + Vite + Tailwind, shows the raw feed
```

## 1. Start TWS or IB Gateway in paper trading mode

1. Install and open **Trader Workstation (TWS)** or **IB Gateway**.
2. At the login screen, switch the mode selector to **Paper Trading** (do this
   before you use this project against a live account).
3. Log in with your paper trading credentials.

## 2. Enable the API in TWS/Gateway

In TWS (or IB Gateway), go to:

```
Configure (or Edit) > Settings > API > Settings
```

and:

- Check **Enable ActiveX and Socket Clients**.
- Uncheck **Read-Only API** if you'll eventually want to place orders from
  this project (not needed for this step, which is read-only market data).
- Note the **Socket port**. By default:
  - Paper trading: `7497`
  - Live trading: `7496`
- Under **Trusted IPs**, add `127.0.0.1` if you're running the backend on the
  same machine as TWS (this is usually automatic for localhost).
- Leave TWS/Gateway running — the API only works while it's open and logged in.

The backend's `.env` must point at whichever port TWS/Gateway is actually
listening on (see below).

## 3. Run the backend

Requires Python 3.11+.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env if your TWS/Gateway host, port, or client ID differ from defaults

uvicorn app.main:app --reload --port 8000
```

On startup the backend tries to connect to TWS/Gateway and subscribes to the
tickers listed in `DEFAULT_TICKERS` in `.env`. If TWS/Gateway isn't reachable,
the backend **stays up** and retries in the background — check
`GET /api/status` or the frontend's status indicator for the reason
(connection refused, timeout, client ID already in use, etc.) rather than a
silent failure.

### Backend environment variables (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `IBKR_HOST` | `127.0.0.1` | Host running TWS/Gateway |
| `IBKR_TRADING_MODE` | `paper` | `paper` or `live` — selects which port below is used |
| `IBKR_PAPER_PORT` | `7497` | Socket port for paper trading |
| `IBKR_LIVE_PORT` | `7496` | Socket port for live trading |
| `IBKR_CLIENT_ID` | `42` | Must be unique among API clients connected to the same TWS/Gateway instance |
| `IBKR_RECONNECT_DELAY_SECONDS` | `5` | Delay between reconnect attempts |
| `IBKR_HEARTBEAT_INTERVAL_SECONDS` | `10` | How often to ping TWS/Gateway to detect a stale connection |
| `DEFAULT_TICKERS` | `AAPL,MSFT,SPY` | Tickers subscribed on startup |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origin(s) |

### Backend API

- `GET /api/status` — connection state (`connected` / `connecting` /
  `reconnecting` / `disconnected`), last error message, and tracked tickers.
- `GET /api/tickers` — list tracked tickers.
- `POST /api/tickers` `{"symbol": "NVDA"}` — start tracking a ticker
  (returns `503` if not currently connected to IBKR, `400` if IBKR can't
  resolve the symbol, `409` if already tracked).
- `DELETE /api/tickers/{symbol}` — stop tracking a ticker.
- `WS /ws/bars` — streams JSON messages:
  - `{"type": "status", "state": ..., "error": ...}` on connection state changes
  - `{"type": "tickers", "tickers": [...]}` when the tracked list changes
  - `{"type": "bar", "symbol": ..., "timestamp": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}` for each new/updated 1-minute bar
  - `{"type": "ticker_error", "symbol": ..., "code": ..., "message": ...}` for per-symbol issues (e.g. missing market data subscription)

### Common error states

The backend is built to surface these clearly instead of failing silently:

- **TWS/Gateway not running or API not enabled** → connection refused, shown
  as `disconnected` with an explanatory message telling you to check the API
  setting.
- **TWS/Gateway restarts or the socket drops** → `reconnecting` state, backend
  keeps retrying, heartbeat detects a dead socket even if the OS doesn't
  report it.
- **Market data subscription missing for a ticker** → a `ticker_error`
  message on the WebSocket naming the symbol and the IB error code/text
  (bars may still arrive as delayed data).
- **`clientId` already in use** → clear error telling you to change
  `IBKR_CLIENT_ID` in `.env`.

## 4. Run the frontend

Requires Node.js 20+.

```bash
cd frontend
npm install

cp .env.example .env
# edit if the backend isn't on localhost:8000

npm run dev
```

Open the printed local URL (default `http://localhost:5173`). You should see:

- A connection status pill (connected / connecting / reconnecting /
  disconnected) reflecting the backend's live IBKR connection state, with the
  underlying error message shown underneath when disconnected.
- A ticker control box to add/remove symbols at runtime.
- A raw table of incoming 1-minute bars as they stream in.

### Frontend environment variables (`frontend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `VITE_BACKEND_HTTP_URL` | `http://localhost:8000` | Base URL for REST calls |
| `VITE_BACKEND_WS_URL` | `ws://localhost:8000/ws/bars` | WebSocket URL |

## Notes on the IBKR library choice

The original `ib_insync` package is no longer maintained by its author. This
project uses **`ib_async`**, the actively maintained community fork with the
same API, so `from ib_async import IB, Stock` is a drop-in replacement for
`ib_insync` code you may find elsewhere.

## What's not in this step

- No charting.
- No strategy/signal logic.
- No order placement.
- No persistence of bar history (only what's held in memory since the
  backend started, plus whatever IBKR returns for the initial lookback
  window).

These come in later steps, on top of this working data pipeline.
