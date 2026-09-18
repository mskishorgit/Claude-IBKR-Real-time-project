"""Unit tests for the signal engine — each test isolates one rule (or the
relative-volume gate) with a hand-built, deterministic bar sequence, so
these serve as the "sanity check on rule quality" the engine itself is for,
one level down.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.signals.engine import EmaPeriods, SignalEngine
from app.signals.factory import build_default_engine
from app.signals.indicators import mean_std
from app.signals.models import Bar
from app.signals.rules import (
    EmaCrossRule,
    RelativeVolumeFilter,
    VolumeSpikeBreakoutRule,
    VwapReclaimRule,
)

SYMBOL = "TEST"
BASE = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


def bar(minute_offset: int, o: float, h: float, l: float, c: float, v: float, day_offset: int = 0) -> Bar:
    return Bar(
        symbol=SYMBOL,
        timestamp=BASE + timedelta(days=day_offset, minutes=minute_offset),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def test_ema_cross_fires_long_on_flip_with_rising_volume():
    engine = SignalEngine(
        rules=[EmaCrossRule(volume_multiplier=1.1)],
        ema_periods=EmaPeriods(fast=2, slow=3),
        relative_volume_filter=RelativeVolumeFilter(enabled=False),
    )

    closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 105]
    signals = []
    for i, close in enumerate(closes):
        volume = 1000 if i < len(closes) - 1 else 5000
        signals.extend(engine.process_bar(bar(i, close, close + 0.5, close - 0.5, close, volume)))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.rule == "ema_cross"
    assert signal.direction == "long"
    assert signal.ticker == SYMBOL


def test_ema_cross_does_not_fire_without_rising_volume():
    engine = SignalEngine(
        rules=[EmaCrossRule(volume_multiplier=1.1)],
        ema_periods=EmaPeriods(fast=2, slow=3),
        relative_volume_filter=RelativeVolumeFilter(enabled=False),
    )

    closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 105]
    signals = []
    for i, close in enumerate(closes):
        # Flat volume throughout, including the flip bar -> "rising volume"
        # requirement is never satisfied.
        signals.extend(engine.process_bar(bar(i, close, close + 0.5, close - 0.5, close, 1000)))

    assert signals == []


def test_vwap_reclaim_fires_long_after_extended_below_move_on_volume():
    engine = SignalEngine(
        rules=[
            VwapReclaimRule(extension_pct=0.1, lookback_bars=3, volume_window=5, volume_multiplier=1.2)
        ],
        relative_volume_filter=RelativeVolumeFilter(enabled=False),
    )

    bars = [
        bar(0, 100, 100, 100, 100, 1000),
        bar(1, 99, 99.2, 98.8, 99, 1000),
        bar(2, 98, 98.2, 97.8, 98, 1000),
        bar(3, 97, 97.2, 96.8, 97, 1000),
        bar(4, 97, 99.5, 97, 99.3, 3000),  # reclaim bar: closes back above VWAP on a volume spike
    ]

    signals = []
    for b in bars:
        signals.extend(engine.process_bar(b))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.rule == "vwap_reclaim"
    assert signal.direction == "long"
    assert signal.price == 99.3
    assert signal.details["vwap"] < signal.price


def test_vwap_reclaim_does_not_fire_without_prior_extension():
    engine = SignalEngine(
        rules=[
            VwapReclaimRule(extension_pct=0.1, lookback_bars=3, volume_window=5, volume_multiplier=1.2)
        ],
        relative_volume_filter=RelativeVolumeFilter(enabled=False),
    )

    # Price hovers near VWAP the whole time -> never "extended" -> no reclaim to speak of.
    bars = [
        bar(0, 100, 100.1, 99.9, 100, 1000),
        bar(1, 100, 100.1, 99.9, 100.02, 1000),
        bar(2, 100, 100.1, 99.9, 99.98, 1000),
        bar(3, 100, 100.1, 99.9, 100.01, 1000),
        bar(4, 100, 100.6, 99.9, 100.5, 3000),
    ]

    signals = []
    for b in bars:
        signals.extend(engine.process_bar(b))

    assert signals == []


def test_volume_spike_breakout_fires_long_on_spike_and_high_break():
    volumes = [100, 110, 90, 105, 95]
    avg, std = mean_std(volumes)
    spike_volume = avg + 3 * std  # comfortably above the 2.0 std-dev threshold

    engine = SignalEngine(
        rules=[
            VolumeSpikeBreakoutRule(volume_window=5, std_dev_threshold=2.0, breakout_lookback_bars=5)
        ],
        relative_volume_filter=RelativeVolumeFilter(enabled=False),
    )

    signals = []
    for i, v in enumerate(volumes):
        signals.extend(engine.process_bar(bar(i, 50, 51, 49, 50, v)))
    # Breakout bar: high clears the prior 5-bar high (51), volume is the spike.
    signals.extend(engine.process_bar(bar(5, 50, 55, 50, 54, spike_volume)))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.rule == "volume_spike_breakout"
    assert signal.direction == "long"
    assert signal.details["volume_z_score"] >= 2.0


def test_volume_spike_breakout_does_not_fire_without_breakout():
    volumes = [100, 110, 90, 105, 95]
    avg, std = mean_std(volumes)
    spike_volume = avg + 3 * std

    engine = SignalEngine(
        rules=[
            VolumeSpikeBreakoutRule(volume_window=5, std_dev_threshold=2.0, breakout_lookback_bars=5)
        ],
        relative_volume_filter=RelativeVolumeFilter(enabled=False),
    )

    signals = []
    for i, v in enumerate(volumes):
        signals.extend(engine.process_bar(bar(i, 50, 51, 49, 50, v)))
    # Big volume spike, but high/low stay inside the prior range -> no breakout.
    signals.extend(engine.process_bar(bar(5, 50, 50.5, 49.5, 50, spike_volume)))

    assert signals == []


def test_relative_volume_filter_suppresses_signal_below_threshold():
    def make_engine(filter_enabled: bool) -> SignalEngine:
        return SignalEngine(
            rules=[EmaCrossRule(volume_multiplier=1.1)],
            ema_periods=EmaPeriods(fast=2, slow=3),
            relative_volume_filter=RelativeVolumeFilter(
                enabled=filter_enabled, min_ratio=2.0, min_sessions_required=1
            ),
        )

    def day1_bars() -> list[Bar]:
        # Establishes the relative-volume baseline: steady volume, flat price
        # (no EMA flip expected or needed on day 1).
        return [bar(i, 100, 100.2, 99.8, 100, 1000, day_offset=0) for i in range(12)]

    def day2_bars() -> list[Bar]:
        # Same time-of-day minutes as day 1, but at 1/10th the volume pace ->
        # relative volume well under the 2.0 threshold. The last bar still
        # satisfies EmaCrossRule's own "rising vs previous bar" volume check
        # (150 >= 1.1 * 100) and a genuine EMA flip, in isolation from the
        # overall-pace gate this test is actually about.
        closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 105]
        bars = []
        for i, close in enumerate(closes):
            volume = 100 if i < len(closes) - 1 else 150
            bars.append(bar(i, close, close + 0.5, close - 0.5, close, volume, day_offset=1))
        return bars

    filtered_engine = make_engine(filter_enabled=True)
    for b in day1_bars():
        filtered_engine.process_bar(b)
    day2_signals_filtered = []
    for b in day2_bars():
        day2_signals_filtered.extend(filtered_engine.process_bar(b))

    unfiltered_engine = make_engine(filter_enabled=False)
    for b in day1_bars():
        unfiltered_engine.process_bar(b)
    day2_signals_unfiltered = []
    for b in day2_bars():
        day2_signals_unfiltered.extend(unfiltered_engine.process_bar(b))

    assert day2_signals_filtered == []
    assert len(day2_signals_unfiltered) == 1
    assert day2_signals_unfiltered[0].rule == "ema_cross"


def test_build_default_engine_wires_all_four_rules_and_respects_enabled_flags():
    engine = build_default_engine(ema_cross_enabled=False)
    rule_names = {rule.name: rule for rule in engine.rules}
    assert set(rule_names) == {"vwap_reclaim", "ema_cross", "volume_spike_breakout"}
    assert rule_names["ema_cross"].enabled is False
    assert rule_names["vwap_reclaim"].enabled is True
