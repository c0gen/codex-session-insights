import type { ResetCredit, ResetCredits } from "./account-types";
import { esc } from "./ui";

export function accountDate(value: number, timezone: string): string {
  return new Date(value * 1000).toLocaleString([], {
    timeZone: timezone, year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}
export function expiryLabel(credit: ResetCredit, timezone: string, compact = false): string {
  if (credit.expiration === "none") return "No expiration";
  if (credit.expires_at === null) return "Expiration unavailable";
  const minutes = Math.ceil((credit.expires_at * 1000 - Date.now()) / 60000);
  if (minutes <= 0) return compact ? "Expiry passed · updating" : `Expired date: ${accountDate(credit.expires_at, timezone)} · awaiting confirmation`;
  const days = Math.floor(minutes / 1440), hours = Math.floor(minutes % 1440 / 60);
  const countdown = days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
  return compact ? `Next known expiry · ${countdown}` : `${accountDate(credit.expires_at, timezone)} · in ${countdown}`;
}
export function resetSummary(summary: ResetCredits | null | undefined, timezone: string): string {
  if (!summary || summary.available_count === null) return "Banked resets unavailable";
  const count = `${summary.available_count} banked reset${summary.available_count === 1 ? "" : "s"}`;
  if (summary.available_count === 0) return count;
  const available = summary.credits?.filter(c => c.status === "available") || [];
  const next = available.filter(c => c.expires_at !== null).sort((a, b) => a.expires_at! - b.expires_at!)[0];
  const expiration = next ? expiryLabel(next, timezone, true)
    : summary.details_complete && available.length && available.every(c => c.expiration === "none")
      ? "No expiration" : "Expiration unavailable";
  return `${count} · ${expiration}`;
}
export function resetMarkup(summary: ResetCredits | null | undefined, timezone: string): string {
  if (!summary) return '<p class="account-muted">Banked reset details are unavailable for this account.</p>';
  const count = summary.available_count === null ? "Count unavailable" : `${summary.available_count} available`;
  return `<div class="account-section-heading"><h3>Banked resets</h3><strong>${count}</strong></div>
    ${summary.credits?.length ? `<ul class="reset-credit-list">${summary.credits.map(credit => `<li><div><strong>${esc(credit.title)}</strong><small>${esc(credit.status)}</small></div><span>${esc(expiryLabel(credit, timezone))}</span></li>`).join("")}</ul>`
      : `<p class="account-muted">${summary.available_count === 0 ? "No banked resets available." : "Expiration details have not been returned."}</p>`}
    ${!summary.details_complete && summary.available_count !== 0 ? '<p class="account-muted">Only some reset details may be available. The count above is reported by the service.</p>' : ""}`;
}
