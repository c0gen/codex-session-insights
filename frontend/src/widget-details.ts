import { call } from "./api";
import type { DesktopState } from "./types";

export const detailsToggle = `<button class="widget-details-toggle" aria-controls="widget-details" aria-expanded="true" title="Hide details" aria-label="Hide details"><span>Details</span><svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true"><path d="m3 7 3-3 3 3" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button>`;

/** Keep the disclosure control usable while account rows refresh underneath it. */
export function bindWidgetDetails(root: HTMLElement, getState: () => DesktopState,
  saved: (state: DesktopState) => void, measure: () => void, error: (message: string) => void) {
  const details = root.querySelector<HTMLElement>("#widget-details")!;
  let pending: boolean | undefined;
  let initialized = false;

  function sync() {
    const hasUsage = root.hasAttribute("data-accounts");
    const expanded = !hasUsage || (pending ?? getState().preferences?.widget_details_expanded ?? true);
    root.dataset.layoutAnchor = hasUsage && getState().preferences?.widget_height_css_px == null ? "bottom" : "top";
    root.toggleAttribute("data-collapsed", !expanded);
    details.inert = !expanded;
    details.setAttribute("aria-hidden", String(!expanded));
    root.querySelectorAll<HTMLButtonElement>(".widget-details-toggle").forEach(button => {
      button.hidden = !hasUsage;
      button.setAttribute("aria-expanded", String(expanded));
      button.title = expanded ? "Hide details" : "Show details";
      button.setAttribute("aria-label", button.title);
      button.disabled = pending !== undefined;
    });
    if (!initialized) {
      // Restore the saved state immediately; animate subsequent user changes.
      void details.offsetHeight;
      root.setAttribute("data-details-ready", "");
      initialized = true;
    }
    measure();
  }

  root.addEventListener("click", async event => {
    if (!(event.target as Element).closest(".widget-details-toggle") || pending !== undefined) return;
    pending = root.hasAttribute("data-collapsed");
    sync();
    try {
      const state = await call<DesktopState>("desktop_settings", { widget_details_expanded: pending });
      saved(state);
    } catch {
      error("Could not save detail visibility · try again");
    } finally {
      pending = undefined;
      sync();
    }
  });
  return sync;
}
