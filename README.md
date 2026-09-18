# Scalp Dashboard

A full-stack project for building a live scalping dashboard on top of Interactive
Brokers TWS/Gateway: IBKR → FastAPI backend → WebSocket → React frontend, with a
live-updating candlestick chart, a rule-based signal engine that flags
potential entries, and a notification layer (browser push, in-app alerts,
sound, optional Telegram) so you don't have to stare at the tab to catch one.
There is no order placement yet — this is detection and alerting on top of
the live market-data pipeline.

```
scalp-dashboard/
├── backend/    FastAPI + ib_async + a rule-based signal engine
└── frontend/   React + TypeScript + Vite + Tailwind + lightweight-charts
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

See `.env.example` for the signal engine's `SIGNALS_*` variables (one enabled
flag and its key thresholds per rule) — covered in detail below.

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
  - `{"type": "bar", "symbol": ..., "timestamp": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}` for each bar update, including intra-bar ticks as the current bar forms
  - `{"type": "ticker_error", "symbol": ..., "code": ..., "message": ...}` for per-symbol issues (e.g. missing market data subscription)
- `WS /ws/signals` — a **separate** channel (so a client can subscribe to
  just this) streaming `{"type": "signal", "ticker": ..., "rule": ...,
  "direction": "long"|"short", "price": ..., "volume": ..., "timestamp": ...,
  "details": {...}}` whenever the signal engine flags a potential entry.
  Nothing else is sent on this channel.

### The signal engine

`backend/app/signals/` is a standalone, dependency-free package (no
FastAPI/ib_async imports) that flags potential scalping entries from
finalized 1-minute bars. It's wired into the live server via
`MarketDataManager.add_bar_closed_listener` (see below), and driven
identically by the CSV backtest CLI — same rules, same code path, whether
the bars come from IBKR live or a CSV.

**This step is detection and alerting only — it never places an order.**

Four named, independently configurable rules (`backend/app/signals/rules.py`,
enabled/tuned via the `SIGNALS_*` env vars or by constructing rule objects
directly in code/tests):

1. **`vwap_reclaim`** — price was extended away from VWAP for several
   consecutive bars, then this bar closes back on the other side of VWAP on
   above-average volume. Extended below → reclaim (long). Extended above →
   rejection (short).
2. **`ema_cross`** — the fast EMA (default period 9) crosses the slow EMA
   (default period 20) on rising volume (this bar's volume exceeds the
   previous bar's by a configurable multiplier).
3. **`volume_spike_breakout`** — this bar's volume is `N` standard
   deviations above its rolling average, *and* this bar breaks the prior
   `M`-bar high or low. (The spec names both thresholds "N" in prose; they're
   independent knobs here — `volume_spike_std_dev_threshold` and
   `volume_spike_breakout_lookback_bars` — since a volatility multiplier and
   a bar-count window aren't interchangeable.)
4. **`relative_volume_filter`** — not an independent trigger, but a gate
   applied to the three rules above: suppresses a candidate signal unless
   today's cumulative volume pace (at the bar's time of day) is at least
   `min_ratio` times the average pace seen at that same time of day across
   prior sessions. The baseline has no persistence across restarts and no
   external multi-day warm-up by default — it's only as good as what the
   process has observed since it started (or was fed via backtest).

Every emitted signal includes `ticker`, `rule`, `direction`, `price`,
`volume`, `timestamp`, and a `details` dict with rule-specific context (VWAP
value, EMA values, volume z-score, the relative-volume reading, etc.) so you
can judge signal quality, not just trust it blindly.

#### Backtesting against a CSV or IBKR historical export

```bash
cd backend
source .venv/bin/activate
python -m app.signals.backtest --csv path/to/bars.csv --out fired_signals.csv
```

- Accepts a CSV with `symbol`/`ticker`, `timestamp`/`date`, `open`, `high`,
  `low`, `close`, `volume` columns (case-insensitive, several common aliases
  recognized) — including IBKR's own historical-data export format. If the
  CSV has no symbol column (a single-symbol export), pass `--symbol AAPL`.
- Runs the exact same `SignalEngine` used live, in order, over the whole
  file, and prints every bar that would have fired a signal (rule, direction,
  price/volume, timestamp). `--out` additionally writes them to a CSV.
- This is the tool for sanity-checking rule quality and tuning thresholds
  before trusting the live `/ws/signals` feed.

#### Why bar-closed vs. raw bar streaming are different paths

`MarketDataManager` distinguishes two things from the same underlying
ib_async `updateEvent`: intra-bar ticks (the current bar updating in place,
`hasNewBar=False`) which stream to `/ws/bars` for the live chart, and a bar
*finalizing* (`hasNewBar=True`, meaning the bar before the newly-appended one
just closed) which is what's handed to `add_bar_closed_listener` — and
therefore to the signal engine. The engine never evaluates a partial,
still-forming bar; the chart never waits for a bar to close to show it
forming. This also warms up indicator state (EMA/VWAP/rolling volume) from
the already-completed history fetched at subscribe time, rather than the
engine starting from nothing on the first live bar.

#### Backend tests

```bash
cd backend
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

Covers each rule firing and *not* firing under a hand-built deterministic
bar sequence, the relative-volume filter suppressing a signal (with an
identical unfiltered run proving the filter — not something else — was
responsible), the CSV loader, the bar-closed vs. raw-bar dispatch logic in
`MarketDataManager`, and the Telegram notifier's rule filter/cooldown/payload
(via `httpx.MockTransport`, no real network calls).

### Optional: Telegram notifications

`backend/app/notifications/telegram.py` posts a message to a Telegram chat
for every signal that isn't filtered by rule or still inside its own
cooldown — independent of anything happening in the browser, so this is what
reaches you if the dashboard's tab (or the browser itself) is closed.
**Disabled unless you set it up** — nothing is hardcoded, and by default
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are blank in `.env.example`:

1. Message **@BotFather** on Telegram, send `/newbot`, follow the prompts —
   you get a bot token back.
2. Send your new bot any message (e.g. "hi"), then open
   `https://api.telegram.org/bot<your-token>/getUpdates` in a browser and
   read your chat id out of the JSON (`"chat": {"id": ...}`).
3. Put both in `backend/.env`:

   ```bash
   TELEGRAM_BOT_TOKEN=123456:your-token-here
   TELEGRAM_CHAT_ID=123456789
   ```
4. Restart the backend. Logs will say `Telegram notifications enabled` on
   startup if both values are present.

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(blank = disabled)* | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | *(blank = disabled)* | Chat id to send messages to |
| `TELEGRAM_ENABLED_RULES` | *(blank = all rules)* | Comma-separated rule names to notify on via Telegram |
| `TELEGRAM_COOLDOWN_SECONDS` | `120` | Minimum seconds between two Telegram messages for the same ticker+rule |

This has its own rule filter and cooldown, separate from the frontend's
notification settings below — the frontend's settings live in that
browser's `localStorage`, which a backend process has no way to read, so the
two are intentionally independent knobs.

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
- A live candlestick chart (with a volume pane below it) for the selected
  ticker, updating in real time as new bars stream in over the same
  WebSocket. Tabs above the chart switch symbols without reconnecting.
- VWAP, EMA(9), and EMA(20) overlays, each independently toggleable.
- A dashed live price line on the chart tracking the latest close.
- A ticker control box to add/remove symbols at runtime.
- A **signal alerts tray** (top-right) showing recent fired signals as
  dismissible cards — click one to jump the chart to that ticker.
- A **Signal alerts** settings section: enable browser push notifications,
  mute/test the audible alert, set the per-ticker/rule cooldown (default 2
  minutes), and pick which rules generate alerts at all.
- A collapsible raw table of incoming 1-minute bars, for confirming the pipe
  itself still works independent of the chart.

### The chart component

`frontend/src/components/CandlestickChart.tsx` is a standalone, reusable
component — it only needs `symbol` and an ascending, per-symbol `bars` array;
it doesn't know about the WebSocket or REST layer. It accepts `height`,
`showVolume`, `overlays` (`{ vwap, ema9, ema20 }`), and a `compact` flag that
trims axes/labels for small tiles. This is meant to be dropped into a future
watchlist grid of several small charts without changes.

Indicators (`frontend/src/indicators.ts`) are computed client-side from the
bars already held in the browser (`useBackendSocket`'s `barsBySymbol`), not
by the backend — VWAP resets at each UTC calendar day boundary as an
approximation of a trading session.

### The notification layer

`frontend/src/useNotificationCenter.ts` turns the raw `/ws/signals` stream
(`useSignalStream.ts`, a separate WebSocket connection from `/ws/bars`) into
toasts, browser push notifications, and sound — each signal is processed
exactly once, gated by two things from **Signal alerts** settings
(persisted in `localStorage`, per-browser, nothing sent to the backend):

- **Per-rule enable/disable** — a signal for a disabled rule produces no
  toast, no push notification, and no sound at all.
- **A cooldown window** (default 2 minutes, configurable) keyed by
  `ticker:rule` — a second signal for the same ticker and rule within the
  window is silently dropped, so a choppy market can't spam you.

Browser push notifications (`Notification` API) fire even when the tab isn't
focused, as long as the browser has the tab open at all — click "Enable
browser notifications" once (browsers require a user gesture; it can't
prompt itself on load). If the tab or browser is fully closed, only the
optional Telegram integration above still reaches you.

Audible alerts (`frontend/src/alertSound.ts`) are synthesized with the Web
Audio API — an ascending two-note chime for long signals, descending for
short — so there are no sound assets to ship or host. A mute toggle and a
"Test sound" button (which also satisfies the browser's autoplay-unlock
requirement) are in the settings panel.

The toast tray (`SignalAlertTray.tsx`) keeps up to the 50 most recent
alerts, newest first, until you dismiss them individually; clicking a
toast's ticker calls the same `onSelectSymbol` the chart's ticker tabs use.

### Frontend environment variables (`frontend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `VITE_BACKEND_HTTP_URL` | `http://localhost:8000` | Base URL for REST calls |
| `VITE_BACKEND_WS_URL` | `ws://localhost:8000/ws/bars` | Raw bar WebSocket URL |
| `VITE_BACKEND_SIGNALS_WS_URL` | `ws://localhost:8000/ws/signals` | Signal alert WebSocket URL |

## Notes on the IBKR library choice

The original `ib_insync` package is no longer maintained by its author. This
project uses **`ib_async`**, the actively maintained community fork with the
same API, so `from ib_async import IB, Stock` is a drop-in replacement for
`ib_insync` code you may find elsewhere.

## What's not in this step

- No watchlist grid of multiple charts at once (the chart component is built
  to support this next, but the UI only shows one at a time so far).
- No order placement — the signal engine only detects and alerts.
- No persistence of bar, signal, or notification history (only what's held
  in memory per backend process, and in each browser's `localStorage`/tab
  memory). The relative-volume baseline and Telegram's cooldown both reset
  on backend restart for the same reason; the toast tray resets on page reload.
- Browser push notifications need the tab open (even if unfocused/backgrounded)
  — reaching you with the tab or browser fully closed is what the optional
  Telegram integration is for, not the Notifications API.

These come in later steps, on top of this working data pipeline.
