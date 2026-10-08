import { icon } from "../icons";
import { compact, currency } from "../charts";
import { esc, count, dateLabel, tip, button, segment } from "../ui";
import { kpis } from "../components";
import type { Dashboard } from "../types";
export function overview(
  data: Dashboard,
  mode: "tokens" | "cost" | "prompts" | "lines",
  basis: "total" | "output",
) {
  const s = data.summary,
    h = data.highlights,
    e = data.equivalents[basis];
  const percent = Math.min((s.total_tokens / h.milestone) * 100, 100);
  const equivalence = (symbol: string, n: string, label: string) =>
    `<div class="equivalent">${icon(symbol, 40)}<div><strong>${n}</strong><span>${label}</span></div></div>`;
  return `${kpis(data)}<div class="overview-middle"><section class="panel activity"><div class="panel-heading"><div><h2>Activity</h2><p>Daily totals · ${esc(data.timezone)}</p></div>${segment(
    "activity",
    [
      ["tokens", "Tokens"],
      ["cost", "Cost"],
      ["prompts", "Prompts"],
      ["lines", "Line changes"],
    ],
    mode,
  )}</div><div class="chart-area"><canvas id="activity-chart" aria-label="Daily activity chart" role="img"></canvas></div><div class="activity-footer"><span>${icon("calendar", 22)}<strong>${count(s.active_days)} active days</strong>${tip("Days containing at least one user prompt in the selected range.")}</span><span>${icon("flame", 22)}<strong>${s.current}-day current streak</strong>${tip("Consecutive prompt-active days ending today or yesterday. Longest in this range: " + s.longest + " days.")}</span></div></section><aside class="panel highlights"><h2>Highlights</h2><div class="highlight"><div>${icon("chart")}<span>Biggest usage day</span></div><strong>${compact(h.busiest?.tokens || 0)} tokens</strong><small>${h.busiest ? dateLabel(h.busiest.day) : "—"}</small></div><div class="highlight"><div>${icon("money")}<span>Most expensive day</span></div><strong>${currency(h.expensive?.cost || 0)}</strong><small>${h.expensive ? dateLabel(h.expensive.day) : "—"}</small></div><div class="highlight milestone"><div>${icon("flag")}<span>Next token milestone</span></div><strong>${compact(h.milestone)} tokens</strong><div class="progress-track"><div style="width:${percent}%"></div></div><div class="progress-label"><span>${compact(s.total_tokens)} of ${compact(h.milestone)}</span><span>${percent.toFixed(0)}%</span></div><p>${compact(h.milestone - s.total_tokens)} tokens to go</p></div></aside></div><section class="panel equivalents"><div class="panel-heading"><h2>Text equivalents</h2>${segment(
    "basis",
    [
      ["total", "Total processed"],
      ["output", "Output only"],
    ],
    basis,
  )}</div><div class="equivalent-grid">${equivalence("book", count(Math.round(e.novels)), "novels")}${equivalence("file", compact(e.pages), "printed pages")}${equivalence("ruler", e.stack_meters >= 1000 ? compact(e.stack_meters / 1000) + " km" : compact(e.stack_meters) + " m", "paper stack")}${equivalence("clock", e.reading_years.toLocaleString("en-US", { maximumFractionDigits: 1 }) + " years", "continuous reading")}</div><div class="equivalent-notes"><div><p>${basis === "total" ? "Includes cached and repeated context; text equivalents do not count unique authored text." : "Output token equivalents include reasoning and tool output, not just visible prose."}</p><small>0.75 words/token · 90k words/novel · 500 words/page · 0.004 in/page · 150 words/min</small></div><button id="equivalents-more" class="text-button">Show all equivalents ${icon("chevron", 15)}</button></div><div id="extra-equivalents" class="extra-equivalents" hidden>${count(e.words)} word equivalents · ${compact(e.floppy_disks)} floppy disks · ${e.typing_years.toFixed(1)} years of typing at 60 words/min</div></section>`;
}
