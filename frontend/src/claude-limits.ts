import type { ProviderAllowance, ProviderBucket } from "./types";
import { accountDate } from "./account-credits";
import { currency } from "./format";
import { esc } from "./ui";
import { allowanceTone, tooltipAttributes } from "./widget-presentation";

/** Claude's 5-hour and weekly limits belong to the plan, shared by every Claude surface. */
export const providerHeadings: Record<string, string> = { claude_code: "Claude plan limits", antigravity: "Antigravity allowance" };
/** Older readings are past every weekly window and only add noise. */
export const MAX_READING_AGE = 8 * 86400;

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** Classify on the server's meter kind, never on a display label. */
export function limitLabel(bucket: Pick<ProviderBucket, "id" | "kind" | "scope_label">): string {
  const kind = bucket.kind ?? bucket.id;
  if (kind === "session" || kind === "five_hour") return bucket.scope_label ? `5-hour · ${bucket.scope_label}` : "5-hour limit";
  if (kind === "weekly_all" || kind === "seven_day") return bucket.scope_label ? `Weekly · ${bucket.scope_label}` : "Weekly limit";
  if (kind === "weekly_scoped") return `Weekly · ${bucket.scope_label || "scoped"}`;
  if (kind === "spend_limit") return "Spend limit";
  const readable = readableKind(kind);
  return bucket.scope_label ? `${readable} · ${bucket.scope_label}` : readable;
}

const windowWords: Record<string, string> = { "5h": "5-hour", "1d": "Daily", daily: "Daily", "7d": "Weekly", week: "Weekly", weekly: "Weekly" };
const scopeWords: Record<string, string> = { "3p": "Third-party models", gemini: "Gemini" };

/** Bridge readings name meters like "gemini-5h" or "3p-weekly"; anything unrecognized stays as reported. */
function readableKind(kind: string) {
  const match = /^(.+?)[-_](5h|1d|daily|7d|week|weekly)$/i.exec(kind);
  if (!match) return kind;
  const scope = scopeWords[match[1].toLowerCase()] ?? match[1].charAt(0).toUpperCase() + match[1].slice(1);
  return `${windowWords[match[2].toLowerCase()]} · ${scope}`;
}

export type LimitState = "fresh" | "stale" | "reset_passed";

/** A passed reset never implies a refilled window; it only voids the reading. */
export function limitState(bucket: ProviderBucket, now = Date.now() / 1000, aged = false): LimitState {
  if (finite(bucket.resets_at) && now >= bucket.resets_at) return "reset_passed";
  return bucket.stale || aged ? "stale" : "fresh";
}

/** Apply expiry locally too: a disconnected client cannot freeze freshness. */
export function readingAged(profile: Pick<ProviderAllowance, "received_at" | "source">, now = Date.now() / 1000): boolean {
  const limit = profile.source?.endsWith(" /usage") ? 600 : 300;
  return !finite(profile.received_at) || now - profile.received_at >= limit;
}

export function validBucket(bucket: ProviderBucket | null | undefined): bucket is ProviderBucket {
  return !!bucket && typeof bucket.id === "string" && (bucket.unit === "percent" || bucket.unit === "usd") &&
    (bucket.resets_at == null || finite(bucket.resets_at)) &&
    ((finite(bucket.remaining_percent) && bucket.remaining_percent >= 0 && bucket.remaining_percent <= 100) ||
      (bucket.unit === "usd" && finite(bucket.used) && bucket.used >= 0));
}

const dayKey = (value: number, timezone: string) => new Date(value * 1000).toLocaleDateString("en-CA", { timeZone: timezone });

/** "3:00 PM" today, "Thu 3:00 PM" within the week, otherwise "Oct 23, 3:00 PM". */
export function shortMoment(value: number, timezone: string, now = Date.now() / 1000): string {
  const date = new Date(value * 1000);
  const time = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: timezone });
  if (dayKey(value, timezone) === dayKey(now, timezone)) return time;
  if (Math.abs(value - now) < 6 * 86400) return `${date.toLocaleDateString([], { weekday: "short", timeZone: timezone })} ${time}`;
  return `${date.toLocaleDateString([], { month: "short", day: "numeric", timeZone: timezone })}, ${time}`;
}

export function fullMoment(value: number, timezone: string): string {
  return new Date(value * 1000).toLocaleString([], {
    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: timezone,
  });
}

export function duration(seconds: number): string {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  const days = Math.floor(minutes / 1440), hours = Math.floor((minutes % 1440) / 60), rest = minutes % 60;
  return days ? `${days}d ${hours}h` : hours ? `${hours}h ${rest}m` : `${rest}m`;
}

/** Absolute reset date and time in the display timezone, with a countdown unless compact. */
export function resetText(reset: number | null | undefined, timezone: string, now = Date.now() / 1000, compact = false): string {
  if (!finite(reset)) return "Reset time unavailable";
  // Servers report e.g. 04:49:59.8; show the minute the window actually resets.
  const minute = Math.round(reset / 60) * 60;
  if (now >= reset) return `Reset ${shortMoment(minute, timezone, now)} · awaiting new reading`;
  return compact ? `Resets ${shortMoment(minute, timezone, now)}` : `Resets ${fullMoment(minute, timezone)} · in ${duration(reset - now)}`;
}

export function asOfText(received: number, timezone: string, now = Date.now() / 1000): string {
  return `As of ${shortMoment(received, timezone, now)}`;
}

export function sourceText(profile: Pick<ProviderAllowance, "source">): string {
  if (profile.source?.endsWith(" /usage")) return `via ${profile.source}`;
  return profile.source ? `via ${profile.source.replace(/^(Claude Code|Antigravity CLI) /, "")}` : "via status line";
}

export function limitWindowMarkup(bucket: ProviderBucket, timezone: string, now = Date.now() / 1000, compact = false, updated = "", aged = false): string {
  const label = limitLabel(bucket);
  const state = limitState(bucket, now, aged);
  const percent = state !== "reset_passed" && finite(bucket.remaining_percent) ? Math.max(0, Math.min(100, bucket.remaining_percent)) : null;
  const value = state === "reset_passed" ? { tone: "unknown", text: "Awaiting reading" }
    : percent === null && bucket.unit === "usd" && finite(bucket.used)
      ? { tone: "unknown", text: `${currency(bucket.used)} / ${finite(bucket.limit) ? currency(bucket.limit) : "—"}` }
      : allowanceTone(percent);
  const full = resetText(bucket.resets_at, timezone, now);
  // Compact surfaces show the countdown like Codex windows; the exact time stays in the tooltip.
  const countdown = finite(bucket.resets_at) && now < bucket.resets_at ? `Resets in ${duration(bucket.resets_at - now)}` : resetText(bucket.resets_at, timezone, now, true);
  const meta = compact
    ? `<div class="widget-metadata"><span class="widget-countdown" ${tooltipAttributes(`${full} · ${timezone}`)}>${esc(countdown)}</span>${updated}</div>`
    : `<small title="${esc(timezone)}">${esc(full)}</small>`;
  return `<div class="allowance-window provider-limit" data-tone="${value.tone}"${state === "fresh" ? "" : ` data-state="${state}"`}>
    <div class="allowance-window-label"><span>${esc(label)}</span><strong>${esc(value.text)}</strong></div>
    ${percent === null ? "" : `<div class="allowance-track" role="meter" aria-label="${esc(label)} remaining" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span style="width:${percent}%"></span></div>`}
    ${meta}</div>`;
}

/** What to do when a profile has no reading yet. */
export function emptyGuidance(profile: ProviderAllowance): string {
  if (profile.provider === "antigravity") {
    if (profile.check?.enabled && !profile.check.error && (profile.check.refreshing || profile.check.last_success_at === null)) return "Checking Antigravity CLI /usage…";
    return profile.check?.enabled ? "No Antigravity quota reading yet." : "Turn on “Check Antigravity allowance” in Settings, or use the optional CLI status-line bridge in Sources.";
  }
  const check = profile.check;
  if (check?.enabled && (check.refreshing || check.last_success_at === null) && !check.error) return "Checking Claude Code /usage…";
  if (check?.enabled) return "No limits reading yet.";
  return "Turn on “Check Claude plan limits” in Settings, or use Claude Code in a terminal with the status-line bridge installed in Sources.";
}
