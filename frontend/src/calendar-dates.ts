/** Date-only arithmetic: indexed days already belong to the display timezone. */
import type { Dashboard } from "./types";

const dayMs = 86_400_000;
export const dayNumber = (day: string) => Date.parse(`${day}T00:00:00Z`) / dayMs;
export const dayString = (day: number) => new Date(day * dayMs).toISOString().slice(0, 10);
export const mondayWeekday = (day: number) => ((day + 3) % 7 + 7) % 7;
export const calendarLabel = (day: string, options: Intl.DateTimeFormatOptions = {}) =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric", ...options, timeZone: "UTC",
  });

export function calendarBounds(data: Dashboard): { start: string | null; end: string } {
  if (data.date_bounds) return data.date_bounds;
  // Older saved reports have no explicit bounds. Use their applied filters.
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: data.timezone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(data.generated_at));
  const part = (name: string) => parts.find(value => value.type === name)!.value;
  const today = `${part("year")}-${part("month")}-${part("day")}`;
  const filters = data.filters;
  if (filters?.range === "custom") return { start: filters.start, end: filters.end };
  const days = filters?.range === "today" ? 1 : Number(filters?.range);
  return { start: [1, 7, 30, 90].includes(days)
    ? dayString(dayNumber(today) - days + 1) : data.timeline[0]?.day || null, end: today };
}
