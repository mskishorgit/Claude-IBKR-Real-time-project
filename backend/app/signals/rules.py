"""Named, independently-configurable scalping entry rules.

Each rule is a small dataclass: given a RuleContext (the bar that just
closed plus the indicator/history state computed for it), it decides
whether to fire a Signal. Rules are pure/stateless — SignalEngine owns and
updates all rolling state (SymbolState) and hands rules a read-only snapshot
via RuleContext, so a rule can be unit-tested with a hand-built context and
no engine at all.

Every rule has an `enabled` flag and tunable thresholds with sensible
defaults, per the requirement that this not be a single hardcoded strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .indicators import mean_std
from .models import Bar, Direction, Signal
from .relative_volume import RelativeVolumeReading
from .state import Relation


@dataclass(frozen=True, slots=True)
class RuleContext:
    bar: Bar
    """Bars strictly before `bar`, oldest to newest (bounded history)."""
    prior_bars: list[Bar]
    """This bar's VWAP value."""
    vwap: float
    """(close-vwap)/vwap*100 for each bar in prior_bars, same order."""
    prior_vwap_distance_pct: list[float]
    ema_fast: float
    ema_slow: float
    ema_relation: Relation
    prev_ema_relation: Relation | None
    relative_volume: RelativeVolumeReading


class Rule(Protocol):
    name: str
    enabled: bool

    def evaluate(self, ctx: RuleContext) -> Signal | None: ...


@dataclass
class VwapReclaimRule:
    """Rule 1: VWAP reclaim/rejection.

    Price was extended away from VWAP (by `extension_pct`, for at least
    `lookback_bars` consecutive prior bars) and this bar closes back on the
    other side of VWAP, on above-average volume.
    Extended below -> closes above VWAP: bullish reclaim (long).
    Extended above -> closes below VWAP: bearish rejection (short).
    """

    name: str = "vwap_reclaim"
    enabled: bool = True
    extension_pct: float = 0.15
    lookback_bars: int = 5
    volume_window: int = 20
    volume_multiplier: float = 1.2

    def evaluate(self, ctx: RuleContext) -> Signal | None:
        if len(ctx.prior_vwap_distance_pct) < self.lookback_bars:
            return None

        recent = ctx.prior_vwap_distance_pct[-self.lookback_bars :]
        extended_below = all(d <= -self.extension_pct for d in recent)
        extended_above = all(d >= self.extension_pct for d in recent)
        if not extended_below and not extended_above:
            return None

        current_distance_pct = (ctx.bar.close - ctx.vwap) / ctx.vwap * 100 if ctx.vwap else 0.0

        direction: Direction | None = None
        if extended_below and current_distance_pct > 0:
            direction = "long"
        elif extended_above and current_distance_pct < 0:
            direction = "short"
        if direction is None:
            return None

        volumes = [b.volume for b in ctx.prior_bars[-self.volume_window :]]
        avg_volume, _ = mean_std(volumes)
        if avg_volume <= 0 or ctx.bar.volume < avg_volume * self.volume_multiplier:
            return None

        return Signal(
            ticker=ctx.bar.symbol,
            rule=self.name,
            direction=direction,
            price=ctx.bar.close,
            volume=ctx.bar.volume,
            timestamp=ctx.bar.timestamp,
            details={
                "vwap": round(ctx.vwap, 4),
                "distance_pct": round(current_distance_pct, 4),
                "avg_volume": round(avg_volume, 2),
                "relative_volume": ctx.relative_volume.ratio,
            },
        )


@dataclass
class EmaCrossRule:
    """Rule 2: EMA9/EMA20 momentum flip.

    Fast EMA crosses the slow EMA (in either direction) on rising volume,
    i.e. this bar's volume exceeds the previous bar's by `volume_multiplier`.
    """

    name: str = "ema_cross"
    enabled: bool = True
    volume_multiplier: float = 1.1

    def evaluate(self, ctx: RuleContext) -> Signal | None:
        if ctx.prev_ema_relation is None or ctx.prev_ema_relation == ctx.ema_relation:
            return None

        direction: Direction = "long" if ctx.ema_relation == "above" else "short"

        if not ctx.prior_bars:
            return None
        previous_volume = ctx.prior_bars[-1].volume
        if previous_volume <= 0 or ctx.bar.volume < previous_volume * self.volume_multiplier:
            return None

        return Signal(
            ticker=ctx.bar.symbol,
            rule=self.name,
            direction=direction,
            price=ctx.bar.close,
            volume=ctx.bar.volume,
            timestamp=ctx.bar.timestamp,
            details={
                "ema_fast": round(ctx.ema_fast, 4),
                "ema_slow": round(ctx.ema_slow, 4),
                "previous_volume": previous_volume,
                "relative_volume": ctx.relative_volume.ratio,
            },
        )


@dataclass
class VolumeSpikeBreakoutRule:
    """Rule 3: volume spike breakout.

    This bar's volume is `std_dev_threshold` standard deviations above the
    rolling mean over `volume_window` prior bars, AND this bar breaks the
    high or low of the prior `breakout_lookback_bars` bars.

    The spec names both the std-dev multiplier and the breakout lookback "N"
    in prose, but they are independent knobs here (a volatility multiplier
    and a bar-count window are different units) — kept separately
    configurable rather than forced to share one value.
    """

    name: str = "volume_spike_breakout"
    enabled: bool = True
    volume_window: int = 20
    std_dev_threshold: float = 2.0
    breakout_lookback_bars: int = 20

    def evaluate(self, ctx: RuleContext) -> Signal | None:
        needed = max(self.volume_window, self.breakout_lookback_bars)
        if len(ctx.prior_bars) < needed:
            return None

        volumes = [b.volume for b in ctx.prior_bars[-self.volume_window :]]
        avg_volume, std_volume = mean_std(volumes)
        if std_volume <= 0:
            return None
        volume_z_score = (ctx.bar.volume - avg_volume) / std_volume
        if volume_z_score < self.std_dev_threshold:
            return None

        breakout_bars = ctx.prior_bars[-self.breakout_lookback_bars :]
        prior_high = max(b.high for b in breakout_bars)
        prior_low = min(b.low for b in breakout_bars)

        direction: Direction | None = None
        if ctx.bar.high > prior_high:
            direction = "long"
        elif ctx.bar.low < prior_low:
            direction = "short"
        if direction is None:
            return None

        return Signal(
            ticker=ctx.bar.symbol,
            rule=self.name,
            direction=direction,
            price=ctx.bar.close,
            volume=ctx.bar.volume,
            timestamp=ctx.bar.timestamp,
            details={
                "volume_avg": round(avg_volume, 2),
                "volume_std": round(std_volume, 2),
                "volume_z_score": round(volume_z_score, 2),
                "prior_high": prior_high,
                "prior_low": prior_low,
                "relative_volume": ctx.relative_volume.ratio,
            },
        )


@dataclass
class RelativeVolumeFilter:
    """Rule 4: relative-volume-by-time-of-day filter.

    Not an independent entry trigger — a gate applied to the other three
    rules' candidate signals. Suppresses a signal unless today's cumulative
    volume pace, at this bar's time of day, is at least `min_ratio` times
    the average pace observed at the same time of day across prior sessions.
    While fewer than `min_sessions_required` sessions have been observed for
    a symbol, the filter does not block (there isn't enough history yet to
    judge "elevated"), so it can be turned on from a cold start without
    silently gating everything.
    """

    name: str = "relative_volume_filter"
    enabled: bool = True
    min_ratio: float = 1.0
    min_sessions_required: int = 1

    def passes(self, reading: RelativeVolumeReading) -> bool:
        if not self.enabled:
            return True
        if reading.ratio is None or reading.sessions_observed < self.min_sessions_required:
            return True
        return reading.ratio >= self.min_ratio
