import type { Dashboard } from "./types";

/** Older reports lack component coverage; retain their recorded aggregate values. */
export function metricState(data: Dashboard, key: "total" | "output" | "cached") {
  const coverage = data.coverage.tokens;
  return key === "total" ? coverage?.state ?? "complete"
    : coverage?.metrics?.[key]?.state ?? coverage?.state ?? "complete";
}

export function recordedMetric(data: Dashboard, key: "total" | "output" | "cached") {
  const state = metricState(data, key);
  const value = data.summary[key === "total" ? "total_tokens" : key === "output" ? "output_tokens" : "cached_tokens"];
  return { value: state === "unavailable" ? null : value, partial: state === "partial" };
}
