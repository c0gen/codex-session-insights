import { compact } from "./format";
import { tip } from "./ui";
import type { Dashboard } from "./types";
import { dashboardTokenTotal } from "./dashboard-token-total";

/** The lifetime headline and filtered analyzed count have separate scopes. */
export function tokenKpiContent(data: Dashboard) {
  const analyzed = data.summary.total_tokens;
  const coverage = data.coverage.tokens?.state;
  const missing = coverage === "unavailable";
  const partial = coverage === "partial";
  const combined = dashboardTokenTotal(data);
  if (combined) {
    const help = ["All-time reported Codex lifetime usage plus indexed Claude Code and Antigravity usage across enabled sources. Independent of tool, date, project, model and source filters.",
      ...combined.breakdown, combined.fallback ? "Indexed Codex fallback: no account lifetime counter is available." : "Codex transcript usage is excluded to avoid counting it twice."].join(" ");
    return `<div class="kpi-label">Total tokens ${tip(help, "total-tokens-help")}</div><strong>${combined.total === null ? "—" : compact(combined.total)}${combined.total !== null && combined.partial ? '<small>partial</small>' : ""}${combined.stale ? '<small>stale</small>' : ""}</strong>
      <p class="token-analyzed">Analyzed tokens in this view: ${missing ? "Unavailable" : compact(analyzed)}${!missing && partial ? " · partial coverage" : ""}</p>
      ${combined.total === null ? '<p>Token counters unavailable</p>' : ""}${combined.fallback ? '<p>Indexed Codex fallback</p>' : ""}`;
  }
  return `<div class="kpi-label">Analyzed tokens ${tip("Combined transcript usage under the selected tool, date, project, model and source filters. Cache reads and writes are included. Account lifetime counters remain on account cards.", "total-tokens-help")}</div><strong>${missing ? "—" : compact(analyzed)}${partial ? '<small>partial</small>' : ""}</strong><p>${missing ? "Token counters unavailable" : partial ? "Partial coverage · some responses lack complete counters" : "Includes cached and repeated context"}</p>`;
}

export function updateTokenKpi(data: Dashboard) {
  const root = document.querySelector<HTMLElement>("#total-tokens-kpi");
  if (!root) return;
  const markup = tokenKpiContent(data);
  if (root.dataset.markup === markup) return;
  const focused = root.contains(document.activeElement);
  root.innerHTML = markup;
  root.dataset.markup = markup;
  if (focused) root.querySelector<HTMLElement>(".info")?.focus({ preventScroll: true });
}
