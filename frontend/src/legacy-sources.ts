import { count, esc } from "./ui";
import type { Source } from "./types";

export interface LegacyPreview {
  status?: string;
  selection_token?: string;
  release_gate: boolean;
  archive_count: number;
  index_matches?: number;
  profile_unlock: string;
  decoder: string;
  counts: Record<string, number>;
  diagnostic?: string;
  coverage?: Record<string, { available: number | null; observations: number | null }>;
}

export function legacyPreview(result: LegacyPreview) {
  const fields = result.coverage || {};
  return `<p>${count(result.archive_count)} archives · ${count(result.index_matches || 0)} index matches · profile ${esc(result.profile_unlock)}</p><p>${Object.entries(result.counts).map(([state, n]) => `${count(n)} ${esc(state)}`).join(" · ")}</p><p>${Object.entries(fields).map(([metric, value]) => `${esc(metric.replaceAll("_", " "))}: ${value.available === null ? "unavailable" : `${count(value.available)} / ${count(value.observations || 0)}`}`).join("<br>")}</p>${result.diagnostic ? `<p>${esc(result.diagnostic)}</p>` : ""}<p>Recognized format: ${esc(result.decoder)}</p><p>Only recorded usage and successful edits with recorded sizes enter the dashboard. Missing counters and prices remain unavailable.</p>`;
}

export function legacySourceDetails(source: Source) {
  if (source.format !== "antigravity_legacy") return "";
  // Current sources already carry the retirement notice; anonymized and older
  // reports still need the fallback when their diagnostic detail is absent.
  if (source.status === "Collection disabled" && source.detail) return "";
  return `<p class="fine-print">Encrypted archive collection is disabled. Previously indexed usage remains included. Use public transcripts and official hooks for new activity.</p>`;
}
