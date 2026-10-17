import type { AllowanceWindow } from "./types";
import { remainingPercent, resetCountdown, windowDuration } from "./allowance";
import { accountDate } from "./account-credits";
import { esc } from "./ui";

export function allowanceTone(remaining: number | null) {
  if (remaining === null || !Number.isFinite(remaining)) return { tone: "unknown", text: "Unavailable" };
  const value = Math.max(0, Math.min(100, remaining));
  const percent = remainingPercent(value);
  if (value === 0) return { tone: "critical", text: `${percent} · Exhausted` };
  if (value <= 10) return { tone: "critical", text: `${percent} · Critical` };
  if (value <= 20) return { tone: "low", text: `${percent} · Low` };
  return { tone: "healthy", text: `${percent} remaining` };
}

export function tooltipAttributes(text: string) {
  return `tabindex="0" data-tooltip="${esc(text)}" title="${esc(text)}" aria-label="${esc(text)}"`;
}

export function widgetTimestamp(updated: number | null, timezone: string) {
  const valid = updated !== null && Number.isFinite(updated);
  const text = valid ? `Updated ${new Date(updated * 1000).toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit", timeZone: timezone,
  })}` : "Not updated";
  return `<span class="allowance-update" ${tooltipAttributes(valid
    ? `Updated ${accountDate(updated, timezone)} · ${timezone}` : "No successful update")}>${esc(text)}</span>`;
}

export function widgetMetadata(reset: number | null, updated: string, timezone: string) {
  const countdown = resetCountdown(reset, undefined, true);
  const detail = reset === null ? countdown : `${countdown}. Reset time: ${accountDate(reset, timezone)} · ${timezone}`;
  return `<div class="widget-metadata"><span class="widget-countdown" ${tooltipAttributes(detail)}>${esc(countdown)}</span>${updated}</div>`;
}

export function widgetWindowMarkup(window: AllowanceWindow, updated: string, timezone: string, label?: string) {
  const { tone, text } = allowanceTone(window.remaining_percent);
  const remaining = window.remaining_percent;
  return `<div class="allowance-window" data-tone="${tone}">
    <div class="allowance-window-label"><span>${esc(label ?? windowDuration(window.window_duration_mins, true))}</span><strong>${esc(text)}</strong></div>
    ${remaining === null || !Number.isFinite(remaining) ? "" : `<div class="allowance-track" role="meter" aria-label="${esc(label ?? windowDuration(window.window_duration_mins))} remaining" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.max(0, Math.min(100, remaining))}"><span style="width:${Math.max(0, Math.min(100, remaining))}%"></span></div>`}
    ${widgetMetadata(window.resets_at, updated, timezone)}</div>`;
}
