import { calendarBounds, dayNumber, dayString, mondayWeekday } from "./calendar-dates";
import type { CacheRateDay, Dashboard } from "./types";

export type CacheRateMode = "daily" | "weekly";
export type CacheRateStatus = "available" | "no-activity" | "missing" | "invalid" | "no-input";
export interface CachePeriod extends CacheRateDay {
  start: string;
  end: string;
  percent: number | null;
  status: CacheRateStatus;
}
export const cachePageSize = 90;
export const cachePercent = (value: number) => `${new Intl.NumberFormat("en-US", { maximumSignificantDigits: 4 }).format(value)}%`;

export function cacheStatus(row: CacheRateDay): CacheRateStatus {
  if (!row.observations) return "no-activity";
  if (row.input_available !== row.observations || row.cached_available !== row.observations) return "missing";
  if (row.input_tokens < 0 || row.cached_tokens < 0 || row.cached_tokens > row.input_tokens) return "invalid";
  return row.input_tokens === 0 ? "no-input" : "available";
}

export const cacheReasons: Record<CacheRateStatus, string> = {
  available: "Complete counter coverage",
  "no-activity": "No recorded usage",
  missing: "Input or cached-read counters missing",
  invalid: "Invalid cached-read/input ratio",
  "no-input": "No input tokens",
};

export function cacheRange(data: Dashboard, mode: CacheRateMode) {
  const bounds = calendarBounds(data);
  const start = bounds.start ? dayNumber(bounds.start) : NaN;
  const end = dayNumber(bounds.end);
  const step = mode === "daily" ? 1 : 7;
  const anchor = mode === "weekly" ? start - mondayWeekday(start) : start;
  const length = Number.isFinite(start) && Number.isFinite(end) && end >= start
    ? Math.floor((end - anchor) / step) + 1 : 0;
  return { start, end, anchor, step, length };
}

/** Only materialize the visible periods; even huge empty date ranges stay bounded. */
export function cachePeriods(data: Dashboard, mode: CacheRateMode, offset: number): CachePeriod[] {
  const range = cacheRange(data, mode);
  if (!range.length || !data.cache_rate_timeline) return [];
  const first = Math.max(0, Math.min(offset, Math.floor((range.length - 1) / cachePageSize) * cachePageSize));
  const periods: CachePeriod[] = Array.from({ length: Math.min(cachePageSize, range.length - first) }, (_, i) => {
    const start = dayString(Math.max(range.start, range.anchor + (first + i) * range.step));
    const end = dayString(Math.min(range.end, range.anchor + (first + i + 1) * range.step - 1));
    return { day: start, start, end, input_tokens: 0, cached_tokens: 0, observations: 0,
      input_available: 0, cached_available: 0, percent: null, status: "no-activity" };
  });
  const invalid = new Set<number>();
  for (const row of data.cache_rate_timeline) {
    const day = dayNumber(row.day);
    if (day < range.start || day > range.end) continue;
    const index = Math.floor((day - range.anchor) / range.step) - first;
    const period = periods[index];
    if (!period) continue;
    for (const key of ["input_tokens", "cached_tokens", "observations", "input_available", "cached_available"] as const)
      period[key] += row[key];
    if (cacheStatus(row) === "invalid") invalid.add(index);
  }
  for (const [i, period] of periods.entries()) {
    period.status = invalid.has(i) ? "invalid" : cacheStatus(period);
    if (period.status === "available") period.percent = 100 * period.cached_tokens / period.input_tokens;
  }
  return periods;
}
