import { icon } from "./icons";
import { compact } from "./format";
import { esc, count, segment } from "./ui";
import type { Dashboard } from "./types";
import { paperStackContent } from "./paper-stack";
import { equivalentSnapshot, type EquivalentBasis } from "./text-equivalents-data";

function content(data: Dashboard, basis: EquivalentBasis) {
  const snapshot = equivalentSnapshot(data, basis), e = snapshot.values;
  const cell = (symbol: string, value: string, label: string) =>
    `<div class="equivalent">${icon(symbol, 40)}<div><strong>${value}</strong><span>${label}</span></div></div>`;
  return {
    values: `${cell("book", e ? count(Math.round(e.novels)) : "—", "novels")}${cell("file", e ? compact(e.pages) : "—", "printed pages")}<div class="equivalent">${icon("ruler", 40)}<div id="paper-stack-value">${paperStackContent(data, basis)}</div></div>${cell("clock", e ? e.reading_years.toLocaleString("en-US", { maximumFractionDigits: 1 }) + " years" : "—", "continuous reading")}`,
    notes: `<p>${esc(snapshot.detail)}</p><p>${basis === "total" ? "Includes cached and repeated context; text equivalents do not count unique authored text." : "Output token equivalents include reasoning and tool output, not just visible prose."}</p><small>0.75 words/token · 90k words/novel · 500 words/page · 0.004 in/page · 150 words/min</small>`,
    extra: e ? `${count(e.words)} word equivalents · ${compact(e.floppy_disks)} floppy disks · ${e.typing_years.toFixed(1)} years of typing at 60 words/min` : "Token counters unavailable.",
  };
}

export function textEquivalents(data: Dashboard, basis: EquivalentBasis) {
  const parts = content(data, basis);
  return `<section id="text-equivalents" class="panel equivalents"><div class="panel-heading"><div><h2>Text equivalents</h2><button class="equivalents-explore" data-page="visualizations">Explore in 3D →</button></div>${segment("basis", [["total", "Total processed"], ["output", "Output only"]], basis)}</div><div id="text-equivalent-values" class="equivalent-grid">${parts.values}</div><div class="equivalent-notes"><div id="text-equivalent-notes">${parts.notes}</div><button id="equivalents-more" class="text-button">Show all equivalents ${icon("chevron", 15)}</button></div><div id="extra-equivalents" class="extra-equivalents" hidden>${parts.extra}</div></section>`;
}

/** Account polling updates numbers without replacing controls, focus or disclosure. */
export function updateTextEquivalents(data: Dashboard, basis: EquivalentBasis) {
  if (!document.getElementById("text-equivalents")) return;
  const parts = content(data, basis);
  for (const [id, markup] of [["text-equivalent-values", parts.values], ["text-equivalent-notes", parts.notes], ["extra-equivalents", parts.extra]]) {
    const element = document.getElementById(id);
    if (element && element.innerHTML !== markup) element.innerHTML = markup;
  }
}
