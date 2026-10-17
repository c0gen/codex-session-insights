import type { JobCompletion } from "./types";
import { esc } from "./ui";

/** Keep the latest completed export visible across live dashboard redraws. */
export class ExportFeedback {
  private warnings: string[] | null = null;

  observe(completion: JobCompletion) {
    const warnings = completion.result?.warnings;
    if (completion.state === "completed" && Array.isArray(warnings)) {
      this.warnings = warnings.filter((value): value is string => typeof value === "string");
    }
  }

  render() {
    if (this.warnings === null) return "";
    const warned = this.warnings.length > 0;
    return `<section class="panel export-notice ${warned ? "export-warning" : ""}" role="status" aria-live="polite"><strong>${warned ? "Export saved with warnings" : "Export saved"}</strong>${this.warnings.map(message => `<p>${esc(message)}</p>`).join("")}</section>`;
  }
}
