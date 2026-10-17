/** A minimal, immutable analytics snapshot. No account or source details enter it. */
import type { Dashboard } from "./types";
import { historyCoverage } from './history-coverage';
import { calendarBounds, calendarLabel as label, dayNumber } from "./calendar-dates";

const preferenceKey = "insights-summary-image-project-names";
let nativeNames: boolean | null = null;
let nativeRead: Promise<void> | null = null;

export interface SummaryImageSnapshot {
  readonly dateLabel: string;
  readonly timezone: string;
  readonly context: string;
  readonly tokens: number | null;
  readonly cost: number | null;
  readonly pricedPercent: number;
  readonly fastPercent: number;
  readonly added: number;
  readonly removed: number;
  readonly chats: number;
  readonly partial: boolean;
  readonly demo: boolean;
  readonly start: string | null;
  readonly end: string;
  readonly activity: readonly number[];
  readonly hasActivity: boolean;
}

export function includeProjectNames(): boolean {
  if (window.pywebview?.api) return nativeNames === true;
  try { return localStorage.getItem(preferenceKey) === "true"; }
  catch { return false; }
}

export async function setIncludeProjectNames(value: boolean): Promise<void> {
  if (window.pywebview?.api) {
    await window.pywebview.api.call("summary_image_preferences", { include_project_names: value });
    nativeNames = value;
  } else localStorage.setItem(preferenceKey, String(value));
}

export function initializeSummaryImagePreferences(): Promise<void> {
  if (!window.pywebview?.api) return Promise.resolve();
  nativeRead ||= window.pywebview.api.call("summary_image_preferences", {}).then(value => {
    nativeNames = (value as { include_project_names: boolean }).include_project_names === true;
  }).catch(() => { nativeNames = false; });
  return nativeRead;
}

/** Calendar bins stay bounded even for long, mostly inactive histories. */
export function tokenActivity(data: Dashboard, start: string | null, end: string): readonly number[] {
  if (!start) return Object.freeze([]);
  const first = dayNumber(start), last = dayNumber(end);
  if (!Number.isFinite(first) || !Number.isFinite(last) || last < first) return Object.freeze([]);
  const days = last - first + 1, count = Math.min(days, 180);
  const bins = Array.from({ length: count }, () => 0);
  for (const row of data.timeline) {
    const offset = dayNumber(row.day) - first;
    if (offset >= 0 && offset < days) bins[Math.min(count - 1, Math.floor(offset * count / days))] += row.tokens || 0;
  }
  return Object.freeze(bins);
}

export function summaryImageSnapshot(data: Dashboard, names = includeProjectNames()): SummaryImageSnapshot {
  const { start, end } = calendarBounds(data), filters = data.filters;
  const project = !filters?.project_id ? "All projects" : names
    ? data.options.projects.find(value => value.id === filters.project_id)?.name || "Selected project"
    : "Selected project";
  const providerNames: Record<string, string> = { codex: "Codex", claude_code: "Claude Code", antigravity: "Antigravity" };
  const context = [providerNames[filters?.provider || ""] || "All tools", project, filters?.model || "All models", filters?.source_id ? "Selected source" : "All sources"].join(" · ");
  const rangeNames: Record<string, string> = { all: "All time", today: "Today", "7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days", custom: "Custom dates" };
  const rangeName = rangeNames[filters?.range || "all"] || "Selected dates";
  const dates = !start ? `Through ${label(end)}` : start === end ? label(end) : `${label(start)} – ${label(end)}`;
  const activity = tokenActivity(data, start, end), s = data.summary;
  return Object.freeze({
    dateLabel: `${rangeName} · ${dates}`, timezone: data.timezone,
    context: historyCoverage(data.source_states) ? `${context} · ${historyCoverage(data.source_states)} · retained history` : context,
    tokens: data.coverage.tokens?.state === "unavailable" ? null : s.total_tokens,
    cost: data.coverage.tokens?.state === "unavailable" || (s.total_tokens > 0 && s.priced_percent === 0) ? null : s.cost, pricedPercent: s.priced_percent,
    fastPercent: data.settings.assumed_fast_percent, added: s.lines_added, removed: s.lines_removed,
    chats: s.chats, partial: s.change_coverage === "partial" || data.coverage.tokens?.state === "partial" || !!historyCoverage(data.source_states), demo: data.demo,
    start, end, activity, hasActivity: activity.some(value => value > 0),
  });
}
