import type { Dashboard } from "./types";
import { count, esc, tip } from "./ui";
import { metricState } from "./metric-availability";

const percent = (value: number) => `${new Intl.NumberFormat("en-US", { maximumSignificantDigits: 4 }).format(value)}%`;
export function discountAmount(value: number): string {
  if (value === 0) return "$0.00";
  const amount = Math.abs(value);
  const display = amount < 0.000001 ? amount.toExponential(3)
    : new Intl.NumberFormat("en-US", amount < 0.01
      ? { maximumSignificantDigits: 3 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount);
  return `${value < 0 ? "−" : ""}$${display}`;
}

/** Why a ratio is unavailable, from the same counter coverage the banner reports. */
function unavailableReason(data: Dashboard, key: "cached" | "reasoning", denominator: number) {
  const metric = data.coverage.tokens?.metrics?.[key];
  if (metric && metric.state !== "complete" && metric.observations > 0) {
    const missing = Math.max(0, metric.observations - metric.available);
    return metric.state === "unavailable" ? `Not recorded in ${count(metric.observations)} responses.`
      : `Missing in ${count(missing)} of ${count(metric.observations)} responses.`;
  }
  return denominator === 0 ? "No tokens in this view." : "No valid ratio in this view.";
}

export function usageMetrics(data: Dashboard): string {
  const m = data.usage_metrics;
  const basis = m?.reasoning_share_basis;
  const partialReasoning = basis && basis.included_responses < basis.total_responses;
  const reasoningDescription = partialReasoning
    ? `Recorded subset · ${count(basis.included_responses)} of ${count(basis.total_responses)} responses.`
    : "Reasoning tokens ÷ output tokens.";
  const reasoningNote = "Reasoning is already included in output. Only responses recording both counters enter this ratio."
    + (basis ? ` Recorded basis: ${count(basis.reasoning_tokens)} reasoning tokens ÷ ${count(basis.output_tokens)} output tokens; ${count(basis.included_responses)} of ${count(basis.total_responses)} responses.` : "");
  const reasoningUnavailable = !basis ? unavailableReason(data, "reasoning", data.summary.output_tokens)
    : !basis.total_responses ? "No recorded usage in this view."
    : !basis.included_responses ? "No responses record both reasoning and output counters."
    : !basis.output_tokens ? "No output tokens in recorded responses."
    : "No valid reasoning/output ratio in recorded responses.";
  const card = (id: string, label: string, value: string, detail: string, explanation: string) =>
    `<section class="panel usage-metric" id="${id}"><h3>${label} ${tip(explanation)}</h3><strong class="usage-metric-value">${esc(value)}</strong><p>${esc(detail)}</p></section>`;
  const cachedState = metricState(data, "cached");
  const discount = cachedState === "unavailable" ? null : m?.cache_discount_usd;
  // The card states the coverage in a few words; exact token counts stay in the help text.
  let coverage = "Unavailable in this snapshot.";
  let exact = "";
  if (m) {
    const partialPricing = m.cache_discount_priced_tokens < m.cache_discount_total_tokens;
    coverage = m.cache_discount_total_tokens === 0 ? "No cached reads · pricing not applicable."
      : partialPricing ? `${m.cache_discount_coverage_percent == null ? "Some" : percent(m.cache_discount_coverage_percent)} of cached tokens priced.`
        : "Fully priced.";
    if (m.cache_discount_total_tokens > 0) exact = ` Priced cached tokens: ${count(m.cache_discount_priced_tokens)} of ${count(m.cache_discount_total_tokens)}.`;
  }
  if (m && discount == null && m.cache_discount_total_tokens > 0) coverage = `No applicable cache prices. ${coverage}`;
  if (discount != null && discount < 0) coverage = `Estimated surcharge at selected rates. ${coverage}`;
  else if (discount != null && m && m.cache_discount_priced_tokens < m.cache_discount_total_tokens && m.cache_discount_priced_tokens > 0) coverage = `Priced subtotal only · ${coverage}`;
  if (cachedState === "unavailable") coverage = "Cached-token counters unavailable.";
  else if (cachedState === "partial") coverage = `Partial counter coverage · recorded subtotal only. ${coverage.replace("No cached reads", "No cached reads in recorded counters")}`;
  const ratio = (id: string, label: string, value: number | null | undefined, description: string, note: string, reason: string) => card(id, label,
    value == null ? "Unavailable" : percent(value), value == null ? reason : description,
    `${description} ${note} Calculated from aggregate counts. A zero denominator or a subset exceeding its denominator is unavailable. ${value == null ? "No valid ratio in this snapshot." : `Exact value: ${value}%.`}`);
  return `<div class="usage-metrics" aria-label="Cache and reasoning metrics">${card("cache-discount", "Estimated cache discount",
    discount == null ? "Unavailable" : discountAmount(discount), coverage,
    `API-equivalent estimate, not subscription savings: cached read tokens × (selected uncached-input price − cached-input price). Input volume, output and cache-write charges stay unchanged. A negative difference is a surcharge.${exact} ${discount == null ? "No estimate in this snapshot." : `Exact signed difference: ${discount} USD.`}`)}${ratio("cache-reuse", "Cache reuse rate", m?.cache_reuse_percent,
      "Cached reads ÷ all input tokens.", "Cache reads and writes are subsets of input.", unavailableReason(data, "cached", data.summary.input_tokens))}${ratio("reasoning-share", "Reasoning share", m?.reasoning_share_percent,
      reasoningDescription, reasoningNote, reasoningUnavailable)}</div>`;
}
