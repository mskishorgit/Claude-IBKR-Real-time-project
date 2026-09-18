"""Backtest the signal engine over historical bars (CSV or IBKR export).

Runs the exact same rule engine used live over historical data and reports
every bar that would have fired a signal, so rule quality and thresholds can
be sanity-checked before trusting the live alerts.

Usage:
    python -m app.signals.backtest --csv path/to/bars.csv
    python -m app.signals.backtest --csv path/to/bars.csv --symbol AAPL --out signals.csv
"""

from __future__ import annotations

import argparse
import csv as csv_module
import json
import sys
from pathlib import Path
from typing import Iterable

from .csv_bars import load_bars_from_csv
from .engine import SignalEngine
from .factory import build_default_engine
from .models import Bar, Signal


def run_backtest(bars: Iterable[Bar], engine: SignalEngine) -> list[Signal]:
    """Feed bars through the engine in order, returning every fired signal."""
    signals: list[Signal] = []
    for bar in bars:
        signals.extend(engine.process_bar(bar))
    return signals


def _write_signals_csv(signals: list[Signal], path: Path) -> None:
    with path.open("w", newline="") as f:
        writer = csv_module.writer(f)
        writer.writerow(["timestamp", "ticker", "rule", "direction", "price", "volume", "details"])
        for signal in signals:
            writer.writerow(
                [
                    signal.timestamp.isoformat(),
                    signal.ticker,
                    signal.rule,
                    signal.direction,
                    signal.price,
                    signal.volume,
                    json.dumps(signal.details),
                ]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="Path to a CSV of historical OHLCV bars")
    parser.add_argument(
        "--symbol",
        help="Symbol to use for every row, if the CSV has no symbol/ticker column",
    )
    parser.add_argument("--out", help="Optional path to write fired signals as CSV")
    args = parser.parse_args(argv)

    try:
        bars = load_bars_from_csv(args.csv, default_symbol=args.symbol)
    except (ValueError, OSError) as exc:
        print(f"Failed to load bars: {exc}", file=sys.stderr)
        return 1

    if not bars:
        print("No bars found in CSV.", file=sys.stderr)
        return 1

    engine = build_default_engine()
    signals = run_backtest(bars, engine)

    print(f"Processed {len(bars)} bars, {len(signals)} signal(s) fired.\n")
    for signal in signals:
        print(
            f"{signal.timestamp.isoformat()}  {signal.ticker:<8} {signal.rule:<24} "
            f"{signal.direction:<5} price={signal.price} volume={signal.volume}"
        )

    if args.out:
        _write_signals_csv(signals, Path(args.out))
        print(f"\nWrote {len(signals)} signal(s) to {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
