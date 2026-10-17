import { calendarBounds, dayNumber, dayString } from "./calendar-dates";
import type { Dashboard, DailySessions } from "./types";

export const sessionPageSize = 90;
export function sessionRange(data: Dashboard) {
  const bounds = calendarBounds(data);
  const start = bounds.start ? dayNumber(bounds.start) : NaN;
  const end = dayNumber(bounds.end);
  const length = Number.isFinite(start) && Number.isFinite(end) && end >= start ? end - start + 1 : 0;
  return { start, end, length };
}

/** Materialize only the visible calendar window, even for centuries-long filters. */
export function sessionDays(data: Dashboard, offset: number): DailySessions[] {
  const range = sessionRange(data);
  if (!range.length || !data.daily_sessions) return [];
  const first = range.start + Math.max(0, Math.min(offset, range.length - 1));
  const last = Math.min(range.end, first + sessionPageSize - 1);
  const rows = new Map(data.daily_sessions.map(row => [row.day, row]));
  return Array.from({ length: last - first + 1 }, (_, index) => {
    const day = dayString(first + index);
    return rows.get(day) ?? { day, chats: 0, subagents: 0, system_agents: 0 };
  });
}
