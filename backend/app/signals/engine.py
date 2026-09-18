"""Rule-based scalping signal engine.

Runs entirely off finalized bars (never partial/forming ones — see
MarketDataManager's bar-closed listener) and has no dependency on
FastAPI/WebSocket/ib_async: feed it Bar objects, get back Signal objects.
This is exactly what both the live server and the CSV/IBKR-export backtest
CLI run, so "what would have fired historically" and "what fires live" are
guaranteed to be the same code path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .indicators import ema_next
from .models import Bar, Signal
from .relative_volume import RelativeVolumeTracker
from .rules import Rule, RelativeVolumeFilter, RuleContext
from .state import SymbolState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmaPeriods:
    fast: int = 9
    slow: int = 20


class SignalEngine:
    def __init__(
        self,
        rules: list[Rule],
        *,
        ema_periods: EmaPeriods | None = None,
        relative_volume_tracker: RelativeVolumeTracker | None = None,
        relative_volume_filter: RelativeVolumeFilter | None = None,
    ) -> None:
        self._rules = rules
        self._ema_periods = ema_periods or EmaPeriods()
        self._relative_volume = relative_volume_tracker or RelativeVolumeTracker()
        self._relative_volume_filter = relative_volume_filter or RelativeVolumeFilter()
        self._states: dict[str, SymbolState] = {}

    @property
    def rules(self) -> list[Rule]:
        return self._rules

    def reset_symbol(self, symbol: str) -> None:
        """Drop rolling state for a symbol, e.g. once it's no longer tracked."""
        self._states.pop(symbol, None)

    def process_bar(self, bar: Bar) -> list[Signal]:
        state = self._states.setdefault(bar.symbol, SymbolState())

        prior_bars = list(state.bars)
        prior_vwap_distance_pct = list(state.vwap_distance_pct_history)

        vwap_value = state.vwap.update(bar)
        current_distance_pct = (bar.close - vwap_value) / vwap_value * 100 if vwap_value else 0.0

        prev_ema_relation = state.ema_relation
        state.ema_fast = ema_next(state.ema_fast, bar.close, self._ema_periods.fast)
        state.ema_slow = ema_next(state.ema_slow, bar.close, self._ema_periods.slow)
        ema_relation = "above" if state.ema_fast >= state.ema_slow else "below"

        relative_volume = self._relative_volume.update(bar)

        ctx = RuleContext(
            bar=bar,
            prior_bars=prior_bars,
            vwap=vwap_value,
            prior_vwap_distance_pct=prior_vwap_distance_pct,
            ema_fast=state.ema_fast,
            ema_slow=state.ema_slow,
            ema_relation=ema_relation,
            prev_ema_relation=prev_ema_relation,
            relative_volume=relative_volume,
        )

        signals: list[Signal] = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            try:
                signal = rule.evaluate(ctx)
            except Exception:
                logger.exception("Rule %s raised while evaluating %s", rule.name, bar.symbol)
                continue
            if signal is None:
                continue
            if not self._relative_volume_filter.passes(relative_volume):
                continue
            signals.append(signal)

        state.bars.append(bar)
        state.vwap_distance_pct_history.append(current_distance_pct)
        state.ema_relation = ema_relation

        return signals
