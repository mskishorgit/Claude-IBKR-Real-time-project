import type { DayPnlData, WeeklyPnlData } from "../types";

interface Props {
  year: number;
  month: number; // 1-12
  days: DayPnlData[];
  weeklyPnl: WeeklyPnlData[];
  selectedDate: string | null;
  onSelectDate: (date: string) => void;
}

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function fmtMoney(value: number): string {
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pnlBg(value: number): string {
  if (value > 0) return "bg-emerald-500/15 border-emerald-500/40";
  if (value < 0) return "bg-red-500/15 border-red-500/40";
  return "bg-slate-800/60 border-slate-800";
}

function pnlText(value: number): string {
  if (value > 0) return "text-emerald-400";
  if (value < 0) return "text-red-400";
  return "text-slate-400";
}

/** ISO week (Monday-start) grid for the given month, split into rows with a
 * trailing week-total cell — the standard trading-journal-calendar layout
 * (TraderSync/TradeZella etc.), which is where this app's "running weekly
 * P/L total" lives (see README for why it's per-row here rather than a
 * single number above the grid). */
export function PnlCalendar({ year, month, days, weeklyPnl, selectedDate, onSelectDate }: Props) {
  const dayByDate = new Map(days.map((d) => [d.date, d]));
  const weekTotalByStart = new Map(weeklyPnl.map((w) => [w.week_start, w.realized_pnl]));

  const firstOfMonth = new Date(Date.UTC(year, month - 1, 1));
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  // Monday=0 .. Sunday=6
  const leadingBlanks = (firstOfMonth.getUTCDay() + 6) % 7;

  const cells: (string | null)[] = [
    ...Array(leadingBlanks).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => {
      const d = i + 1;
      return `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    }),
  ];
  while (cells.length % 7 !== 0) cells.push(null);

  const weeks: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-8 gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
        {WEEKDAY_LABELS.map((label) => (
          <div key={label} className="px-1 text-center">
            {label}
          </div>
        ))}
        <div className="px-1 text-center">Week</div>
      </div>

      {weeks.map((week, weekIdx) => {
        const weekStart = week.find((d) => d !== null);
        const weekTotal = weekStart ? weekTotalByStart.get(_mondayOf(weekStart)) : undefined;
        return (
          <div key={weekIdx} className="grid grid-cols-8 gap-1.5">
            {week.map((dateStr, i) => {
              if (dateStr === null) {
                return <div key={i} className="aspect-square rounded-md border border-transparent" />;
              }
              const entry = dayByDate.get(dateStr);
              const pnl = entry?.realized_pnl ?? 0;
              const hasTrades = entry !== undefined;
              const isSelected = dateStr === selectedDate;
              return (
                <button
                  key={dateStr}
                  type="button"
                  onClick={() => onSelectDate(dateStr)}
                  className={`flex aspect-square flex-col items-start justify-between rounded-md border p-1.5 text-left transition-colors ${
                    hasTrades ? pnlBg(pnl) : "border-slate-800 bg-slate-900/40 hover:border-slate-700"
                  } ${isSelected ? "ring-2 ring-sky-400" : ""}`}
                >
                  <span className="text-[10px] text-slate-500">{Number(dateStr.slice(-2))}</span>
                  {hasTrades && (
                    <span className={`w-full truncate text-[11px] font-mono font-semibold ${pnlText(pnl)}`}>
                      {fmtMoney(pnl)}
                    </span>
                  )}
                </button>
              );
            })}
            <div className="flex aspect-square flex-col items-center justify-center rounded-md border border-slate-800 bg-slate-900/60 px-1">
              <span className="text-[9px] uppercase text-slate-600">Wk</span>
              <span className={`font-mono text-[11px] font-semibold ${weekTotal !== undefined ? pnlText(weekTotal) : "text-slate-600"}`}>
                {weekTotal !== undefined ? fmtMoney(weekTotal) : "—"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** weeklyPnl keys weeks by their Monday date already — this just derives
 * the same key from any date in that row so the trailing cell can look it
 * up regardless of which day the row's first non-blank cell landed on. */
function _mondayOf(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00Z`);
  const dow = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - dow);
  return d.toISOString().slice(0, 10);
}
