import type { Dashboard } from "./types";
import { count, esc } from "./ui";

const names: Record<string, string> = { total: "Total tokens", input: "Input", cached: "Cache reads", writes: "Cache writes", output: "Output", reasoning: "Reasoning" };

function share(part: number, whole: number) {
  const value = (part / whole) * 100;
  return value > 0 && value < 0.1 ? "<0.1%" : `${value < 10 ? value.toFixed(1) : Math.round(value)}%`;
}

function metricGap(key: string, value: { state: string; available: number; observations: number }) {
  const missing = Math.max(0, value.observations - value.available);
  const detail = value.state === "unavailable" ? `not recorded in ${count(value.observations)} responses`
    : `missing in ${count(missing)} of ${count(value.observations)} responses (${share(missing, value.observations || 1)})`;
  return `${esc(names[key] || key)}: ${esc(value.state)} · ${detail}`;
}

export function metricCoverage(data: Dashboard) {
  const metrics = data.coverage.tokens?.metrics;
  const sources = data.sources.filter(s => s.enabled && (!data.filters?.provider || s.provider === data.filters.provider) && (!data.filters?.source_id || s.id === data.filters.source_id));
  const unavailable = sources.filter(s => s.format === "antigravity_legacy" && s.status !== "Available");
  const partial = Object.entries(metrics || {}).filter(([, value]) => value.state !== "complete");
  const missingCompletion = data.coverage.edit_completion_time_unavailable || 0;
  if (!partial.length && !unavailable.length && !missingCompletion) return "";
  // Near-complete counters are worth noting, not worth a warning.
  const minor = !unavailable.length && !missingCompletion && partial.every(([, v]) => v.state === "partial" && v.observations > 0 && v.available / v.observations >= 0.99);
  return `<div class="coverage-note${minor ? " minor" : ""}" aria-label="Metric coverage">${partial.length ? `<span>${partial.map(([key, value]) => metricGap(key, value)).join(" · ")}. Totals shown are recorded subtotals.</span>` : ""}${missingCompletion ? `<p>${missingCompletion} verified edits lack completion timestamps; their sizes are retained in exports and excluded from dated totals.</p>` : ""}${unavailable.length ? `<p>${unavailable.map(s => `${esc(s.label)}: ${esc(s.status)}`).join(" · ")}. Previously accepted history is retained.</p>` : ""}</div>`;
}

export function componentValue(data: Dashboard, key: string, value: number, format: (n: number) => string) {
  const state = data.coverage.tokens?.metrics?.[key]?.state;
  return state === "unavailable" ? "Unavailable" : format(value) + (state === "partial" ? " · partial" : "");
}
