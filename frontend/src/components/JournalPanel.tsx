import { useEffect, useState } from "react";
import { getJournalCalendar, getJournalDay, getJournalStats, triggerJournalSync } from "../api";
import type { DayPnlData, JournalTradeData, MonthStatsData } from "../types";
import { JournalDayTrades } from "./JournalDayTrades";
import { JournalStatsPanel } from "./JournalStatsPanel";
import { PnlCalendar } from "./PnlCalendar";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const EMPTY_STATS: MonthStatsData = {
  year: 0,
  month: 0,
  total_pnl: 0,
  trade_count: 0,
  win_count: 0,
  loss_count: 0,
  win_rate: null,
  avg_win: null,
  avg_loss: null,
  largest_win: null,
  largest_loss: null,
  weekly_pnl: [],
};

function fmtMoney(value: number): string {
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

interface Props {
  journalVersion: number;
}

/** Container for the daily P/L calendar: month navigation, the calendar
 * grid, a monthly total banner, the win/loss stats strip, and the
 * expanded trade list for whichever day is selected. Data comes from
 * REST (journal.py's calendar/day/stats endpoints); `journalVersion`
 * (from useJournalStream) just tells it when to refetch. */
export function JournalPanel({ journalVersion }: Props) {
  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getUTCFullYear());
  const [viewMonth, setViewMonth] = useState(today.getUTCMonth() + 1);
  const [days, setDays] = useState<DayPnlData[]>([]);
  const [stats, setStats] = useState<MonthStatsData>(EMPTY_STATS);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [dayTrades, setDayTrades] = useState<JournalTradeData[]>([]);
  const [dayLoading, setDayLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJournalCalendar(viewYear, viewMonth).then((res) => {
      if (!cancelled) setDays(res.days);
    });
    getJournalStats(viewYear, viewMonth).then((res) => {
      if (!cancelled) setStats(res);
    });
    return () => {
      cancelled = true;
    };
  }, [viewYear, viewMonth, journalVersion]);

  useEffect(() => {
    if (!selectedDate) {
      setDayTrades([]);
      return;
    }
    let cancelled = false;
    setDayLoading(true);
    getJournalDay(selectedDate)
      .then((res) => {
        if (!cancelled) setDayTrades(res.trades);
      })
      .finally(() => {
        if (!cancelled) setDayLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDate, journalVersion]);

  function changeMonth(delta: number) {
    let month = viewMonth + delta;
    let year = viewYear;
    if (month < 1) {
      month = 12;
      year -= 1;
    } else if (month > 12) {
      month = 1;
      year += 1;
    }
    setViewYear(year);
    setViewMonth(month);
    setSelectedDate(null);
  }

  async function handleSync() {
    setSyncing(true);
    setSyncError(null);
    try {
      await triggerJournalSync();
      const [calendar, monthStats] = await Promise.all([
        getJournalCalendar(viewYear, viewMonth),
        getJournalStats(viewYear, viewMonth),
      ]);
      setDays(calendar.days);
      setStats(monthStats);
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => changeMonth(-1)}
            className="rounded-md border border-slate-700 px-2 py-1 text-sm text-slate-300 hover:border-slate-500"
            aria-label="Previous month"
          >
            ←
          </button>
          <span className="min-w-[9rem] text-center text-sm font-medium text-slate-200">
            {MONTH_NAMES[viewMonth - 1]} {viewYear}
          </span>
          <button
            type="button"
            onClick={() => changeMonth(1)}
            className="rounded-md border border-slate-700 px-2 py-1 text-sm text-slate-300 hover:border-slate-500"
            aria-label="Next month"
          >
            →
          </button>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-xs text-slate-500">Month total</div>
            <div className={`font-mono text-lg font-semibold ${stats.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {fmtMoney(stats.total_pnl)}
            </div>
          </div>
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-slate-500 disabled:opacity-50"
          >
            {syncing ? "Syncing…" : "Sync with IBKR"}
          </button>
        </div>
      </div>

      {syncError && <p className="text-xs text-red-400">{syncError}</p>}

      <JournalStatsPanel stats={stats} />

      <PnlCalendar
        year={viewYear}
        month={viewMonth}
        days={days}
        weeklyPnl={stats.weekly_pnl}
        selectedDate={selectedDate}
        onSelectDate={(date) => setSelectedDate(date === selectedDate ? null : date)}
      />

      {selectedDate && <JournalDayTrades date={selectedDate} trades={dayTrades} loading={dayLoading} />}
    </div>
  );
}
