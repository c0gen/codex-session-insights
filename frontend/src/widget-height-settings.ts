import type { DesktopPreferences } from "./types";

export const widgetHeightSettings = `<fieldset><legend>Widget height</legend>
  <label>Size<select data-desktop="widget_height_mode"><option value="auto">Automatic · fit to content</option><option value="custom">Custom height</option></select></label>
  <label id="widget-custom-height" hidden>Height (CSS pixels)<input data-desktop="widget_height_css_px" type="number" min="120" max="65536" step="1" value="360"></label>
  <p class="fine-print">Drag the top or bottom edge to resize. Custom height stays fixed when details change; extra content scrolls. Fit to content restores automatic sizing.</p></fieldset>`;

export function syncWidgetHeight(root: HTMLElement, preferences: DesktopPreferences) {
  const height = preferences.widget_height_css_px;
  root.querySelector<HTMLSelectElement>('[data-desktop="widget_height_mode"]')!.value = height == null ? "auto" : "custom";
  root.querySelector<HTMLElement>("#widget-custom-height")!.hidden = height == null;
  const input = root.querySelector<HTMLInputElement>('[data-desktop="widget_height_css_px"]')!;
  input.disabled = height == null;
  if (document.activeElement !== input) input.value = String(height == null ? 360 : Math.round(height));
}

export function widgetHeightChange(root: HTMLElement, target: HTMLInputElement | HTMLSelectElement): Partial<DesktopPreferences> | undefined {
  if (target.dataset.desktop === "widget_height_mode" && target.value === "auto") return { widget_height_css_px: null };
  const input = root.querySelector<HTMLInputElement>('[data-desktop="widget_height_css_px"]')!;
  const value = Number(input.value);
  if (!Number.isFinite(value) || value < 120 || value > 65536) {
    input.reportValidity();
    return undefined;
  }
  return { widget_height_css_px: value };
}
