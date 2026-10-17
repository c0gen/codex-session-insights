import type { Dashboard } from "./types";

/** Account lifetime counters replace Codex logs; other tools remain indexed. */
export function dashboardTokenTotal(data: Dashboard) {
  if (data.demo || data.exporter || data.readonly || !data.indexed_token_totals) return undefined;
  const reported = data.account_token_total;
  const hasReported = typeof reported?.total_tokens === "number";
  const indexed = data.indexed_token_totals;
  const values: number[] = [];
  const breakdown: string[] = [];
  let partial = false;
  const fallback = !hasReported;
  if (hasReported) {
    values.push(reported!.total_tokens!);
    partial = reported!.reported_accounts < reported!.accounts || !reported!.identity_complete;
    breakdown.push(`Codex: ${reported!.total_tokens!.toLocaleString("en-US")} reported lifetime tokens.`);
    if (!reported!.identity_complete) breakdown.push("Account identities unresolved; duplicate connections may remain in this total.");
    if (reported!.reported_accounts < reported!.accounts) breakdown.push("Some Codex accounts have not returned lifetime counters.");
  }
  for (const [provider, name] of [["codex", "Codex"], ["claude_code", "Claude Code"], ["antigravity", "Antigravity"]] as const) {
    if (provider === "codex" && hasReported) continue;
    const total = indexed[provider];
    if (typeof total?.total_tokens === "number") {
      values.push(total.total_tokens);
      partial ||= total.state !== "complete";
      breakdown.push(`${name}: ${total.total_tokens.toLocaleString("en-US")} indexed tokens${total.state !== "complete" ? " (partial coverage)" : ""}.`);
    } else if ((total?.sessions || 0) > 0 || (provider === "codex" && (reported?.accounts || 0) > 0)) {
      partial = true;
      breakdown.push(`${name}: token counters unavailable.`);
    }
  }
  return { total: values.length ? values.reduce((sum, value) => sum + value, 0) : null,
    partial, stale: hasReported && !!reported?.stale, fallback, breakdown };
}
