from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from .indicators import SessionVwap
from .models import Bar

Relation = Literal["above", "below"]

# Bounds memory per symbol; must be >= the largest window any rule config uses.
MAX_BAR_HISTORY = 200
MAX_VWAP_DISTANCE_HISTORY = 50


@dataclass
class SymbolState:
    """Rolling per-symbol state the engine maintains and rules read from.

    Rules never mutate this directly — SignalEngine owns all writes, so the
    exact point in `process_bar` where "prior" history is snapshotted versus
    "current bar" is applied is unambiguous and centralized in one place.
    """

    bars: deque[Bar] = field(default_factory=lambda: deque(maxlen=MAX_BAR_HISTORY))
    vwap: SessionVwap = field(default_factory=SessionVwap)
    vwap_distance_pct_history: deque[float] = field(
        default_factory=lambda: deque(maxlen=MAX_VWAP_DISTANCE_HISTORY)
    )
    ema_fast: float | None = None
    ema_slow: float | None = None
    ema_relation: Relation | None = None
