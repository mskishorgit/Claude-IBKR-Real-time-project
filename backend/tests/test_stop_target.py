"""Exhaustive coverage of stop/target price computation and level-hit
checks — sign/direction bugs here are exactly the "expensive bug" the spec
warns about, so every direction x kind combination is checked explicitly.
"""

from __future__ import annotations

from app.options.models import StopTargetConfig
from app.options.stop_target import check_level_hit, compute_stop_target_prices

ENTRY = 2.00  # $2.00/share premium == $200/contract


def test_long_pct_stop_and_target():
    stop, target = compute_stop_target_prices(
        ENTRY, "long", StopTargetConfig("pct", 25), StopTargetConfig("pct", 50)
    )
    assert stop == 1.50  # 25% below entry
    assert target == 3.00  # 50% above entry


def test_short_pct_stop_and_target():
    stop, target = compute_stop_target_prices(
        ENTRY, "short", StopTargetConfig("pct", 25), StopTargetConfig("pct", 50)
    )
    assert stop == 2.50  # a short loses when price rises
    assert target == 1.00  # a short profits when price falls


def test_long_abs_stop_and_target():
    # $50/contract == $0.50/share
    stop, target = compute_stop_target_prices(
        ENTRY, "long", StopTargetConfig("abs", 50), StopTargetConfig("abs", 100)
    )
    assert stop == 1.50
    assert target == 3.00


def test_short_abs_stop_and_target():
    stop, target = compute_stop_target_prices(
        ENTRY, "short", StopTargetConfig("abs", 50), StopTargetConfig("abs", 100)
    )
    assert stop == 2.50
    assert target == 1.00


def test_stop_price_never_goes_negative():
    # A stop-loss percent >100% would otherwise compute a negative price.
    stop, _ = compute_stop_target_prices(ENTRY, "long", StopTargetConfig("pct", 150), None)
    assert stop == 0.0


def test_none_config_yields_none_price():
    stop, target = compute_stop_target_prices(ENTRY, "long", None, None)
    assert stop is None
    assert target is None


def test_check_level_hit_long_stop():
    assert check_level_hit("long", current_price=1.40, stop_price=1.50, target_price=3.00) == "stop"


def test_check_level_hit_long_target():
    assert check_level_hit("long", current_price=3.10, stop_price=1.50, target_price=3.00) == "target"


def test_check_level_hit_long_neither():
    assert check_level_hit("long", current_price=2.00, stop_price=1.50, target_price=3.00) is None


def test_check_level_hit_short_stop():
    # A short's stop triggers when price rises above the stop level.
    assert check_level_hit("short", current_price=2.60, stop_price=2.50, target_price=1.00) == "stop"


def test_check_level_hit_short_target():
    # A short's target triggers when price falls below the target level.
    assert check_level_hit("short", current_price=0.90, stop_price=2.50, target_price=1.00) == "target"


def test_check_level_hit_short_neither():
    assert check_level_hit("short", current_price=2.00, stop_price=2.50, target_price=1.00) is None


def test_check_level_hit_exact_boundary_counts_as_hit():
    # <= / >= (not strict <, >), so a level touched exactly still fires.
    assert check_level_hit("long", current_price=1.50, stop_price=1.50, target_price=None) == "stop"
    assert check_level_hit("long", current_price=3.00, stop_price=None, target_price=3.00) == "target"


def test_check_level_hit_with_no_levels_configured():
    assert check_level_hit("long", current_price=2.00, stop_price=None, target_price=None) is None
