import { icon } from "../icons";
import { compact, currency } from "../charts";
import { esc, count, dateLabel, tip, button, segment } from "../ui";
import { kpis } from "../components";
import type { Dashboard } from "../types";
export function usage(data: Dashboard, modelMode: "tokens" | "cost") {
  const s = data.summary;
  const components = [
    [
      "Uncached input",
      Math.max(s.input_tokens - s.cached_tokens - s.cache_write_tokens, 0),
      "#62e5bf",
    ],
    ["Cached input", s.cached_tokens, "#479b86"],
    ["Cache writes", s.cache_write_tokens, "#e6c17d"],
    [
      "Other output",
      Math.max(s.output_tokens - s.reasoning_tokens, 0),
      "#82b8ee",
    ],
    ["Reasoning", s.reasoning_tokens, "#a795d9"],
  ] as const;
  const volume = components.reduce((a, c) => a + c[1], 0) || 1;
  const cells = new Map(
    data.heatmap.map((c) => [c.weekday + ":" + c.hour, c.count]),
  );
  const max = Math.max(1, ...data.heatmap.map((c) => c.count));
  return `${kpis(data)}<div class="usage-grid"><section class="panel"><div class="panel-heading"><div><h2>Token composition</h2><p>Cache and reasoning counts are subsets</p></div></div><div class="composition-bar">${components.map(([label, n, color]) => `<span style="width:${(n / volume) * 100}%;background:${color}" title="${label}: ${count(n)}"></span>`).join("")}</div><div class="component-list">${components.map(([label, n, color]) => `<div><span><i style="background:${color}"></i>${label}</span><strong>${compact(n)}</strong><small>${((n / volume) * 100).toFixed(1)}%</small></div>`).join("")}</div><p class="fine-print">${count(s.input_tokens)} input · ${count(s.output_tokens)} output. Provider total: ${count(s.total_tokens)}. Component totals can differ from provider totals.</p></section><section class="panel"><div class="panel-heading"><div><h2>Models</h2><p>Usage at a glance</p></div>${segment(
    "model",
    [
      ["tokens", "Tokens"],
      ["cost", "Cost"],
    ],
    modelMode,
  )}</div><div class="model-chart-area"><canvas id="model-chart" role="img" aria-label="Usage by model"></canvas></div></section></div><section class="panel heatmap-panel"><div class="panel-heading"><div><h2>When you prompt</h2><p>User prompts · ${esc(data.timezone)}</p></div><small>Less <span class="heat-legend"></span> More</small></div><div class="heatmap"><div class="hour-labels"><span></span>${Array.from({ length: 24 }, (_, h) => `<small>${h % 3 === 0 ? String(h).padStart(2, "0") : ""}</small>`).join("")}</div>${[
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
  ]
    .map(
      (label, d) =>
        `<div class="heat-row"><span>${label}</span>${Array.from(
          { length: 24 },
          (_, h) => {
            const n = cells.get(d + ":" + h) || 0;
            return `<div tabindex="0" style="background:rgba(89,222,181,${0.05 + (n / max) * 0.85})" title="${label} ${String(h).padStart(2, "0")}:00 · ${count(n)} prompts"></div>`;
          },
        ).join("")}</div>`,
    )
    .join(
      "",
    )}</div></section><div class="usage-grid"><section class="panel"><div class="panel-heading"><h2>Agent usage</h2></div><div class="component-list">${data.agents.map((a) => `<div><span>${esc(a.name.replaceAll("_", " "))}</span><strong>${compact(a.tokens)}</strong><small>${count(a.sessions)} sessions</small></div>`).join("")}</div><p class="fine-print">Session counts represent recorded activity, including system and spawned agents.</p></section><section class="panel"><div class="panel-heading"><h2>Pricing & coverage</h2>${button("settings-inline", "Settings", "settings")}</div><div class="component-list"><div><span>Priced token coverage</span><strong>${s.priced_percent}%</strong></div><div><span>Verified replay excluded</span><strong>${compact(data.coverage.replay_tokens)}</strong></div><div><span>Unresolved histories</span><strong>${data.coverage.unresolved}</strong></div>${data.tiers.map((t) => `<div><span>${esc(t.name)}</span><strong>${compact(t.tokens)}</strong><small>${count(t.responses)} responses</small></div>`).join("")}</div><p class="fine-print">Historical model rates · USD · <a href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noopener">OpenAI API pricing</a></p></section></div>`;
}
