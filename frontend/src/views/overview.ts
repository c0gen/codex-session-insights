import { icon } from "../icons";
import { textEquivalents } from "../text-equivalents";
import { metricState } from "../metric-availability";
import { compact, currency } from "../charts";
import { esc, count, dateLabel, tip, button, segment } from "../ui";
import { kpis } from "../components";
import type { Dashboard } from "../types";
export function overview(
  data: Dashboard,
  mode: "tokens" | "cost" | "prompts" | "lines",
  basis: "total" | "output",
  tokenActivity: string,
) {
  const s = data.summary,
    h = data.highlights;
  const percent = Math.min((s.total_tokens / h.milestone) * 100, 100);
  return `${kpis(data)}${tokenActivity}<div class="overview-middle"><section class="panel activity"><div class="panel-heading"><div><h2>Activity</h2><p>Daily totals · ${esc(data.timezone)}</p></div>${segment(
    "activity",
    [
      ["tokens", "Tokens"],
      ["cost", "Cost"],
      ["prompts", "Prompts"],
      ["lines", "Line changes"],
    ],
    mode,
  )}</div><div class="chart-area"><canvas id="activity-chart" aria-label="Daily activity chart" role="img"></canvas></div><div class="activity-footer"><span>${icon("calendar", 22)}<strong>${count(s.active_days)} active days</strong>${tip("Days containing at least one user prompt in the selected range.")}</span><span>${icon("flame", 22)}<strong>${s.current ? `${count(s.current)}-day current streak` : "No current streak"}</strong>${tip("Consecutive prompt-active days ending today or yesterday. Longest in this range: " + s.longest + " days.")}</span></div></section><aside class="panel highlights"><h2>Highlights</h2><div class="highlight"><div>${icon("chart")}<span>Biggest usage day</span></div><strong>${data.coverage.tokens?.state === "unavailable" ? "Unavailable" : compact(h.busiest?.tokens || 0) + " tokens"}</strong><small>${h.busiest ? dateLabel(h.busiest.day) : "—"}</small></div><div class="highlight"><div>${icon("money")}<span>Most expensive day</span></div><strong>${h.expensive ? currency(h.expensive.cost) : "Unavailable"}</strong><small>${h.expensive ? dateLabel(h.expensive.day) : "—"}</small></div><div class="highlight milestone"><div>${icon("flag")}<span>Next token milestone</span></div><strong>${metricState(data, "total") === "unavailable" ? "Unavailable" : compact(h.milestone) + " tokens"}</strong><div class="progress-track" ${metricState(data, "total") === "unavailable" ? "hidden" : ""}><div style="width:${percent}%"></div></div><div class="progress-label" ${metricState(data, "total") === "unavailable" ? "hidden" : ""}><span>${compact(s.total_tokens)} of ${compact(h.milestone)}</span><span>${percent.toFixed(0)}%</span></div><p>${metricState(data, "total") === "unavailable" ? "Token counters unavailable" : compact(h.milestone - s.total_tokens) + " tokens to go"}</p></div></aside></div>${textEquivalents(data, basis)}`;
}
