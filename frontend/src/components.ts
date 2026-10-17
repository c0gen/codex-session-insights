import { compact, currency } from "./charts";
import { count, esc, tip } from "./ui";
import type { Dashboard } from "./types";
import { tokenKpiContent } from "./token-kpi";

/** Seven-digit line counts don't fit side by side, so they shorten with the exact value on hover. */
const lineCount = (n: number) => n >= 1_000_000 ? `<span title="${esc(count(n))}">${compact(n)}</span>` : count(n);

export const tokenCard = (data: Dashboard) => `<article id="total-tokens-kpi" class="panel kpi">${tokenKpiContent(data)}</article>`;

export function costCard(data: Dashboard) {
  const s = data.summary;
  return `<article class="panel kpi"><div class="kpi-label">Estimated API-equivalent cost ${tip("Estimated model-token charges at configured request-date API rates. Claude uses logged speed/tier and geography; missing values assume Standard/global. The Fast-share setting applies only to Codex. This is not a subscription bill.")}</div><strong>${data.coverage.tokens?.state === "unavailable" ? "Unavailable" : s.total_tokens > 0 && s.priced_percent === 0 ? "Unpriced" : currency(s.cost)} <small>USD</small></strong><p>${s.priced_percent}% priced · ${data.filters?.provider === "claude_code" ? "Standard/global where unlogged" : data.settings.assumed_fast_percent ? "Codex: " + data.settings.assumed_fast_percent + "% Fast assumed where unlogged" : "Standard tier assumed where unlogged"}</p></article>`;
}

export function kpis(data: Dashboard) {
  const s = data.summary,
    totalChangedLines = s.lines_added + s.lines_removed;
  return `<div class="kpis">${tokenCard(data)}${costCard(data)}<article class="panel kpi changes"><div class="kpi-label">Observed line changes ${tip("Confirmed edits visible in logs, including repeated edits. Total changed lines is additions plus removals. Missing results and unsupported writes leave partial coverage.")}</div><div class="change-values"><div><strong>+${lineCount(s.lines_added)}</strong><small>added</small></div><div><strong>−${lineCount(s.lines_removed)}</strong><small>removed</small></div></div><div class="change-total"><span>Total changed lines</span><strong>${count(totalChangedLines)}</strong></div><p>${s.change_coverage === "partial" ? "Partial observation · repeated edits count" : s.change_coverage === "no_observed_changes" ? "No observed changes in logs" : "Repeated edits count"}</p></article><article class="panel kpi"><div class="kpi-label">Chats ${tip("Unique main chat IDs with activity in this range. Spawned and system agents are listed in Usage & Cost.")}</div><strong>${count(s.chats)}</strong><p>Main chats</p></article></div>`;
}
