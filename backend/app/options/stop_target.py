"""Stop-loss / profit-target math, kept separate and pure so it's easy to
unit test exhaustively — this is exactly the kind of sign/direction logic
where a bug is expensive, so every branch is explicit rather than clever.

This computes *alert* levels only. Per the spec, auto-submitting a bracket
order to enforce these is an unimplemented stretch goal (see README) —
crossing a level here only flags/notifies; it never places an order itself.
"""

from __future__ import annotations

from typing import Literal, Optional

from .models import OPTION_MULTIPLIER, Direction, StopTargetConfig


def _move_amount(cfg: StopTargetConfig, entry_price: float) -> float:
    """The absolute premium-per-share move `cfg` represents, given the
    entry price (needed to turn a percent config into a dollar amount)."""
    if cfg.kind == "abs":
        return cfg.value / OPTION_MULTIPLIER
    return entry_price * (cfg.value / 100)


def compute_stop_target_prices(
    entry_price: float,
    direction: Direction,
    stop_loss: Optional[StopTargetConfig],
    profit_target: Optional[StopTargetConfig],
) -> tuple[Optional[float], Optional[float]]:
    """Returns (stop_price, target_price) as option premium-per-share
    levels, or None for whichever wasn't configured."""
    stop_price: Optional[float] = None
    if stop_loss is not None:
        move = _move_amount(stop_loss, entry_price)
        if direction == "long":
            stop_price = entry_price - move
        else:
            stop_price = entry_price + move
        stop_price = max(0.0, stop_price)

    target_price: Optional[float] = None
    if profit_target is not None:
        move = _move_amount(profit_target, entry_price)
        if direction == "long":
            target_price = entry_price + move
        else:
            target_price = entry_price - move
        target_price = max(0.0, target_price)

    return stop_price, target_price


def check_level_hit(
    direction: Direction,
    current_price: float,
    stop_price: Optional[float],
    target_price: Optional[float],
) -> Optional[Literal["stop", "target"]]:
    """Which level (if either) `current_price` has crossed. Callers are
    responsible for latching so this isn't re-reported every tick — see
    OptionPosition.stop_alert_fired/target_alert_fired."""
    if direction == "long":
        if stop_price is not None and current_price <= stop_price:
            return "stop"
        if target_price is not None and current_price >= target_price:
            return "target"
    else:
        if stop_price is not None and current_price >= stop_price:
            return "stop"
        if target_price is not None and current_price <= target_price:
            return "target"
    return None
