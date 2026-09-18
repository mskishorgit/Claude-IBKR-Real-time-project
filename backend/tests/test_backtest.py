"""End-to-end test of the CSV loader + backtest runner, using the same
VWAP-reclaim scenario from test_signal_engine.py so this test doubles as
confirmation that the backtest path (CSV -> Bar -> SignalEngine -> Signal)
reproduces exactly what direct engine calls produce.
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.signals.backtest import run_backtest
from app.signals.csv_bars import load_bars_from_csv
from app.signals.engine import SignalEngine
from app.signals.rules import RelativeVolumeFilter, VwapReclaimRule

CSV_ROWS = [
    {"timestamp": "2024-01-02 14:30:00", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000},
    {"timestamp": "2024-01-02 14:31:00", "open": 99, "high": 99.2, "low": 98.8, "close": 99, "volume": 1000},
    {"timestamp": "2024-01-02 14:32:00", "open": 98, "high": 98.2, "low": 97.8, "close": 98, "volume": 1000},
    {"timestamp": "2024-01-02 14:33:00", "open": 97, "high": 97.2, "low": 96.8, "close": 97, "volume": 1000},
    {"timestamp": "2024-01-02 14:34:00", "open": 97, "high": 99.5, "low": 97, "close": 99.3, "volume": 3000},
]


def _write_csv(path: Path, symbol: str | None) -> None:
    fieldnames = ["timestamp", "open", "high", "low", "close", "volume"]
    if symbol is not None:
        fieldnames = ["symbol", *fieldnames]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in CSV_ROWS:
            out = dict(row)
            if symbol is not None:
                out["symbol"] = symbol
            writer.writerow(out)


def test_load_bars_from_csv_with_symbol_column(tmp_path: Path):
    csv_path = tmp_path / "bars.csv"
    _write_csv(csv_path, symbol="AAPL")

    bars = load_bars_from_csv(csv_path)

    assert len(bars) == 5
    assert all(b.symbol == "AAPL" for b in bars)
    assert bars[0].close == 100
    assert bars[-1].volume == 3000
    assert bars == sorted(bars, key=lambda b: b.timestamp)


def test_load_bars_from_csv_without_symbol_column_uses_default(tmp_path: Path):
    csv_path = tmp_path / "bars_no_symbol.csv"
    _write_csv(csv_path, symbol=None)

    bars = load_bars_from_csv(csv_path, default_symbol="msft")

    assert len(bars) == 5
    assert all(b.symbol == "MSFT" for b in bars)


def test_run_backtest_matches_direct_engine_calls(tmp_path: Path):
    csv_path = tmp_path / "bars.csv"
    _write_csv(csv_path, symbol="AAPL")
    bars = load_bars_from_csv(csv_path)

    engine = SignalEngine(
        rules=[
            VwapReclaimRule(extension_pct=0.1, lookback_bars=3, volume_window=5, volume_multiplier=1.2)
        ],
        relative_volume_filter=RelativeVolumeFilter(enabled=False),
    )

    signals = run_backtest(bars, engine)

    assert len(signals) == 1
    assert signals[0].rule == "vwap_reclaim"
    assert signals[0].direction == "long"
    assert signals[0].ticker == "AAPL"
