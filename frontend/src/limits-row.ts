import type { BurnRateEstimate, ProviderAllowance, ProviderBucket, UsageLimits } from "./types";
import { remainingPercent, windowName } from "./allowance";
import { compact, currency } from "./format";
import { esc } from "./ui";
import { duration, fullMoment, limitLabel, limitState, readingAged, validBucket } from "./claude-limits";

/** Overview shows one short row; Accounts keeps the full cards. */
type Meter = { label: string; remaining: number | null; resets: number | null; reset_passed?: boolean };

const tone = (remaining: number | null) => remaining === null ? "unknown" : remaining <= 10 ? "critical" : remaining <= 20 ? "low" : "healthy";

function describe(meter: Meter, timezone: string) {
  const value = meter.reset_passed ? "awaiting new reading" : meter.remaining === null ? "unavailable" : `${remainingPercent(meter.remaining)} left`;
  const reset = meter.resets === null ? "" : meter.reset_passed ? "" : `, resets ${fullMoment(Math.round(meter.resets / 60) * 60, timezone)}`;
  return `${meter.label}: ${value}${reset}.`;
}

function chip(id: string, name: string, meters: Meter[], badge: string, detail: string, timezone: string, now: number) {
  // The tightest window is the one that limits work next.
  const live = meters.filter(m => !m.reset_passed && m.remaining !== null);
  const tight = live.sort((a, b) => a.remaining! - b.remaining!)[0];
  const text = tight ? `${remainingPercent(tight.remaining!)} left` : meters.some(m => m.reset_passed) ? "Awaiting reading" : "Unavailable";
  const reset = tight?.resets && tight.resets > now ? ` · in ${duration(tight.resets - now)}` : "";
  const help = [`${name} limits, independent of filters.`, ...meters.map(m => describe(m, timezone)), detail, "Open Accounts for details."].filter(Boolean).join(" ");
  return `<button type="button" id="limit-chip-${esc(id)}" class="limit-chip" data-limit="${esc(id)}" data-tone="${tight ? tone(tight.remaining) : "unknown"}" title="${esc(help)}" aria-label="${esc(help)}">
    <span class="limit-chip-name">${esc(name)}${badge}</span>${tight ? `<span class="limit-chip-window">${esc(tight.label)}</span><span class="limit-chip-track" aria-hidden="true"><span style="width:${Math.max(0, Math.min(100, tight.remaining!))}%"></span></span>` : ""}<strong>${esc(text)}</strong>${reset ? `<span class="limit-chip-reset">${esc(reset)}</span>` : ""}</button>`;
}

function codexChip(limits: UsageLimits, timezone: string, now: number) {
  const bucket = limits.buckets.find(b => b.id === "codex") || limits.buckets[0];
  const meters: Meter[] = (bucket?.windows || []).map(w => ({
    label: windowName(w.window_duration_mins), remaining: w.remaining_percent, resets: w.resets_at,
    reset_passed: w.resets_at !== null && now >= w.resets_at,
  }));
  const detail = limits.error || (limits.last_success_at === null ? "No successful update yet." : `Updated ${fullMoment(limits.last_success_at, timezone)}.`);
  return chip("codex", "Codex", meters, limits.stale ? ' <b class="allowance-stale">Stale</b>' : "", detail, timezone, now);
}

function providerChip(profile: ProviderAllowance, timezone: string, now: number) {
  const buckets = (Array.isArray(profile.buckets) ? profile.buckets : []).filter(validBucket);
  const aged = readingAged(profile, now);
  const meters: Meter[] = buckets.filter((b: ProviderBucket) => b.unit === "percent").map(b => ({
    label: limitLabel(b).replace(/ limit$/, ""), remaining: b.remaining_percent, resets: b.resets_at,
    reset_passed: limitState(b, now, aged) === "reset_passed",
  }));
  const checking = profile.check?.enabled && (profile.check.refreshing || profile.check.last_success_at === null) && !profile.check.error;
  // A provider nobody turned on stays off the row; its setup guidance lives on Accounts.
  if (!meters.length && !profile.check?.enabled) return "";
  const stale = buckets.some(b => limitState(b, now, aged) !== "fresh");
  const name = profile.provider === "claude_code" ? "Claude" : profile.provider === "antigravity" ? "Antigravity" : profile.label || profile.provider;
  const detail = profile.check?.error || (checking && !meters.length ? "Checking now." : "");
  return chip(profile.provider, name, meters, stale ? ' <b class="allowance-stale">Stale</b>' : "", detail, timezone, now);
}

function burnChip(limits: UsageLimits) {
  const rates: [BurnRateEstimate | undefined, "tokens" | "cost"][] = [[limits.token_burn_rate, "tokens"], [limits.cost_burn_rate, "cost"]];
  const parts = rates.filter(([rate]) => rate).map(([rate, kind]) => {
    const numeric = rate!.value !== null && Number.isFinite(rate!.value);
    const value = rate!.status === "collecting" ? "Collecting…" : !numeric ? "Unavailable"
      : kind === "cost" ? `${rate!.value! > 0 && rate!.value! < 0.01 ? "<$0.01" : currency(rate!.value!)}/min` : `${compact(rate!.value!)} tokens/min`;
    const help = `${kind === "cost" ? "Local dollar burn: API-equivalent USD per minute, not a subscription bill" : "Local token burn: tokens per minute"} from enabled local Codex session folders. Five-minute trailing estimate.${rate!.status === "stale" ? " Stale." : ""}`;
    // Stable ids let a full dashboard redraw restore keyboard focus (live-updates.ts).
    return `<span id="limits-burn-${kind}" class="burn-rate burn-rate-${kind}" data-status="${esc(rate!.status)}" tabindex="0" title="${esc(help)}" aria-label="${esc(`${help} ${value}.`)}"><strong>${esc(value)}</strong></span>`;
  });
  return parts.length ? `<div class="limit-burn"><span>Local burn</span>${parts.join('<span aria-hidden="true">·</span>')}</div>` : "";
}

export function limitsRowMarkup(limits: UsageLimits | undefined, providers: ProviderAllowance[] | undefined, selected: string | undefined, timezone: string, now = Date.now() / 1000): string {
  const showCodex = !selected || selected === "codex";
  const chips = [
    showCodex && limits?.enabled ? codexChip(limits, timezone, now) : "",
    ...(providers || []).filter(p => p && (!selected || p.provider === selected)).map(p => providerChip(p, timezone, now)),
  ].filter(Boolean);
  const burn = showCodex && limits?.enabled ? burnChip(limits) : "";
  if (!chips.length && !burn) return "";
  return `<div class="limit-chips">${chips.join("")}</div>${burn}<button type="button" id="limits-details" class="text-button limit-details" data-limit="details">Limits &amp; accounts →</button>`;
}
