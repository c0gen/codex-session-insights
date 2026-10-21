import { sourceIndexHealth } from "../source-index-health";
import { legacySourceDetails } from "../legacy-sources";
import { icon } from "../icons";
import { shortDateTime } from "../format";
import { esc, count, button } from "../ui";
import type { Dashboard, Source } from "../types";
import { providerSetupCards } from "../provider-ui";
import { recoveryNotice } from '../claude-recovery';

const providerNames: Record<string, string> = { codex: "Codex", claude_code: "Claude Code", antigravity: "Antigravity" };

/** Reports drop absolute roots, so only demo sources may claim to be synthetic. */
function sourceOrigin(data: Dashboard, s: Source) {
  if (s.kind === "import") return "Compact usage snapshot";
  if (s.root) return esc(s.root);
  if (data.demo) return "Synthetic demo source";
  return data.readonly ? "Path hidden in saved report" : "";
}

export function sources(data: Dashboard) {
  return `${data.exporter ? '<section class="exporter-intro"><h2>Your usage, ready to travel.</h2><p>Index this Mac’s sessions, then save a compact usage snapshot to a USB drive or shared folder. Import it in the Windows dashboard. Conversation text stays here.</p></section>' : ""}${providerSetupCards(data.provider_setup)}${recoveryNotice(data.claude_recovery)}<div class="source-actions">${button("add-source", "Add session folder", "plus", true)}${button("import-snapshot", "Import snapshot", "upload")}${button("export-snapshot", "Export usage", "download")}${button("rebuild-index", "Rebuild index", "refresh")}${button("review-history", "Review conflicts", "database")}</div><div class="source-cards">${data.sources.map((s) => {
    const origin = sourceOrigin(data, s);
    return `<article class="panel source-card"><div class="source-title">${icon(s.kind === "import" ? "upload" : "laptop", 27)}<div><h2>${esc(s.label)}</h2><p>${esc(providerNames[s.provider || "codex"] || s.provider)} · ${s.kind === "import" ? "imported snapshot" : "local history"}</p>${origin ? `<p>${origin}</p>` : ""}</div><span class="status-pill ${["Offline", "No supported history", "Locked", "Unsupported", "Collection disabled"].includes(s.status) ? "muted" : ""}">${esc(s.status)}</span></div><div class="source-facts"><span><strong>${count(s.segments)}</strong> session segments</span><span>Last indexed <strong>${s.updated ? esc(shortDateTime(s.updated, data.timezone)) : "Not yet"}</strong></span>${s.last_activity ? `<span>Last activity <strong>${esc(shortDateTime(s.last_activity, data.timezone))}</strong></span>` : ""}${s.revision ? `<span>Snapshot revision <strong>${s.revision}</strong></span>` : ""}</div>${s.provider && s.provider !== "codex" ? `<p class="fine-print">Tokens require verified numeric usage records. Allowances come from optional official CLI checks or status lines. ${s.segments ? "" : "No readable history indexed yet; client history may be absent or this root may be offline."}</p>` : ""}${sourceIndexHealth(s)}${legacySourceDetails(s)}${s.detail ? `<p class="fine-print">${esc(s.detail)}</p>` : ""}<div class="source-footer"><label class="toggle-label"><input type="checkbox" data-enabled="${esc(s.id)}" ${s.enabled ? "checked" : ""}> Include in dashboard</label><button class="text-button danger" data-forget="${esc(s.id)}">Forget indexed history</button></div></article>`;
  }).join("")}</div><details class="panel source-help"><summary><h2>About snapshots</h2></summary><p>Each export contains timestamped usage and edit facts. Importing a newer snapshot replaces the previous one from that exporter. Identical copied chats count once.</p><p>Snapshots include project labels and session identities; they exclude prompts, responses, commands, patches, credentials, and absolute file paths.</p><p>Offline drives retain their last indexed history. Forgetting a source removes its indexed contribution and leaves original chats untouched.</p></details>`;
}
