import type { ProviderAllowance } from "./types";
import { esc } from "./ui";
import { accountDate } from "./account-credits";
import { tooltipAttributes } from "./widget-presentation";
import { MAX_READING_AGE, asOfText, limitState, limitWindowMarkup, readingAged, sourceText, validBucket } from "./claude-limits";

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const names: Record<string, string> = { claude_code: "Claude", antigravity: "Antigravity" };

/** Keep the last reading visible, labeled by age, instead of dropping it after five minutes. */
export function visibleWidgetProviders(profiles?: ProviderAllowance[], now = Date.now() / 1000): ProviderAllowance[] {
  if (!Array.isArray(profiles)) return [];
  return profiles.flatMap(profile => {
    if (!profile || !finite(profile.received_at) || now < profile.received_at || now - profile.received_at >= MAX_READING_AGE || !Array.isArray(profile.buckets)) return [];
    const buckets = profile.buckets.filter(validBucket);
    return buckets.length ? [{ ...profile, buckets }] : [];
  });
}

export function renderWidgetProviders(profiles: ProviderAllowance[] | undefined, timezone: string, now = Date.now() / 1000) {
  return visibleWidgetProviders(profiles, now).map(profile => {
    const received = profile.received_at!;
    const aged = readingAged(profile, now);
    const stale = profile.buckets.some(bucket => limitState(bucket, now, aged) !== "fresh");
    const updated = `<span class="allowance-update" ${tooltipAttributes(`${asOfText(received, timezone, now)} · ${accountDate(received, timezone)} · ${sourceText(profile)}`)}>${esc(asOfText(received, timezone, now))}</span>`;
    return `<section class="provider-allowance widget-account" data-provider="${esc(profile.provider)}"${stale ? " data-stale" : ""}>
    <div class="widget-account-heading"><h2>${esc(names[profile.provider] || profile.provider)}${stale ? ' <b class="allowance-stale">Stale</b>' : ""}</h2></div>
    ${profile.buckets.map((bucket, index) => limitWindowMarkup(bucket, timezone, now, true, index === profile.buckets.length - 1 ? updated : "", aged)).join("")}</section>`;
  }).join("");
}
