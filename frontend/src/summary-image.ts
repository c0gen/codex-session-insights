/** One-click copying, persistent preferences, and an explicit PNG save fallback. */
import type { Dashboard } from "./types";
import { esc, tip } from "./ui";
import { icon } from "./icons";
import { includeProjectNames, setIncludeProjectNames, initializeSummaryImagePreferences, summaryImageSnapshot } from "./summary-image-data";
import { renderSummaryImage } from "./summary-image-render";

const pngBase64 = (blob: Blob): Promise<string> => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(",")[1]);
  reader.onerror = () => reject(new Error("Could not read the summary image."));
  reader.readAsDataURL(blob);
});

export function summaryImageSettings(): string {
  return `<label class="toggle-label"><input id="summary-image-project-names" type="checkbox" ${includeProjectNames() ? "checked" : ""}> Include project names in copied images ${tip("Shows the selected project name. All-project summaries do not list project names.")}</label>`;
}

export function bindSummaryImageSettings(notify: (message: string, error?: boolean) => void): void {
  const input = document.querySelector<HTMLInputElement>("#summary-image-project-names");
  if (!input) return;
  input.disabled = true;
  void initializeSummaryImagePreferences().then(() => { input.checked = includeProjectNames(); input.disabled = false; });
  input.addEventListener("change", async event => {
    const input = event.target as HTMLInputElement;
    input.disabled = true;
    try { await setIncludeProjectNames(input.checked); }
    catch { input.checked = !input.checked; notify("Could not remember the image preference.", true); }
    finally { input.disabled = false; }
  });
}

export class SummaryImageCopy {
  private loading = true;
  private busy = false;
  private saving = false;
  private failed: { blob: Blob; filename: string; label: string } | null = null;
  private eligible = false;
  private preferencesReady = false;
  private nativeReady = false;

  constructor(private notify: (message: string, error?: boolean, duration?: number) => void) {}

  setLoading(value: boolean) { this.loading = value; this.update(); }

  mount(data: Dashboard, page: string) {
    if (!this.preferencesReady || (!!window.pywebview?.api && !this.nativeReady)) {
      this.preferencesReady = false;
      this.nativeReady = !!window.pywebview?.api;
      void initializeSummaryImagePreferences().then(() => { this.preferencesReady = true; this.update(); });
    }
    this.eligible = !data.readonly && !data.exporter && ["overview", "usage", "projects"].includes(page);
    const button = document.querySelector<HTMLButtonElement>("#copy-summary-image");
    if (button) {
      button.hidden = !this.eligible;
      button.onclick = () => { void this.copy(data); };
    }
    this.update();
  }

  private update() {
    const button = document.querySelector<HTMLButtonElement>("#copy-summary-image");
    if (button) {
      button.disabled = this.loading || this.busy || this.saving || !this.preferencesReady;
      button.setAttribute("aria-busy", String(this.busy));
      button.title = this.loading ? "Wait for the selected filters to load" : this.busy ? "Copying summary image…" : "Copy summary as an image";
    }
    const feedback = document.querySelector<HTMLElement>("#summary-image-feedback");
    if (!feedback) return;
    feedback.hidden = !this.failed || !this.eligible;
    if (!this.failed) { feedback.replaceChildren(); return; }
    feedback.innerHTML = `<span>Couldn’t copy the image. Save the generated summary instead.<small>${esc(this.failed.label)}</small></span><button id="save-summary-image" class="button small" ${this.saving || this.busy ? "disabled" : ""}>${icon("download", 16)}${this.saving ? "Saving…" : "Save PNG"}</button>`;
    feedback.querySelector<HTMLButtonElement>("#save-summary-image")!.onclick = () => { void this.save(); };
  }

  private async copy(data: Dashboard) {
    if (this.loading || this.busy || this.saving || !this.preferencesReady) return;
    this.busy = true; this.failed = null; this.update();
    let image: Promise<Blob> | null = null;
    let description: ReturnType<typeof summaryImageSnapshot> | null = null;
    try {
      description = summaryImageSnapshot(data);
      image = renderSummaryImage(description);
      if (window.pywebview?.api) {
        const response = await window.pywebview.api.call("copy_summary_image", { png_base64: await pngBase64(await image) }) as { status: string };
        if (response?.status !== "copied") throw new Error("Clipboard write failed.");
      } else {
        if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") throw new Error("Image clipboard unavailable.");
        // Start the browser write in the click handler; encoding can finish later.
        await navigator.clipboard.write([new ClipboardItem({ "image/png": image })]);
      }
      this.notify("Image copied", false, 3000);
    } catch {
      if (image && description) {
        try { this.failed = { blob: await image, filename: `codex-summary-${description.end}.png`, label: description.dateLabel }; }
        catch { /* A rendering failure has no image to save. */ }
      }
      this.notify(this.failed ? "Couldn’t copy the image. Use Save PNG to keep this summary." : "Couldn’t generate the image. Please try again.", true);
    } finally {
      this.busy = false; this.update();
    }
  }

  private async save() {
    if (!this.failed || this.saving || this.busy) return;
    const image = this.failed;
    this.saving = true; this.update();
    try {
      if (window.pywebview?.api) {
        const result = await window.pywebview.api.call("save_summary_image", { png_base64: await pngBase64(image.blob), filename: image.filename }) as { status: string };
        if (result?.status === "cancelled") return;
        if (result?.status !== "saved") throw new Error("Image save failed.");
        this.notify("Image saved", false, 3000);
      } else {
        const url = URL.createObjectURL(image.blob), anchor = document.createElement("a");
        anchor.href = url; anchor.download = image.filename; anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        this.notify("PNG download started", false, 3000);
      }
      this.failed = null;
    } catch { this.notify("Couldn’t save the image. Please try again.", true); }
    finally { this.saving = false; this.update(); }
  }
}
