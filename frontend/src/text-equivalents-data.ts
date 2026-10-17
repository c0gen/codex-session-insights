import type { Dashboard, Equivalents } from "./types";
import { dashboardTokenTotal } from "./dashboard-token-total";
import { recordedMetric } from "./metric-availability";

export type EquivalentBasis = "total" | "output";

export function convertTokens(tokens: number): Equivalents {
  const words = tokens * 0.75, pages = Math.ceil(words / 500);
  return { words: Math.round(words), novels: words / 90000, pages,
    stack_meters: pages * 0.004 * 0.0254, reading_years: words / 150 / 60 / 24 / 365.25,
    typing_years: words / 60 / 60 / 24 / 365.25, floppy_disks: tokens * 4 / 1440000 };
}

/** All total-based equivalents share the headline's deduplicated provider total. */
export function equivalentSnapshot(data: Dashboard, basis: EquivalentBasis) {
  const combined = basis === "total" ? dashboardTokenTotal(data) : undefined;
  const recorded = recordedMetric(data, basis);
  const tokens = combined ? combined.total : recorded.value;
  const partial = combined ? combined.partial : recorded.partial;
  const stale = combined?.stale ?? false;
  const scope = combined
    ? "All-time combined total · reported Codex lifetime tokens plus indexed usage from other tools · independent of dashboard filters."
    : basis === "output"
      ? "Recorded output in the filtered view · the Codex lifetime counter does not provide an output breakdown."
      : "Analyzed tokens in this filtered snapshot.";
  const detail = [scope, combined?.fallback ? "Indexed Codex fallback." : "",
    tokens === null ? "Token counters unavailable." : `${tokens.toLocaleString("en-US")} tokens.`,
    partial ? combined ? "Partial or unverified coverage; see the Total tokens breakdown." : "Partial coverage · recorded subtotal only." : "",
    stale ? "Stale account data." : ""].filter(Boolean).join(" ");
  return { tokens, partial, stale, detail, values: tokens === null ? null : convertTokens(tokens) };
}
