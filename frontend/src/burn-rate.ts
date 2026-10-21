import { burnCoverageHelp, burnCoverageMarkup } from "./burn-coverage";
import type { BurnRateEstimate, UsageLimits } from "./types";
import { compact, currency } from "./format";
import { esc } from "./ui";

function observedDuration(seconds: number): string {
  const total = Math.floor(seconds), minutes = Math.floor(total / 60), rest = total % 60;
  return minutes ? `${minutes}m${rest ? ` ${rest}s` : ""}` : `${rest}s`;
}

function pricingCoverage(rate: BurnRateEstimate): string {
  if (rate.total_tokens === undefined || rate.priced_tokens === undefined) return "";
  if (!rate.total_tokens) return "No recent usage";
  const percent = rate.priced_tokens / rate.total_tokens * 100;
  const amount = percent > 99.9 && percent < 100 ? ">99.9" : percent > 0 && percent < 0.1 ? "<0.1" : Number(percent.toFixed(1));
  return `${amount}% priced`;
}

function pricingHelp(rate: BurnRateEstimate): string {
  const parts = [
    "API-equivalent token cost in USD, not a subscription bill.",
    "Uses the same dated model, input, cached-input, output, cache-write, service-tier and long-context rates as Usage & Cost, including Settings assumptions for unlogged tiers.",
    "Excludes non-token tool and service charges.",
  ];
  if (rate.total_tokens !== undefined && rate.priced_tokens !== undefined) {
    parts.push(`Pricing coverage: ${rate.priced_tokens.toLocaleString("en-US")} of ${rate.total_tokens.toLocaleString("en-US")} tokens.`);
    if (rate.total_tokens > rate.priced_tokens)
      parts.push(rate.priced_tokens ? "Unpriced usage is excluded; the dollar amount is only the priced subtotal." : "No API price is available for this usage.");
  }
  if (rate.value !== null && Number.isFinite(rate.value)) parts.push(`Unrounded rate: ${rate.value} USD/min.`);
  return ` ${parts.join(" ")}`;
}

/** Shared by full-size allowance displays; compact widgets omit these rows. */
export function burnRateMarkup(rate: BurnRateEstimate | undefined, kind: "tokens" | "cost" | "allowance", identity: string[]): string {
  if (!rate) return "";
  const id = `burn-rate-${kind}-${encodeURIComponent(JSON.stringify(identity))}`;
  const local = kind !== "allowance", cost = kind === "cost";
  const label = cost ? "Local dollar burn" : local ? "Local token burn" : "Allowance burn";
  const numeric = rate.value !== null && Number.isFinite(rate.value);
  const amount = numeric ? rate.value! > 0 && rate.value! < 0.01 ? "<0.01" : compact(rate.value!) : "";
  const dollars = numeric ? rate.value! > 0 && rate.value! < 0.01 ? "<$0.01" : currency(rate.value!) : "";
  const value = rate.status === "collecting" ? local ? "Waiting for indexing…" : "Collecting data…" : numeric
    ? cost ? `${dollars}/min` : local ? `${amount} tokens/min` : `${amount}%/hr` : "Unavailable";
  const duration = observedDuration(rate.observed_seconds);
  const partial = rate.observed_seconds > 0 && rate.observed_seconds < 300;
  const scope = local
    ? `${cost ? "USD" : "Tokens"} per minute from enabled local Codex session folders, across projects and accounts. Local logs do not reliably identify accounts. Excludes imported snapshots; independent of allowance buckets and analytics filters. Updates with local session indexing.`
    : "Percentage points of this allowance window consumed per hour (%/hr), independent of analytics filters.";
  const calculation = local
    ? "Uses recorded event timestamps within the last five minutes. Updates as local usage is indexed; no five-minute warm-up is needed."
    : "Uses actual time between readings, retaining the reading before the five-minute cutoff. At least two readings spanning 60 seconds are required.";
  const pricing = cost ? pricingHelp(rate) : "";
  const help = `${scope} Five-minute trailing estimate, including idle time. ${calculation}${pricing} ${rate.observed_seconds > 0 ? `Observed interval: ${duration}.` : local ? "Waiting for local indexing." : "Waiting for observations."}${rate.updated_at === null ? "" : ` Latest ${local ? "verified source check" : "reading"}: ${new Date(rate.updated_at * 1000).toLocaleString()}.`}${burnCoverageHelp(rate)}`;
  const coverage = cost ? pricingCoverage(rate) : "";
  return `<div id="${esc(id)}" class="burn-rate burn-rate-${kind}" data-status="${esc(rate.status)}" role="group" tabindex="0" aria-label="${esc(`${label}. ${value}. ${help}`)}" title="${esc(help)}"><span>${label} · <strong>${esc(value)}</strong>${burnCoverageMarkup(rate, id)}</span><span class="burn-rate-period">5m estimate${partial ? ` · ${duration} observed` : ""}${cost ? " · API-equivalent" : ""}${coverage ? ` · ${esc(coverage)}` : ""}</span></div>`;
}

export function localBurnRatesMarkup(rates: Pick<UsageLimits, "token_burn_rate" | "cost_burn_rate">, identity: string[]): string {
  const markup = burnRateMarkup(rates.token_burn_rate, "tokens", identity) + burnRateMarkup(rates.cost_burn_rate, "cost", identity);
  return markup ? `<div class="local-burn-rates">${markup}</div>` : "";
}
