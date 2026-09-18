"""SQLite-backed storage for the trading journal: closed round-trip
trades, a log of fired signals (for linking a trade's entry back to the
rule that triggered it), and a dedup marker for IBKR executions already
folded into a trade.

Plain sqlite3, not an ORM — this project favors explicit code over
abstraction (see the other modules), and a personal trading journal's data
volume never approaches what would need one. Every call here runs on the
single asyncio event-loop thread the rest of this app already runs on, so
no locking is needed.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

from .models import DayPnl, JournalTrade, MonthStats, SignalLogEntry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    rule TEXT NOT NULL,
    direction TEXT NOT NULL,
    price REAL NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_ticker_time ON signals(ticker, timestamp);

CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    sec_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_time TEXT NOT NULL,
    exit_price REAL NOT NULL,
    exit_date TEXT NOT NULL,
    realized_pnl REAL NOT NULL,
    source TEXT NOT NULL,
    expiry TEXT,
    strike REAL,
    right TEXT,
    signal_rule TEXT,
    signal_timestamp TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_exit_date ON trades(exit_date);

CREATE TABLE IF NOT EXISTS synced_executions (
    exec_id TEXT PRIMARY KEY
);
"""

# trades columns in exactly the order the schema (and therefore `SELECT *`)
# declares them, so insert_trade / _row_to_trade stay a straightforward
# zip rather than a second source of truth to keep in sync.
_TRADE_COLUMNS = (
    "id",
    "symbol",
    "sec_type",
    "direction",
    "quantity",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "exit_date",
    "realized_pnl",
    "source",
    "expiry",
    "strike",
    "right",
    "signal_rule",
    "signal_timestamp",
)


class JournalStore:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- signals -----------------------------------------------------------

    def record_signal(self, entry: SignalLogEntry) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO signals (id, ticker, rule, direction, price, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (entry.id, entry.ticker, entry.rule, entry.direction, entry.price, entry.timestamp.isoformat()),
        )
        self._conn.commit()

    def find_signal_before(
        self, ticker: str, direction: str, before: datetime, window_seconds: float
    ) -> Optional[SignalLogEntry]:
        earliest = (before - timedelta(seconds=window_seconds)).isoformat()
        row = self._conn.execute(
            "SELECT id, ticker, rule, direction, price, timestamp FROM signals "
            "WHERE ticker = ? AND direction = ? AND timestamp <= ? AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (ticker, direction, before.isoformat(), earliest),
        ).fetchone()
        if row is None:
            return None
        return SignalLogEntry(
            id=row[0],
            ticker=row[1],
            rule=row[2],
            direction=row[3],
            price=row[4],
            timestamp=datetime.fromisoformat(row[5]),
        )

    # -- execution dedup -----------------------------------------------------

    def is_execution_synced(self, exec_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM synced_executions WHERE exec_id = ?", (exec_id,)).fetchone()
        return row is not None

    def mark_execution_synced(self, exec_id: str) -> None:
        self._conn.execute("INSERT OR IGNORE INTO synced_executions (exec_id) VALUES (?)", (exec_id,))
        self._conn.commit()

    # -- trades --------------------------------------------------------------

    def insert_trade(self, trade: JournalTrade) -> None:
        values = {
            "id": trade.id,
            "symbol": trade.symbol,
            "sec_type": trade.sec_type,
            "direction": trade.direction,
            "quantity": trade.quantity,
            "entry_time": trade.entry_time.isoformat(),
            "entry_price": trade.entry_price,
            "exit_time": trade.exit_time.isoformat(),
            "exit_price": trade.exit_price,
            "exit_date": trade.exit_time.date().isoformat(),
            "realized_pnl": trade.realized_pnl,
            "source": trade.source,
            "expiry": trade.expiry,
            "strike": trade.strike,
            "right": trade.right,
            "signal_rule": trade.signal_rule,
            "signal_timestamp": trade.signal_timestamp.isoformat() if trade.signal_timestamp else None,
        }
        placeholders = ", ".join("?" for _ in _TRADE_COLUMNS)
        self._conn.execute(
            f"INSERT OR REPLACE INTO trades ({', '.join(_TRADE_COLUMNS)}) VALUES ({placeholders})",
            tuple(values[col] for col in _TRADE_COLUMNS),
        )
        self._conn.commit()

    def trades_for_day(self, day: date) -> list[JournalTrade]:
        rows = self._conn.execute(
            f"SELECT {', '.join(_TRADE_COLUMNS)} FROM trades WHERE exit_date = ? ORDER BY exit_time ASC",
            (day.isoformat(),),
        ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def day_pnl_for_month(self, year: int, month: int) -> list[DayPnl]:
        start, end = _month_bounds(year, month)
        rows = self._conn.execute(
            "SELECT exit_date, SUM(realized_pnl), COUNT(*) FROM trades "
            "WHERE exit_date >= ? AND exit_date <= ? GROUP BY exit_date ORDER BY exit_date",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [DayPnl(day=date.fromisoformat(r[0]), realized_pnl=r[1], trade_count=r[2]) for r in rows]

    def month_stats(self, year: int, month: int) -> MonthStats:
        start, end = _month_bounds(year, month)
        rows = self._conn.execute(
            "SELECT exit_date, realized_pnl FROM trades WHERE exit_date >= ? AND exit_date <= ?",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        pnls = [r[1] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        weekly: dict[tuple[int, int], float] = {}
        for exit_date_str, pnl in rows:
            iso_year, iso_week, _ = date.fromisoformat(exit_date_str).isocalendar()
            weekly[(iso_year, iso_week)] = weekly.get((iso_year, iso_week), 0.0) + pnl
        weekly_pnl = [
            (date.fromisocalendar(iso_year, iso_week, 1).isoformat(), total)
            for (iso_year, iso_week), total in sorted(weekly.items())
        ]

        return MonthStats(
            year=year,
            month=month,
            total_pnl=sum(pnls),
            trade_count=len(pnls),
            win_count=len(wins),
            loss_count=len(losses),
            win_rate=(len(wins) / len(pnls)) if pnls else None,
            avg_win=(sum(wins) / len(wins)) if wins else None,
            avg_loss=(sum(losses) / len(losses)) if losses else None,
            largest_win=max(wins) if wins else None,
            largest_loss=min(losses) if losses else None,
            weekly_pnl=weekly_pnl,
        )

    def _row_to_trade(self, row: tuple) -> JournalTrade:
        values = dict(zip(_TRADE_COLUMNS, row))
        return JournalTrade(
            id=values["id"],
            symbol=values["symbol"],
            sec_type=values["sec_type"],
            direction=values["direction"],
            quantity=values["quantity"],
            entry_time=datetime.fromisoformat(values["entry_time"]),
            entry_price=values["entry_price"],
            exit_time=datetime.fromisoformat(values["exit_time"]),
            exit_price=values["exit_price"],
            realized_pnl=values["realized_pnl"],
            source=values["source"],
            expiry=values["expiry"],
            strike=values["strike"],
            right=values["right"],
            signal_rule=values["signal_rule"],
            signal_timestamp=datetime.fromisoformat(values["signal_timestamp"])
            if values["signal_timestamp"]
            else None,
        )


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end
