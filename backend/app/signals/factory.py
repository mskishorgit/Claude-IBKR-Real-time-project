"""Builds a SignalEngine from plain keyword arguments.

Deliberately takes primitives rather than the app's pydantic Settings object,
so this stays usable from the backtest CLI (and tests) without constructing
a full FastAPI app. main.py calls this passing settings.signals_* fields;
the backtest CLI calls it with argparse-provided overrides or defaults.
"""

from __future__ import annotations

from .engine import EmaPeriods, SignalEngine
from .relative_volume import RelativeVolumeTracker
from .rules import EmaCrossRule, RelativeVolumeFilter, VolumeSpikeBreakoutRule, VwapReclaimRule


def build_default_engine(
    *,
    vwap_reclaim_enabled: bool = True,
    vwap_extension_pct: float = 0.15,
    vwap_lookback_bars: int = 5,
    vwap_volume_window: int = 20,
    vwap_volume_multiplier: float = 1.2,
    ema_cross_enabled: bool = True,
    ema_fast_period: int = 9,
    ema_slow_period: int = 20,
    ema_volume_multiplier: float = 1.1,
    volume_spike_enabled: bool = True,
    volume_spike_window: int = 20,
    volume_spike_std_dev_threshold: float = 2.0,
    volume_spike_breakout_lookback_bars: int = 20,
    relative_volume_filter_enabled: bool = True,
    relative_volume_min_ratio: float = 1.0,
    relative_volume_min_sessions: int = 1,
    relative_volume_max_sessions_tracked: int = 20,
) -> SignalEngine:
    rules = [
        VwapReclaimRule(
            enabled=vwap_reclaim_enabled,
            extension_pct=vwap_extension_pct,
            lookback_bars=vwap_lookback_bars,
            volume_window=vwap_volume_window,
            volume_multiplier=vwap_volume_multiplier,
        ),
        EmaCrossRule(
            enabled=ema_cross_enabled,
            volume_multiplier=ema_volume_multiplier,
        ),
        VolumeSpikeBreakoutRule(
            enabled=volume_spike_enabled,
            volume_window=volume_spike_window,
            std_dev_threshold=volume_spike_std_dev_threshold,
            breakout_lookback_bars=volume_spike_breakout_lookback_bars,
        ),
    ]
    return SignalEngine(
        rules=rules,
        ema_periods=EmaPeriods(fast=ema_fast_period, slow=ema_slow_period),
        relative_volume_tracker=RelativeVolumeTracker(
            max_sessions=relative_volume_max_sessions_tracked
        ),
        relative_volume_filter=RelativeVolumeFilter(
            enabled=relative_volume_filter_enabled,
            min_ratio=relative_volume_min_ratio,
            min_sessions_required=relative_volume_min_sessions,
        ),
    )
