# Runbook: running Scalp Dashboard against a live account

This is the short, operational version. For how any of this is built, see
`README.md` (in particular "Options trading panel" and "The order flow").
Read this whole document once before your first live session — not mid-emergency.

## 1. Start the app safely

Every session, in this order:

1. **Start TWS or IB Gateway first**, log in, and confirm in its own title
   bar / login screen which mode you're in — "Paper Trading" or your real
   account number. Do this visually, in TWS itself, before touching this
   app at all. This app trusts `IBKR_TRADING_MODE` in `.env`, but that's
   just a config value — it does not, by itself, know what TWS is actually
   logged into. (Section 2 below is the automated check on top of this.)
2. **Check `backend/.env`**: `IBKR_TRADING_MODE` matches what you just
   confirmed in TWS, and `IBKR_PAPER_PORT` / `IBKR_LIVE_PORT` match the API
   port TWS/Gateway is configured for (Configure → API → Settings). If
   you're not sure, leave `IBKR_TRADING_MODE=paper` — paper is always the
   safe default and the backend refuses to place a live order regardless of
   anything else until you explicitly arm it (section 3).
3. **Start the backend**, and watch its startup log for the connection
   result:
   ```bash
   cd backend
   source .venv/bin/activate
   uvicorn app.main:app --reload
   ```
4. **Start the frontend** in a second terminal:
   ```bash
   cd frontend
   npm run dev
   ```
5. **Open the dashboard** and look at the top of the page before doing
   anything else — the connection pill, and whether either of these two
   banners is showing:
   - **"Not connected to the backend"** or **"Backend lost its IBKR
     connection"** (amber) — data on the page may be stale; see section 4.
   - **"ACCOUNT/MODE MISMATCH"** (red) — `IBKR_TRADING_MODE` doesn't match
     the account IBKR actually connected to. **Stop. Do not place any
     order.** All orders are already blocked while this shows (this is the
     account/mode cross-check from the hardening pass), but fix the
     mismatch and restart the backend before doing anything else — see
     section 2.

## 2. Verify you're actually in paper mode

Don't take `.env`'s word for it — confirm it two ways, both visible without
placing any order:

1. **In TWS/Gateway itself**: the title bar/login screen says "Paper
   Trading Account" (or your account number starts with `DU`).
2. **In the dashboard**: `GET /api/trading-safety` (or just load the page)
   — reload the page and check that:
   - No **"LIVE TRADING"** banner is showing at all (that banner only
     renders when `trading_mode` is `"live"` — paper mode shows nothing
     here, on purpose).
   - No **"ACCOUNT/MODE MISMATCH"** banner is showing.

   From a terminal, the same thing:
   ```bash
   curl -s http://localhost:8000/api/trading-safety | python3 -m json.tool
   ```
   Expect `"trading_mode": "paper"`, `"live_at_risk": false`,
   `"account_mode_mismatch": false`, and `"account_id"` starting with `DU`.

If `account_mode_mismatch` is ever `true`, every order is already blocked
server-side (`check_order_allowed()` refuses regardless of paper/live) —
but treat it as a stop-and-fix signal, not a "safe to keep going" one.

## 3. Switch to live trading

This is two separate, deliberate steps — by design, neither one alone is
enough:

1. **Restart the backend with `IBKR_TRADING_MODE=live`** in `backend/.env`,
   pointed at TWS/Gateway's live API port. This alone does **not** let any
   order through — every order still hits `check_order_allowed()`, which
   blocks live orders until step 2.
2. **Arm live trading in the UI.** A red "LIVE TRADING ARMED" banner is
   the only state that allows a live order to actually reach IBKR — it's
   impossible to miss, and it stays up the whole time you're armed. Click
   "Disarm live trading" the moment you're done for the session; it does
   *not* re-lock itself automatically, so get in the habit of disarming
   before walking away.

Before your first live order: place one small preview, read the confirm
dialog's contract/quantity/side back to yourself, and only then confirm.
The preview step exists specifically so a fat-fingered contract or
quantity gets caught before it reaches IBKR, not after.

## 4. If the data looks frozen ("data may be stale")

The dashboard cannot make a lost IBKR connection reappear, so instead of
guessing, trust the banner over the numbers:

- **Amber "Not connected to the backend"**: this browser tab lost its
  WebSocket to the backend itself. Everything on the page is frozen at
  whatever it last showed. Wait — it auto-reconnects — or reload the page.
- **Amber "Backend lost its IBKR connection"**: the backend is fine, but
  TWS/Gateway isn't. Prices, positions, and account figures below are
  frozen at their last known values, not live. The backend auto-reconnects
  to TWS/Gateway on its own (see `IBKR_RECONNECT_DELAY_SECONDS`); check TWS
  itself is still running and logged in.
- Every "Stale" tag next to a section heading (Account summary, Watchlist,
  Portfolio) and the dimmed chart mean the exact same thing, localized to
  that section — they always appear together with one of the two banners
  above, never on their own.

**Do not place or judge an order based on a page showing either banner.**
Wait for it to clear (connection pill goes back to "Connected to IBKR")
before trusting anything you see.

## 5. Kill switch — emergency stop

A red **"🛑 Kill switch"** button is always visible near the top of the
page, in both paper and live mode. Use it any time you need everything to
stop *right now* and you don't have time to reason about why.

**What it does:**
- Cancels every open (working, unfilled) order on the account at the IBKR
  level — via `reqGlobalCancel`, which cancels *all* open orders on the
  account, not just ones this app placed.
- Immediately blocks every new order this app could submit (preview,
  confirm, and one-click close all go through the same check) until reset.
- If live trading was armed, disarms it as part of engaging.

**What it does NOT do:**
- It does **not** close any already-open position. Cancelling a working
  order and flattening a position are different things — flattening is
  itself a new order, and this only ever cancels unfilled ones. If you have
  open positions you want out of, you'll need to close them manually
  (either directly in TWS, or through this app's own close-position button
  — the latter is blocked while the kill switch is engaged, by the same
  gate as everything else; **reset the kill switch first** if you want to
  use the app to close a position, not TWS).
- If the backend can't currently reach IBKR, it still engages locally
  (blocks the app's own order submission) but the response tells you
  `ibkr_reachable: false` — meaning nothing could actually be cancelled
  remotely. In that case, cancel manually in TWS/Gateway directly.

**To use it:**
1. Click "🛑 Kill switch".
2. Confirm on the second prompt ("Yes, kill everything") — this is
   deliberately a two-click action so it's never triggered by accident.
3. Read the result line under the red banner: how many orders were
   cancelled, and whether IBKR was reachable.
4. When you're ready to trade again: click "Reset kill switch". This only
   lifts the order-submission block — if you were in live mode, you'll
   still need to re-arm live trading separately (section 3, step 2). That's
   intentional: coming back from an emergency stop should never be a single
   click that also silently re-arms live orders.

## Quick reference

| Situation | What to check | Where |
|---|---|---|
| "Am I in paper mode?" | `trading_mode: "paper"`, no LIVE banner | `GET /api/trading-safety`, top of page |
| "Is this really the account I think it is?" | `account_id` starts with `DU` for paper | `GET /api/trading-safety` |
| "Is what I'm looking at live?" | No amber stale banner, connection pill green | Top of page |
| "Something's wrong, stop everything" | Kill switch button | Top of page, always visible |
