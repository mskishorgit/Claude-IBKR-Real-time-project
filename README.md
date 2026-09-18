# Scalp Dashboard

A full-stack project for building a live scalping dashboard on top of Interactive
Brokers TWS/Gateway: IBKR → FastAPI backend → WebSocket → React frontend, with a
live-updating candlestick chart, a rule-based signal engine that flags
potential entries, a notification layer (browser push, in-app alerts, sound,
optional Telegram), an options trading panel that can place real 0DTE/weekly
option orders through IBKR — paper by default, live gated behind an explicit,
visible arm switch — a live watchlist/portfolio view pulling the account's
actual positions and P/L straight from IBKR, and a trading journal with a
daily P/L calendar backed by a local SQLite database, reconciled
periodically against IBKR's own execution history. A hardening pass added
an account/mode mismatch check, a global emergency kill switch, a
stale-data banner for when the IBKR connection drops mid-session, and
client-side pacing limits on every IBKR data request. **Read the "Options
trading panel" section before touching that part of the UI against a live
account, and see `RUNBOOK.md` for the short operational version of all of
this (starting safely, verifying paper mode, switching to live, and using
the kill switch) before your first live session.**

```
scalp-dashboard/
├── backend/    FastAPI + ib_async + a rule-based signal engine
├── frontend/   React + TypeScript + Vite + Tailwind + lightweight-charts
└── RUNBOOK.md  Operational safety procedures for running against a live account
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
| `JOURNAL_DB_PATH` | `scalp_journal.db` | SQLite file for the trading journal (relative to `backend/`) |
| `JOURNAL_SYNC_INTERVAL_SECONDS` | `300` | How often to reconcile against IBKR's execution history |
| `IBKR_HISTORICAL_RATE_LIMIT_MAX_CALLS` | `6` | Historical-data pacing limit — max requests... |
| `IBKR_HISTORICAL_RATE_LIMIT_PER_SECONDS` | `2.0` | ...per this many seconds (IBKR's own documented rule) |
| `IBKR_GENERAL_RATE_LIMIT_MAX_CALLS` | `30` | Shared limit for reqMktData/qualifyContracts/etc — max requests... |
| `IBKR_GENERAL_RATE_LIMIT_PER_SECONDS` | `1.0` | ...per this many seconds |

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
- `GET /api/trading-safety` / `POST /api/trading-safety/arm` `{"armed": bool}`
  — read/set the options panel's live-trading arm switch. See "Options
  trading panel" below.
- `POST /api/trading-safety/kill-switch/engage` / `POST
  /api/trading-safety/kill-switch/reset` — the emergency kill switch:
  cancels every open order at the IBKR level and blocks all new order
  submission until reset. See "Emergency kill switch" below.
- `GET /api/options/expiries?symbol=` — near-term (0DTE/weekly) expiries for
  a tracked underlying.
- `POST /api/options/chain/subscribe` `{"symbol", "expiry"}` /
  `POST /api/options/chain/unsubscribe` `{"symbol"}` — start/stop streaming
  a chain's near-the-money strikes.
- `POST /api/options/orders/preview` / `POST /api/options/orders/{id}/confirm`
  / `DELETE /api/options/orders/preview/{id}` — the two-step order flow (see
  below). A preview is single-use and short-lived.
- `GET /api/options/positions` / `POST /api/options/positions/{id}/close` —
  list open/closed positions; close is one-click (no preview/confirm step,
  by design — see below).
- `WS /ws/options` — live chain quotes (`option_quote` messages) for
  whatever's currently subscribed.
- `WS /ws/positions` — live P/L (`position_update`) and stop/target alerts
  (`stop_target_alert`) for open positions; sends a `positions_snapshot` on
  connect.
- `GET /api/portfolio/positions` — live IBKR account positions (via
  `reqAccountUpdates`), split into `positions` (equities/ETFs/anything that
  isn't an option) and `option_positions` (with strike/expiry/greeks). This
  is the account's actual holdings — not just positions opened through this
  app's own options order flow (that's `/api/options/positions` above).
- `GET /api/portfolio/summary` — net liquidation, buying power, and day
  realized/unrealized P/L for the account.
- `WS /ws/portfolio` — sends a `portfolio_snapshot` (both position lists +
  the summary) on connect, then `position_update` / `option_position_update`
  / `account_summary` messages as IBKR reports changes.
- `GET /api/journal/calendar?year=&month=` — that month's realized P/L and
  trade count per day that had at least one closed trade.
- `GET /api/journal/day?day=YYYY-MM-DD` — every closed round-trip trade for
  one day (ticker, entry/exit time+price, contract details if it was an
  option, P/L, and the signal rule that triggered the entry, if any).
- `GET /api/journal/stats?year=&month=` — win rate, average win/loss,
  largest win/loss, and a per-ISO-week P/L breakdown for that month.
- `POST /api/journal/sync` — trigger an immediate `reqExecutions`
  reconciliation on top of the periodic background sync (returns `503` if
  not currently connected to IBKR).
- `WS /ws/journal` — sends a `trade_recorded` message whenever a new
  round-trip trade lands in the journal DB; carries no data of its own
  beyond that nudge, since REST stays the source of truth for the
  calendar/day/stats data itself.

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

### Options trading panel

**This places real orders through IBKR when armed against a live account.**
`backend/app/options/` is a distinct package (safety.py, chain.py,
positions.py, orders.py, stop_target.py) wired into `main.py` the same way
as the signal engine — plain Python where it can be (stop/target math,
P/L, the safety gate), ib_async only where it must be (chain lookups,
market data, order placement).

#### The paper/live safety model

Four independent things all funnel through the exact same choke point —
`TradingSafety.check_order_allowed()`, called at the top of every single
`ib.placeOrder`-adjacent call in this app (preview, confirm, and one-click
close; verified by grepping for every `placeOrder` call site — there are
exactly two, both in `app/options/orders.py`, both gated). The first two
were the original design; the last two were added in a hardening pass
after an explicit audit of every order-submission path (see `RUNBOOK.md`
for the operational version of all of this):

1. **`IBKR_TRADING_MODE`** in `.env` — fixed for the backend process's
   lifetime, same variable that already picks the connection port. This is
   "which account is IBKR actually talking to," *according to `.env`.*
2. **The arm switch** — a runtime-only, in-memory flag (`live_armed`,
   default `False`) toggled from the UI via `POST /api/trading-safety/arm`.
   This is "has a human, right now, explicitly said yes to real orders."
3. **Account/mode cross-check** (`account_mode_mismatch`) — #1 above is
   only ever what `.env` *says*; nothing previously verified it against
   which account IBKR actually connected the process to. A TWS/Gateway port
   misconfigured so `IBKR_TRADING_MODE=paper` points at a real account
   would otherwise let "paper" orders hit real money without this app ever
   noticing. IBKR paper/demo accounts are always `DU`-prefixed; live
   accounts never are — a mismatch here blocks **every** order, including
   in paper mode, which previously skipped every check unconditionally.
   The account id is learned from the first `accountValueEvent` IBKR sends
   after connecting (see `PortfolioService`), so there's a short window
   right after startup where this can't yet be evaluated (recorded as
   "not a mismatch," not "safe" — see `TradingSafety.account_mode_mismatch`).
4. **The kill switch** (`kill_switch_engaged`) — see "Emergency kill
   switch" below.

When `IBKR_TRADING_MODE=paper` *and there's no account mismatch*, an order
is inherently safe and the frontend shows no banner for #1/#2 at all. When
it's `live`, the UI shows an amber "connected to a LIVE account, orders
blocked" banner until you arm it, at which point it becomes a bold red
"LIVE TRADING ARMED" banner that stays up for as long as it's armed. A
mismatch (#3) or an engaged kill switch (#4) shows its own banner and
blocks orders regardless of #1/#2's state. Arming is never implicit and
never assumed. **Test the whole flow against a paper account first.**

#### The order flow

1. Select a ticker (via the chart tabs, or by clicking a fired signal), pick
   an expiry, click a bid/ask in the chain table to select that
   strike/side, then fill in the order form (action, market/limit,
   quantity, optional stop-loss/profit-target).
2. **"Preview order"** calls `POST /api/options/orders/preview`, which
   re-checks the safety gate, fetches a *fresh* quote, and returns a
   short-lived (90s), single-use preview — nothing has been sent to IBKR
   yet.
3. A confirmation dialog shows exactly what that preview captured
   (contract, action, quantity, the quote, and — in bold red if
   applicable — that this is a LIVE order). **There is no way to submit
   without this step.**
4. **"Confirm & submit"** calls `POST /api/options/orders/{id}/confirm`,
   which re-checks the safety gate again (state can change between preview
   and confirm), pops the preview (single-use — a failure here always
   means a fresh preview against a fresh quote next time, never a blind
   resubmission), and only then calls `ib.placeOrder`. Every attempt and
   every IBKR status/fill update is logged. **Nothing here retries
   automatically, ever** — a failed submission is surfaced to you, not
   silently reattempted.
5. Once filled, the position appears with a live-updating unrealized P/L
   (from the option's own live bid/ask, marked at the mid).
6. **"Close position"** is deliberately **one click, no confirmation
   dialog** (an explicit exception to the rule above, per spec, since
   hesitating to exit a scalp costs money) — but it still runs through the
   exact same safety gate as opening an order.

#### Stop-loss / profit-target: alert-only (by design, for now)

Set a stop and/or target (as a `$`-per-contract or `%`-of-entry-premium
move) when you fill in the order form. Once the position is open, its live
quote is checked against those levels on every tick; crossing one fires a
**visual flag on that position's card and a `stop_target_alert` over
`/ws/positions`** — it does **not** place an order and does **not**
auto-close the position. Each level fires once (latched), not on every
tick past it. Auto-submitting a bracket order to actually enforce these is
an explicit stretch goal from the spec that isn't implemented — flagging
first, reliably, was the priority.

#### Emergency kill switch

A red "🛑 Kill switch" button is always visible near the top of the page
(both trading modes) — a global panic button, added in the hardening pass.
Engaging it (`POST /api/trading-safety/kill-switch/engage`, a two-click
confirm in the UI so it can't fire by accident):

- Cancels every currently open (working, unfilled) order at the IBKR
  level via `ib.reqGlobalCancel()` — **all** open orders on the account,
  not just ones this app itself placed — plus an explicit `cancelOrder`
  per order this process knows about, belt-and-suspenders.
- Sets `kill_switch_engaged=True`, which `check_order_allowed()` checks
  *first*, before anything else — blocking every new preview, confirm, and
  one-click close (yes, including closing a position, which is itself an
  order) until it's reset.
- Drops `live_armed` to `False` as part of engaging, so a bare reset can't
  silently leave live trading armed with no further human action.

It deliberately does **not** close any open position — cancelling a
resting order and flattening a position are different operations, and
"cancel all open orders" only ever means the former. `POST
/api/trading-safety/kill-switch/reset` only lifts the submission block;
live trading (if applicable) needs a separate re-arm. It engages locally
(blocking this app's own order submission) even if IBKR is unreachable —
the response's `ibkr_reachable` field says whether the cancel actually
reached IBKR or only the local flag flipped. See `RUNBOOK.md` for the
step-by-step emergency procedure.

#### Options tests

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/test_stop_target.py tests/test_trading_safety.py \
  tests/test_option_quotes.py tests/test_option_position_pnl.py \
  tests/test_position_manager.py tests/test_options_orders.py -v
```

Covers stop/target price math and level-hit checks for both directions and
both `%`/`$` kinds explicitly (not via a clever shared formula — a
sign/direction bug here is exactly the "expensive bug" this feature warns
about), the arm/disarm gate in both trading modes, IBKR's price-sentinel
vs. legitimate-negative-delta handling, P/L math long and short, stop/target
alert latching (fires once, not every tick), and the full preview → confirm
→ fill → position → close flow against a fake IBKR client built from real
`ib_async` `Order`/`Trade` objects (so `trade.statusEvent`/`filledEvent`
behave exactly like production) — including that a preview is rejected the
second time it's used, and that both `create_preview` and `close_position`
are blocked when live trading isn't armed. `test_trading_safety.py`
additionally covers the hardening-pass additions: the account/mode
mismatch check in every direction (paper+paper account, paper+live
account, live+paper account, live+live account), that the kill switch
blocks orders regardless of trading mode, that engaging it disarms live
trading, that resetting it does *not* auto-rearm live trading, and
`KillSwitchService` itself (cancels every open order, still engages
locally when IBKR is unreachable, reset clears the flag) against a fake
IBKR client.

### Watchlist & portfolio

`backend/app/account/portfolio.py` wraps `ib.reqAccountUpdates(account)` —
one always-on subscription that gives both live positions
(`updatePortfolioEvent`, with IBKR's own live market price and
unrealized/realized P/L already computed) and the account summary
(`accountValueEvent`: net liquidation, buying power, day P/L) for the
session's managed account. It restarts automatically on every reconnect
(hooked into the same connection-state listener the rest of the app uses),
since a fresh `ib_async` session has no memory of the previous subscription.

- **Equity vs. option positions are genuinely separate types**
  (`AccountPosition` / `AccountOptionPosition`), not one shape with optional
  fields bolted on — options additionally get their own `reqMktData`
  subscription (reusing `options/quotes.py`, so IBKR's "no data" sentinels
  are interpreted identically everywhere in this project) for delta/IV,
  which equities don't have.
- **Account summary currency handling**: IBKR reports each tag once per
  currency. The summary picks one currency per field and sticks to it — a
  `"BASE"` value always takes over (so a multi-currency account doesn't
  flap between currencies), and once a field has picked a currency,
  further updates keep flowing from that same currency, which is what
  makes the summary strip "refreshing live" rather than frozen after the
  first tick. (An earlier version of this filter naively preferred `"BASE"`
  and silently stopped updating altogether for accounts that never report
  one — a caught-and-fixed bug, and a regression test for it lives in
  `tests/test_portfolio_service.py`.)
- **The watchlist grid, sparklines, and "% change today" are frontend-only
  compositions of data this app already streams** — no new backend surface
  for those. Last price and the sparkline come from `barsBySymbol` (already
  in memory from `/ws/bars`); "% change today" is approximated as the move
  since the first bar this process has seen for that symbol (not a true
  previous-close baseline — see the caveat below), same style of
  approximation as the chart's VWAP session reset.
- **The signal-active highlight** (`frontend/src/signalActivity.ts`) treats
  a fired signal as "active" for a fixed window (5 minutes) after it fires,
  since a signal is a point-in-time event, not a persisting state IBKR or
  the signal engine tracks — reuses the same `/ws/signals` stream the
  notification layer already subscribes to.

#### Portfolio tests

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/test_portfolio_service.py -v
```

Covers the account-value currency-picking logic described above (including
the regression test for the frozen-summary bug), splitting equity vs.
option positions, subscribing to greeks exactly once per option contract
(not once per portfolio update), and enriching a position with delta/IV
once a matching ticker update arrives — all against a fake IBKR client
using real `eventkit.Event` objects, so `+=`/`.emit()` behave exactly like
the real `ib_async` events this service listens to.

#### Caveat: "% change today" isn't a true previous-close baseline

Getting a real previous-session close would mean a separate historical-data
snapshot per symbol; this step instead uses the earliest bar already held
in memory for that symbol as the reference point, which is only exactly
right if the ticker was added to the watchlist before that session's first
print. Documented here rather than silently assumed — see the chart's VWAP
session-reset caveat for the same kind of tradeoff made elsewhere in this
project.

### Trading journal

`backend/app/journal/` persists closed round-trip trades and a log of fired
signals to a local SQLite database (`backend/scalp_journal.db` by default,
`JOURNAL_DB_PATH`), so the calendar/stats views don't re-query IBKR on every
page load — and so the numbers survive a backend restart, unlike everything
else in this project so far (see "What's not in this step").

- **Equity/ETF trades and options trades come from two different sources,
  on purpose.** This app never places an equity order itself — a scalp
  placed directly in TWS has no in-app record of it — so equities/ETFs are
  rebuilt from IBKR's own execution history (`reqExecutions` for a
  periodic backfill, `execDetailsEvent` for fills as they happen) and
  matched into round trips FIFO, per symbol, flip-aware (`fifo_matcher.py`:
  a fill that closes an open lot and reverses into the opposite direction
  splits into a close plus a freshly opened lot in the new direction).
  Options, by contrast, are taken directly from `PositionManager`'s own
  entry/close tracking (see "The order flow" above) rather than re-derived
  from raw option executions — it already has the exact entry/exit price
  and realized P/L, multiplier included, that this app itself used when it
  opened and closed the position, so re-parsing executions would just be a
  worse copy of data already sitting in memory.
- **Reconciliation, not just a one-time import.** `ExecutionSyncService`
  backfills via `reqExecutions` on every IBKR reconnect and on a timer
  (`JOURNAL_SYNC_INTERVAL_SECONDS`, default 5 minutes) — plus a manual
  `POST /api/journal/sync` for "pull the numbers right now." Every run is
  safe to repeat: each execution's `execId` is recorded in a
  `synced_executions` dedup table the moment it's folded into the FIFO
  matcher, so a re-run only ever picks up fills this process genuinely
  hasn't seen yet (e.g. it wasn't running yet when they happened, or it
  just reconnected) — it never re-matches (and re-realizes P/L for) the
  same fill twice.
- **Linking a trade back to the signal that triggered it** looks up the
  most recent logged signal for that ticker and direction within a 5-minute
  window before the trade's entry time (`ExecutionSyncService.
  SIGNAL_LINK_WINDOW_SECONDS`) — every fired signal is logged to the same
  database (`_record_signal_in_journal` in `main.py`) specifically so this
  lookup has something to search. No match within the window just leaves
  `signal_rule` `null` — most scalps in a real account won't have started
  from this app's own signal engine at all, and that's an expected, valid
  state, not an error.
- **The weekly P/L total lives beside each calendar row, not as a single
  number above the grid.** `month_stats` groups trades by ISO week
  (Monday-start) and returns a `weekly_pnl` breakdown alongside the monthly
  total; the frontend renders it as a trailing "week total" cell per row —
  the layout real trading-journal calendars (TraderSync, TradeZella, etc.)
  use, and more useful across a full month than a single "this week"
  figure would be. A week that spans a month boundary only sums the trades
  within the *requested* month, so a boundary week's total is a partial
  figure in each of the two months it touches — a SQL-month-filtered
  system's structural limitation, not a bug, noted here rather than
  silently assumed.

#### Trading journal tests

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/test_fifo_matcher.py tests/test_journal_store.py tests/test_execution_sync.py -v
```

`test_fifo_matcher.py` covers the round-trip matching logic in isolation
(simple long/short round trips, partial closes, FIFO ordering across
multiple lots, a fill that closes a lot and reverses into a new one, and
that different symbols are matched independently) — pure Python, no IBKR
or database involved. `test_journal_store.py` covers the SQLite layer
directly (day/month aggregation, win/loss stats, weekly grouping, signal
lookup window/direction matching, execId dedup). `test_execution_sync.py`
covers the service that ties it together, against a fake IBKR client using
a real `eventkit.Event` for `execDetailsEvent` (same pattern as
`test_portfolio_service.py`) so live-fill and backfill paths both behave
exactly like production.

### IBKR pacing limits / rate limiting

IBKR disconnects clients that request data too aggressively. `backend/app/
ibkr/rate_limiter.py`'s `AsyncRateLimiter` — a small async sliding-window
limiter (`await limiter.acquire()` blocks, never raises, until it's safe to
proceed) — throttles every outbound call that could realistically burst:

- **Historical data** (`reqHistoricalDataAsync`, called once per ticker
  add): capped at 6 requests / 2 seconds, matching IBKR's own documented
  historical-data pacing rule exactly. A user (or script) adding several
  tickers back-to-back is the realistic burst case.
- **Everything else data-related** (`reqMktData`, `qualifyContractsAsync`,
  `reqSecDefOptParamsAsync`, `reqExecutionsAsync`): one **shared** limiter
  (default 30 calls/second) injected into `OptionsChainService`,
  `OptionsOrderService`, and `ExecutionSyncService` from `main.py`, so their
  *combined* rate is what's capped — not each one independently, which
  could otherwise stack past IBKR's general ~50-messages/second socket
  guidance if more than one burst happens at once. Subscribing an options
  chain is the tightest realistic burst here: up to ~20+ `reqMktData` calls
  in a row for one `subscribe()` call.

Both limits are configurable (`IBKR_HISTORICAL_RATE_LIMIT_*` /
`IBKR_GENERAL_RATE_LIMIT_*` in `.env`) — see `.env.example`.

**Deliberately never applied to order placement or any cancellation call**
(`placeOrder`, `cancelOrder`, `reqGlobalCancel`, `cancelMktData`,
`cancelHistoricalData`) — an order, and especially an emergency kill-switch
cancel, must never be delayed by a data-request throttle. One call site
(`PortfolioService`'s per-option `reqMktData` for greeks) is deliberately
*not* rate-limited either, with a comment explaining why: it fires at most
once per distinct option contract ever held, for the life of the process —
no realistic trading pace opens enough distinct option positions per
second for that to be the thing that trips a pacing violation.

This is a client-side courtesy limiter, not a guarantee IBKR won't ever
pace-violate for other reasons (e.g. exceeding the account's concurrent
market-data-line entitlement) — see `RUNBOOK.md` if it happens anyway.

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/test_rate_limiter.py -v
```

Covers the limiter in isolation: calls within the limit never wait, a call
over the limit waits exactly long enough for the window to clear (verified
with a monkeypatched clock, not real sleeps), concurrent callers are
serialized through the same window rather than each getting their own
budget, and non-positive configuration is rejected.

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
- An always-visible **🛑 Kill switch** button (see the backend's "Emergency
  kill switch" section above) — a two-click confirm, then a red "KILL
  SWITCH ENGAGED" banner with a "Reset kill switch" button.
- An **account/mode mismatch banner** (red, unmissable) if the account
  IBKR actually connected to doesn't match `IBKR_TRADING_MODE` — see the
  backend's "paper/live safety model" above. All orders are already
  blocked server-side while this shows; the banner exists so a human
  notices immediately rather than discovering it from a failed order.
- A **stale-data banner** (amber) whenever this browser tab loses its
  WebSocket to the backend, or the backend loses its connection to IBKR —
  added in a hardening pass so a frozen price/position/P&L can never keep
  looking live with nothing on screen saying otherwise. Every affected
  section (account summary, watchlist, chart, portfolio) additionally dims
  and shows a small "STALE" tag next to its heading for the same reason,
  localized to where the frozen numbers actually are.
- An **account summary strip**: net liquidation, buying power, and day
  realized/unrealized P/L, refreshing live.
- A **watchlist grid**: compact tiles per tracked ticker with last price,
  % change today, a mini sparkline, and a colored border (green/red) when a
  scalping signal is currently active on that ticker. Add/remove tickers
  directly from this view; click a tile to make it the selected ticker
  everywhere else on the page (chart, options panel).
- A live candlestick chart (with a volume pane below it) for the selected
  ticker, updating in real time as new bars stream in over the same
  WebSocket. Tabs above the chart switch symbols without reconnecting.
- VWAP, EMA(9), and EMA(20) overlays, each independently toggleable.
- A dashed live price line on the chart tracking the latest close.
- A **signal alerts tray** (top-right) showing recent fired signals as
  dismissible cards — click one to jump the chart (and watchlist selection)
  to that ticker.
- A **Signal alerts** settings section: enable browser push notifications,
  mute/test the audible alert, set the per-ticker/rule cooldown (default 2
  minutes), and pick which rules generate alerts at all.
- A collapsible raw table of incoming 1-minute bars, for confirming the pipe
  itself still works independent of the chart.
- An **options trading panel** for the selected ticker: near-term expiry
  picker, a live chain table (click a bid/ask to select that strike/side),
  an order form with a required confirmation dialog before anything is
  sent, and an open-positions list with live P/L and one-click close. A
  persistent banner appears whenever connected to a live account, escalating
  once you arm it. **Read the backend's "Options trading panel" section
  above before using this against a live account.**
- A **portfolio table**: the account's actual IBKR positions (not just ones
  opened through this app), in separate equities/ETFs and options sections
  — the options section additionally shows strike/expiry/delta/IV, and both
  show % of account (computed client-side from market value ÷ net
  liquidation, so it always uses whatever summary figure is freshest).
- A **trading journal**: a monthly P/L calendar (day cells colored/labeled
  by that day's realized P/L, a trailing weekly-total column per row, and a
  month-total banner above it), a win-rate/avg-win/avg-loss/largest-win/loss
  stats strip for the displayed month, and — click any day — the full list
  of that day's closed trades with entry/exit price and time, contract
  details for options, P/L, and the scalping rule (if any) that triggered
  the entry. A "Sync with IBKR" button pulls the latest execution history
  immediately on top of the automatic periodic reconciliation.

### Reconnection & stale data

Two separate connections can each drop independently, and previously
neither one showing "disconnected" changed how any price/position/P&L was
rendered — the last values just sat there, indistinguishable from live
ones. This was hardened as follows:

- `frontend/src/useBackendSocket.ts` (and every other WebSocket hook —
  `usePortfolioStream`, `usePositionsStream`, `useOptionsChainStream`,
  `useJournalStream`) already reconnects automatically on close with a
  fixed delay; that part was fine. What was missing was surfacing it.
- `frontend/src/dataFreshness.ts`'s `isDataStale(ibkrState, socketStates)`
  is the single source of truth: true if the backend's own IBKR connection
  isn't `"connected"`, *or* any of this tab's WebSocket connections to the
  backend aren't `"open"`. `App.tsx` computes this once from every socket
  state it holds and threads it into `StaleDataBanner` (page-level) and a
  `dataStale`-driven dim + `StaleBadge` on the account summary, watchlist,
  chart, and portfolio sections.
- The banner distinguishes the two failure modes with different text —
  "not connected to the backend" (this tab's WebSocket is down; the
  backend might be perfectly healthy) vs. "backend lost its IBKR
  connection" (this tab is fine; TWS/Gateway isn't) — since they imply
  different fixes (wait for this tab to reconnect, vs. check TWS itself).

```bash
cd frontend
npm run build   # tsc -b && vite build — the type-check is the fast gate here
```

There's no dedicated frontend test runner in this project yet (see
"What's not in this step"); this hardening pass was verified with a
scripted mock backend broadcasting a simulated `{"type": "status",
"state": "disconnected"}` message and a Playwright pass confirming the
banner, dimming, and "STALE" tags all appear together and clear together.

### The chart component

`frontend/src/components/CandlestickChart.tsx` is a standalone, reusable
component — it only needs `symbol` and an ascending, per-symbol `bars` array;
it doesn't know about the WebSocket or REST layer. It accepts `height`,
`showVolume`, `overlays` (`{ vwap, ema9, ema20 }`), and a `compact` flag that
trims axes/labels for small tiles, for exactly this kind of small-tile reuse
(the watchlist grid above uses a lightweight inline-SVG `Sparkline` instead
of a full chart instance per tile — one `lightweight-charts` instance per
watchlist tile would be excessive for a grid of many).

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
| `VITE_BACKEND_OPTIONS_WS_URL` | `ws://localhost:8000/ws/options` | Options chain quote WebSocket URL |
| `VITE_BACKEND_POSITIONS_WS_URL` | `ws://localhost:8000/ws/positions` | Option positions WebSocket URL |
| `VITE_BACKEND_PORTFOLIO_WS_URL` | `ws://localhost:8000/ws/portfolio` | Account positions/summary WebSocket URL |
| `VITE_BACKEND_JOURNAL_WS_URL` | `ws://localhost:8000/ws/journal` | Trading journal "new trade recorded" WebSocket URL |

## Notes on the IBKR library choice

The original `ib_insync` package is no longer maintained by its author. This
project uses **`ib_async`**, the actively maintained community fork with the
same API, so `from ib_async import IB, Stock` is a drop-in replacement for
`ib_insync` code you may find elsewhere.

## What's not in this step

- No auto-submitted bracket order for stop-loss/profit-target — crossing a
  level only flags/alerts (see "Options trading panel" above); this is an
  explicit, unimplemented stretch goal per the spec, not an oversight.
- No multi-leg option strategies (spreads, straddles, etc.) — single-leg
  calls/puts only.
- No true previous-close baseline for the watchlist's "% change today" —
  see the "Watchlist & portfolio" section's caveat.
- No persistence of bars, notifications, orders, or *open* positions (only
  what's held in memory per backend process, and in each browser's
  `localStorage`/tab memory). The relative-volume baseline, Telegram's
  cooldown, and all open positions reset on backend restart; the signal
  toast tray resets on page reload. The trading journal is the one
  exception — closed round-trip trades and the signal log they're linked
  against are persisted to SQLite and survive a restart (see "Trading
  journal" above).
- No cross-month aggregation for a calendar week that spans a month
  boundary — the journal's weekly P/L total only sums trades within
  whichever month is currently displayed (see "Trading journal" above).
- Browser push notifications need the tab open (even if unfocused/backgrounded)
  — reaching you with the tab or browser fully closed is what the optional
  Telegram integration is for, not the Notifications API.
- The kill switch never closes open positions — only cancels working
  orders and blocks new submission. Flattening a position after tripping
  it is a manual step (see "Emergency kill switch" above and `RUNBOOK.md`).
- Trading-safety state (armed/kill-switch/mismatch) is fetched once per
  tab on load and updated locally by that tab's own actions — it isn't
  pushed to other open tabs/browsers the way price/position data is. A
  kill switch engaged from one tab won't visually update a second tab
  until that tab is reloaded, even though the backend-side block applies
  immediately everywhere. Fine for the single-user use case this is built
  for; would need a WebSocket channel (like the ones prices already use)
  to matter for more than one.
- The IBKR pacing limiter is a client-side courtesy throttle tuned to
  IBKR's documented/general guidance — not a hard guarantee against every
  possible pacing violation (e.g. exceeding the account's own concurrent
  market-data-line entitlement is a different limit entirely).

These come in later steps, on top of this working data pipeline.
