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
"""

from __future__ import annotations

from dataclasses import dataclass


class LiveTradingNotArmedError(Exception):
    pass


@dataclass
class TradingSafety:
    trading_mode: str  # "paper" | "live"
    live_armed: bool = False

    def set_armed(self, armed: bool) -> None:
        self.live_armed = armed

    def check_order_allowed(self) -> None:
        if self.trading_mode == "paper":
            return
        if not self.live_armed:
            raise LiveTradingNotArmedError(
                "Connected to a LIVE IBKR account, but live trading is not "
                "armed. Enable the live-trading toggle to submit real orders."
            )

    def status(self) -> dict:
        return {
            "trading_mode": self.trading_mode,
            "live_armed": self.live_armed,
            "live_at_risk": self.trading_mode == "live" and self.live_armed,
        }
