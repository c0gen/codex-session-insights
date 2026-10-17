import { componentValue } from "../metric-coverage";
import { compact } from "../charts";
import { esc, count, tip, button, segment } from "../ui";
import { costCard, tokenCard } from "../components";
import type { Dashboard } from "../types";
import { usageMetrics } from "../usage-metrics";
import { sessionSeries } from "../daily-sessions-chart";

/** Same names as the Chats and agents per day legend, main chats first. */
const agentLabels: Record<string, string> = {
  top_level: sessionSeries[0].label,
  spawned_subagent: sessionSeries[1].label,
  system_subagent: sessionSeries[2].label,
  embedded_subagents: "Embedded sub-agents",
};
const agentOrder = Object.keys(agentLabels);
const tierLabels: Record<string, string> = { standard: "Standard", priority: "Priority", flex: "Flex", fast: "Fast", default: "Default", auto: "Auto" };
const capitalized = (value: string) => value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " ");

export function usage(data: Dashboard, modelMode: "tokens" | "cost", dailySessions = "") {
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
      data.coverage.tokens?.reasoning !== "recorded" ? "Output (breakdown incomplete)" : "Other output",
      data.coverage.tokens?.reasoning === "recorded" ? Math.max(s.output_tokens - s.reasoning_tokens, 0) : s.output_tokens,
      "#82b8ee",
    ],
    ["Reasoning", data.coverage.tokens?.reasoning === "recorded" ? s.reasoning_tokens : 0, "#a795d9"],
  ] as const;
  const volume = components.reduce((a, c) => a + c[1], 0) || 1;
  // With partial counters the shares describe the recorded subtotal, so say so instead of hiding them.
  const recordedOnly = data.coverage.tokens?.state === "partial" || data.coverage.tokens?.reasoning !== "recorded";
  const cells = new Map(
    data.heatmap.map((c) => [c.weekday + ":" + c.hour, c.count]),
  );
  const max = Math.max(1, ...data.heatmap.map((c) => c.count));
  const agents = [...data.agents].sort((a, b) => {
    const rank = (name: string) => agentOrder.includes(name) ? agentOrder.indexOf(name) : agentOrder.length;
    return rank(a.name) - rank(b.name);
  });
  const unlogged = data.filters?.provider === "claude_code" ? "Standard/global assumed" : data.settings.assumed_fast_percent ? `Codex: ${data.settings.assumed_fast_percent}% Fast assumed` : "Standard assumed";
  return `<div class="usage-summary"><div class="kpis usage-kpis">${tokenCard(data)}${costCard(data)}</div>${usageMetrics(data)}</div><div class="usage-grid"><section class="panel"><div class="panel-heading"><div><h2>Token composition</h2><p>Cache and reasoning counts are subsets</p></div>${recordedOnly ? '<small class="composition-scope">Shares of recorded counters</small>' : ""}</div><div class="composition-bar">${components.map(([label, n, color]) => `<span style="width:${(n / volume) * 100}%;background:${color}" title="${label}: ${count(n)}"></span>`).join("")}</div><div class="component-list">${components.map(([label, n, color]) => `<div><span><i style="background:${color}"></i>${label}</span><strong>${componentValue(data, label === "Reasoning" ? "reasoning" : label === "Cache writes" ? "writes" : label === "Cached input" ? "cached" : label === "Uncached input" ? "input" : "output", label === "Reasoning" ? s.reasoning_tokens : n, compact)}</strong><small>${label === "Reasoning" && data.coverage.tokens?.reasoning !== "recorded" ? "—" : ((n / volume) * 100).toFixed(1) + "%"}</small></div>`).join("")}</div><p class="fine-print">${count(s.input_tokens)} input · ${count(s.output_tokens)} output. Provider total: ${count(s.total_tokens)}. Component totals can differ from provider totals.</p></section><section class="panel"><div class="panel-heading"><div><h2>Models</h2><p>Usage at a glance</p></div>${segment(
    "model",
    [
      ["tokens", "Tokens"],
      ["cost", "Cost"],
    ],
    modelMode,
  )}</div><div class="model-chart-area"><canvas id="model-chart" role="img" aria-label="Usage by model"></canvas></div></section></div>${dailySessions}<section class="panel heatmap-panel"><div class="panel-heading"><div><h2>When you prompt</h2><p>User prompts · ${esc(data.timezone)}</p></div><small>Less <span class="heat-legend"></span> More</small></div><div class="heatmap"><div class="hour-labels"><span></span>${Array.from({ length: 24 }, (_, h) => `<small>${h % 3 === 0 ? String(h).padStart(2, "0") : ""}</small>`).join("")}</div>${[
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
    )}</div></section><div class="usage-grid"><section class="panel"><div class="panel-heading"><h2>Agent usage</h2></div><div class="component-list">${agents.map((a) => `<div><span>${esc(agentLabels[a.name] || capitalized(a.name))}</span><strong>${a.tokens === null ? "Included in parent accounting" : compact(a.tokens)}</strong><small>${count(a.sessions)} sessions</small></div>`).join("")}</div><p class="fine-print">Session counts represent recorded activity, including system and spawned agents.</p></section><section class="panel"><div class="panel-heading"><h2>Pricing & coverage</h2>${button("settings-inline", "Settings", "settings")}</div><div class="component-list"><div><span>Priced token coverage</span><strong>${s.priced_percent}%</strong></div><div><span>Verified replay excluded ${tip("Inherited history in spawned agents that was matched against its parent and removed so it isn't counted twice.")}</span><strong>${compact(data.coverage.replay_tokens)}</strong></div><div><span>Unresolved histories ${tip("Spawned-agent histories whose parent was missing or couldn't be aligned. Inherited history in them couldn't be verified, so their recorded usage is counted as logged.")}</span><strong>${count(data.coverage.unresolved)}</strong></div>${data.tiers.length ? `<div class="component-subheading"><span>Service tier</span></div>${data.tiers.map((t) => `<div><span>${esc(t.name === "Not logged" ? `Not logged · ${unlogged}` : tierLabels[t.name] || capitalized(t.name))}</span><strong>${compact(t.tokens)}</strong><small>${count(t.responses)} responses</small></div>`).join("")}` : ""}</div><p class="fine-print">Dated API-equivalent rates where verified · unknown models and missing price components remain unpriced · Claude assumes Standard/global where unlogged; the Fast-share setting applies only to Codex · USD · <a href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noopener">OpenAI API pricing</a> · <a href="https://platform.claude.com/docs/en/about-claude/pricing" target="_blank" rel="noopener">Anthropic API pricing</a></p></section></div>`;
}
