"""The one gate every order-placing call in this app must pass through.

`trading_mode` ("paper" or "live") is fixed for the process's lifetime —
it comes from IBKR_TRADING_MODE in .env, same as the rest of this project's
connection setup, and mirrors which port/account TWS is actually connected
to. Reconnecting to a different account mid-session isn't supported (or
asked for) — that's a restart, same as everywhere else in this app.

`live_armed` is a separate, in-memory, runtime-only flag defaulting to
False. When `trading_mode` is "paper", every order is inherently safe and
this flag doesn't matter. When `trading_mode` is "live", an order is
blocked unless a human has explicitly flipped `live_armed` on via the UI —
this is the "paper by default, live needs explicit + visible opt-in" gate
the spec asks for, checked at both preview and confirm time.

Two more checks were added in a hardening pass and are just as load-bearing
as the two above — `check_order_allowed()` is the single choke point all
four go through, and every `ib.placeOrder` call site in this app calls it
immediately before placing an order (see app/options/orders.py):

- **Account/mode cross-check.** `trading_mode` is only ever what the .env
  file *says* — nothing before this pass verified it against what account
  IBKR actually connected the process to. A TWS/Gateway port misconfigured
  to point `IBKR_TRADING_MODE=paper` at a real account would otherwise let
  "paper" orders hit real money with this app never noticing. IBKR paper
  accounts are always "DU"-prefixed; live accounts never are, so a mismatch
  here is caught and every order is refused until it's resolved — even in
  "paper" mode, which previously skipped every check unconditionally.
- **Kill switch.** A separate, always-checked-first flag a human can trip
  from the UI in an emergency; see KillSwitchService below for what tripping
  it actually does. Reset requires an explicit, separate action — it never
  clears itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ib_async import IB

logger = logging.getLogger(__name__)

# IBKR paper/demo account ids are always prefixed this way; a live account
# never is. Used only to sanity-check the declared trading_mode against
# reality — never to derive trading_mode itself.
PAPER_ACCOUNT_PREFIXES = ("DU",)


class LiveTradingNotArmedError(Exception):
    pass


class TradingHaltedError(Exception):
    """Raised by check_order_allowed() for the kill switch and the
    account/mode mismatch check — both unconditional, checked before (and
    regardless of) trading_mode/live_armed."""


@dataclass
class TradingSafety:
    trading_mode: str  # "paper" | "live"
    live_armed: bool = False
    kill_switch_engaged: bool = False
    account_id: Optional[str] = None

    def set_armed(self, armed: bool) -> None:
        self.live_armed = armed

    def set_account(self, account_id: str) -> None:
        """Called as soon as IBKR reports which account this session is
        actually connected to (see PortfolioService), so
        account_mode_mismatch() below has something to check against."""
        if account_id and account_id != self.account_id:
            self.account_id = account_id
            if self.account_mode_mismatch():
                logger.error(
                    "TRADING MODE MISMATCH: configured trading_mode=%r but connected "
                    "account %r does not look like it matches. All orders are blocked "
                    "until this is resolved.",
                    self.trading_mode,
                    account_id,
                )

    def account_mode_mismatch(self) -> bool:
        """True if the account IBKR actually connected us to doesn't match
        IBKR_TRADING_MODE — e.g. .env says "paper" but TWS/Gateway is
        logged into a real account on that port. Returns False (not
        "safe" — just "unknown") until an account id has been reported at
        all, since there's nothing to cross-check yet at that point."""
        if not self.account_id:
            return False
        looks_paper = self.account_id.upper().startswith(PAPER_ACCOUNT_PREFIXES)
        return looks_paper != (self.trading_mode == "paper")

    def check_order_allowed(self) -> None:
        if self.kill_switch_engaged:
            raise TradingHaltedError(
                "Kill switch is engaged — no orders can be submitted until it's reset."
            )
        if self.account_mode_mismatch():
            raise TradingHaltedError(
                f"Connected account {self.account_id!r} does not look like it matches "
                f"the configured trading mode ({self.trading_mode!r}). Refusing to "
                "submit any order until this is resolved — check IBKR_TRADING_MODE in "
                ".env against which account TWS/Gateway is actually logged into."
            )
        if self.trading_mode == "paper":
            return
        if not self.live_armed:
            raise LiveTradingNotArmedError(
                "Connected to a LIVE IBKR account, but live trading is not "
                "armed. Enable the live-trading toggle to submit real orders."
            )

    def trip_kill_switch(self) -> None:
        """Blocks every order-placing call immediately (see
        check_order_allowed) and drops live_armed so a bare reset can't
        silently leave live trading armed with no further human action."""
        self.kill_switch_engaged = True
        self.live_armed = False

    def reset_kill_switch(self) -> None:
        """Only lifts the order-submission block. Live trading (if
        applicable) still needs to be re-armed separately — deliberately
        two actions, not one."""
        self.kill_switch_engaged = False

    def status(self) -> dict:
        return {
            "trading_mode": self.trading_mode,
            "live_armed": self.live_armed,
            "live_at_risk": self.trading_mode == "live" and self.live_armed,
            "kill_switch_engaged": self.kill_switch_engaged,
            "account_id": self.account_id,
            "account_mode_mismatch": self.account_mode_mismatch(),
        }


class KillSwitchService:
    """Cancels every currently open order at the IBKR API level — via
    `reqGlobalCancel`, which cancels *all* working orders on the account
    regardless of which client placed them, not just ones this app itself
    submitted — and engages TradingSafety's kill switch so no further order
    can be submitted through this app until a human explicitly resets it.

    Deliberately does NOT close open positions: flattening a position is
    itself a new order, and "cancel all open orders" (the spec's wording)
    only ever means unfilled/working orders. See the runbook for what to do
    about resting positions after tripping this.
    """

    def __init__(self, ib: "IB", safety: TradingSafety) -> None:
        self.ib = ib
        self.safety = safety

    def engage(self) -> dict:
        ibkr_reachable = self.ib.isConnected()
        cancelled = 0
        if ibkr_reachable:
            open_trades = list(self.ib.openTrades())
            for trade in open_trades:
                try:
                    self.ib.cancelOrder(trade.order)
                except Exception:
                    logger.exception(
                        "cancelOrder raised for order %s during kill switch engage",
                        trade.order.orderId,
                    )
            self.ib.reqGlobalCancel()
            cancelled = len(open_trades)

        self.safety.trip_kill_switch()
        logger.warning(
            "KILL SWITCH ENGAGED (ibkr_reachable=%s, %d open order(s) cancelled) — "
            "all new order submission is blocked until it's reset",
            ibkr_reachable,
            cancelled,
        )
        return {"cancelled_orders": cancelled, "ibkr_reachable": ibkr_reachable}

    def reset(self) -> None:
        self.safety.reset_kill_switch()
        logger.warning(
            "Kill switch reset — order submission re-enabled (live trading, if "
            "applicable, still requires re-arming separately)"
        )
