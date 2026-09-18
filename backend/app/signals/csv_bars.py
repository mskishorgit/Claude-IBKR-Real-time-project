"""Load Bar objects from a CSV of historical OHLCV data.

Accepts either a CSV with a symbol/ticker column, or a single-symbol export
(e.g. an IBKR historical-data export) with no such column, in which case
pass `default_symbol`.

Recognized column names (case-insensitive):
    symbol:    symbol, ticker
    timestamp: timestamp, date, datetime, time
    open:      open, o
    high:      high, h
    low:       low, l
    close:     close, c
    volume:    volume, vol, v
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import Bar

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "ticker"),
    "timestamp": ("timestamp", "date", "datetime", "time"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "volume": ("volume", "vol", "v"),
}

_REQUIRED_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")

# Tried in order; IB's historical-data export commonly uses "yyyyMMdd  HH:mm:ss"
# (two spaces) when the request used formatDate=1.
_TIMESTAMP_FORMATS = (
    "%Y%m%d  %H:%M:%S",
    "%Y%m%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


def _resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    lowered = {name.lower(): name for name in fieldnames}
    resolved: dict[str, str] = {}
    for field_name, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                resolved[field_name] = lowered[alias]
                break
    missing = [f for f in _REQUIRED_FIELDS if f not in resolved]
    if missing:
        raise ValueError(f"CSV is missing required column(s): {', '.join(missing)}")
    return resolved


def _parse_timestamp(raw: str) -> datetime:
    raw = raw.strip()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Could not parse timestamp: {raw!r}") from exc


def _read_rows(
    reader: csv.DictReader, columns: dict[str, str], default_symbol: str | None
) -> Iterator[Bar]:
    for row in reader:
        if "symbol" in columns:
            symbol = row[columns["symbol"]].strip().upper()
        elif default_symbol:
            symbol = default_symbol.strip().upper()
        else:
            raise ValueError(
                "CSV has no symbol/ticker column and no default symbol was provided"
            )
        yield Bar(
            symbol=symbol,
            timestamp=_parse_timestamp(row[columns["timestamp"]]),
            open=float(row[columns["open"]]),
            high=float(row[columns["high"]]),
            low=float(row[columns["low"]]),
            close=float(row[columns["close"]]),
            volume=float(row[columns["volume"]]),
        )


def load_bars_from_csv(path: str | Path, default_symbol: str | None = None) -> list[Bar]:
    """Load and chronologically sort (per symbol) all bars in a CSV."""
    resolved_path = Path(path)
    with resolved_path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        columns = _resolve_columns(list(reader.fieldnames))
        bars = list(_read_rows(reader, columns, default_symbol))
    bars.sort(key=lambda b: (b.symbol, b.timestamp))
    return bars
