import { call } from "./api";
import { esc, count } from "./ui";
import { shortDateTime } from "./format";
import type { Dashboard } from "./types";
import "./history-review.css";

interface Version {
  id: string;
  source: string;
  locations: string[];
  records: number;
  recorded_tokens: number | null;
  first_activity: string;
  last_activity: string;
  accepted: boolean;
  classification?: string;
  parent_session_id?: string | null;
  format: string;
}
export interface HistoryConflict {
  id: string;
  session_id: string;
  kind: "copy" | "accounting" | "identity";
  state: "needs_review" | "awaiting_verification" | "manually_resolved" | "verified";
  reason: string;
  revision: string;
  has_selection: boolean;
  versions: Version[];
  reason_code?: string;
  alternative_only_tokens?: number;
  alternative_only_responses?: number;
  disputed_responses?: number;
}

function evidenceNote(group: HistoryConflict) {
  if (group.alternative_only_tokens === undefined) return '';
  return `<p>${count(group.alternative_only_responses || 0)} alternative-only responses · ${count(group.alternative_only_tokens)} potentially excluded tokens. These are deduplicated against accepted responses; they are not verified recoverable usage.${group.disputed_responses ? ` ${count(group.disputed_responses)} ${group.disputed_responses === 1 ? "response has" : "responses have"} disputed counters.` : ''}</p>`;
}

export function coverageNotice(data: Dashboard) {
  const c = data.coverage;
  const parts = [c.conflicts ? `${count(c.conflicts)} copy conflicts` : "",
    c.identity_issues ? `${count(c.identity_issues)} agent identity observations need verification` : '',
    c.accounting_overlaps ? `${count(c.accounting_overlaps)} accounting overlaps` : "",
    c.awaiting_verification ? `${count(c.awaiting_verification)} awaiting verification` : "",
    c.parse_errors ? `${count(c.parse_errors)} unparsed records` : ""].filter(Boolean);
  if (!parts.length) return "";
  return `<div class="coverage-note">${parts.join(" · ")}. Accepted totals may exclude activity in alternative histories.${!data.readonly ? ' <button id="review-history-banner" class="text-button">Review conflicts</button>' : " Open the desktop app to review."}</div>`;
}

export function reviewBody(groups: HistoryConflict[], zone: string) {
  if (!groups.length) return '<p>No histories need review. Verified copies and extensions are reconciled automatically.</p>';
  const labels = { needs_review: "Needs review", awaiting_verification: "Awaiting verification", manually_resolved: "Selection saved", verified: "Verified" };
  return `<p>Verified copies count once. For disagreements, choose the version that should contribute usage. All retained alternatives stay available.</p>${groups.map((g, index) => `<section class="history-group" data-history-group="${index}"><h3>${esc(g.session_id)}</h3><p><strong>${labels[g.state]}</strong> · ${g.kind === "identity" || g.reason_code === "claude_identity_unverified" ? "Agent identity" : g.kind === "copy" ? "Copied history" : "Accounting formats"}</p><p>${esc(g.reason)}</p>${evidenceNote(g)}${g.versions.map((v, i) => `<article class="history-version"><h4>${esc(v.source)}${v.accepted ? ' <span class="status-pill">Accepted</span>' : ""}</h4><p>${esc(v.format)}${v.classification === "spawned_subagent" ? " · Sub-agent" : ""}${v.parent_session_id ? ` · Parent ${esc(v.parent_session_id)}` : ""} · ${count(v.records)} records · ${v.recorded_tokens === null ? "Tokens unavailable" : `${count(v.recorded_tokens)} recorded tokens`}</p><p class="fine-print">${esc(shortDateTime(v.first_activity, zone))} – ${esc(shortDateTime(v.last_activity, zone))}</p>${v.locations.length ? `<ul class="history-locations">${v.locations.map(path => `<li>${esc(path)}</li>`).join("")}</ul>` : '<p class="fine-print">Retained indexed history; physical location unavailable on this computer.</p>'}<button class="button small ${v.accepted ? "" : "primary"}" data-history-select="${index}:${i}" ${g.reason_code === "claude_identity_unverified" ? "disabled" : ""}>${v.accepted ? "Keep accepted" : "Use this version"}</button></article>`).join("")}${g.has_selection ? `<button class="text-button" data-history-undo="${index}">Undo selection</button>` : ""}</section>`).join("")}<p class="history-error" role="alert" hidden></p>`;
}

type Dialog = (title: string, body: string, footer: string, bind: () => void) => void;

export class HistoryReview {
  private generation = 0;
  constructor(private dialog: Dialog,
    private action: (name: string, args: unknown) => Promise<boolean>,
    private toast: (message: string, error?: boolean) => void) {}

  async open(zone: string) {
    const generation = ++this.generation;
    try {
      const groups = await call<HistoryConflict[]>("history_conflicts");
      if (generation !== this.generation) return;
      this.dialog("Review conflicts", reviewBody(groups, zone), "", () => {
        const modal = document.querySelector<HTMLElement>('[role="dialog"]')!;
        const save = async (group: HistoryConflict, selected?: string) => {
          const buttons = modal.querySelectorAll<HTMLButtonElement>("[data-history-select],[data-history-undo]");
          buttons.forEach(b => b.disabled = true);
          modal.setAttribute("data-pending-edit", "true");
          try {
            const ok = await this.action("resolve_history_conflict", {
              id: group.id, revision: group.revision, selected, undo: selected === undefined,
            });
            if (modal.isConnected) {
              if (ok) await this.open(zone);
              else {
                const error = modal.querySelector<HTMLElement>(".history-error")!;
                error.textContent = "Selection was not saved. Close and reopen Review conflicts to load current evidence.";
                error.hidden = false;
              }
            }
          } finally {
            modal.removeAttribute("data-pending-edit");
            buttons.forEach(b => b.disabled = false);
          }
        };
        modal.querySelectorAll<HTMLButtonElement>("[data-history-select]").forEach(b => b.onclick = () => {
          const [g, v] = b.dataset.historySelect!.split(":").map(Number);
          void save(groups[g], groups[g].versions[v].id);
        });
        modal.querySelectorAll<HTMLButtonElement>("[data-history-undo]").forEach(b => b.onclick = () => {
          void save(groups[Number(b.dataset.historyUndo)]);
        });
      });
    } catch (error) { this.toast(error instanceof Error ? error.message : String(error), true); }
  }
}
