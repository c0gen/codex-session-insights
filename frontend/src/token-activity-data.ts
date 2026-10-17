import { calendarBounds, dayNumber, dayString, mondayWeekday } from "./calendar-dates";
import type { Dashboard } from "./types";

export type TokenActivityMode = "daily" | "weekly" | "cumulative";
export interface TokenDay {
  day: string;
  tokens: number;
  cumulative: number;
  level: number;
}
export interface TokenWeek {
  weekStart: string;
  start: string;
  end: string;
  tokens: number;
}
export interface TokenYear {
  year: string;
  columns: number;
  cells: (TokenDay | null)[];
  months: { month: number; column: number }[];
}
export interface TokenActivityData {
  start: string | null;
  end: string;
  days: TokenDay[];
  weeks: TokenWeek[];
  years: TokenYear[];
  total: number;
  max: number;
}

/** One source for all views; padding is distinct from a selected zero-token day. */
export function buildTokenActivity(data: Dashboard): TokenActivityData {
  const { start, end } = calendarBounds(data);
  const result: TokenActivityData = { start, end, days: [], weeks: [], years: [], total: 0, max: 0 };
  if (!start) return result;
  const first = dayNumber(start), last = dayNumber(end);
  if (!Number.isFinite(first) || !Number.isFinite(last) || last < first) return result;
  const totals = new Map<string, number>();
  for (const row of data.timeline) {
    if (row.day >= start && row.day <= end)
      totals.set(row.day, (totals.get(row.day) || 0) + (row.tokens || 0));
  }
  let week: TokenWeek | undefined, year: TokenYear | undefined;
  for (let n = first; n <= last; n++) {
    const day = dayString(n), tokens = totals.get(day) || 0, weekday = mondayWeekday(n);
    result.total += tokens;
    result.max = Math.max(result.max, tokens);
    const entry: TokenDay = { day, tokens, cumulative: result.total, level: 0 };
    result.days.push(entry);
    if (!week || weekday === 0) {
      week = { weekStart: dayString(n - weekday), start: day, end: day, tokens: 0 };
      result.weeks.push(week);
    }
    week.end = day;
    week.tokens += tokens;
    if (!year || year.year !== day.slice(0, 4)) {
      year = { year: day.slice(0, 4), columns: 0, cells: Array(weekday).fill(null), months: [] };
      result.years.push(year);
    }
    const month = Number(day.slice(5, 7));
    if (year.months[year.months.length - 1]?.month !== month)
      year.months.push({ month, column: Math.floor(year.cells.length / 7) + 1 });
    year.cells.push(entry);
  }
  for (const entry of result.days)
    entry.level = entry.tokens > 0 ? Math.min(4, Math.ceil(entry.tokens / result.max * 4)) : 0;
  for (const year of result.years) {
    year.columns = Math.ceil(year.cells.length / 7);
    while (year.cells.length < year.columns * 7) year.cells.push(null);
  }
  return result;
}
