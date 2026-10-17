import { call } from "./api";
import "./desktop-settings.css";
import type { DesktopPreferences, DesktopState, WidgetMetric, UsageLimits } from "./types";
import { esc } from "./ui";
import type { AccountsSnapshot } from "./account-types";
import { syncWidgetAccountSettings } from "./widget-account-settings";
import { syncWidgetHeight, widgetHeightChange, widgetHeightSettings } from "./widget-height-settings";

export const widgetMetrics: [WidgetMetric, string][] = [
  ["tokens", "Tokens"],
  ["cost", "Estimated API-equivalent cost"],
  ["lines", "Observed lines added / removed"],
  ["chats", "Main chats"],
];
let pending = false;
const snapshots = new WeakMap<HTMLElement, DesktopState>();
let accountSnapshot: AccountsSnapshot | undefined;
export function setDesktopAccounts(value: AccountsSnapshot | undefined) {
  accountSnapshot = value;
  const root = document.querySelector<HTMLElement>("#desktop-preferences");
  const state = root && snapshots.get(root);
  if (root && state && !pending) syncWidgetAccountSettings(root, state, value, next => snapshots.set(root, next));
}

export function syncDesktopSettings(state: DesktopState, limits?: UsageLimits) {
  const root = document.querySelector<HTMLElement>("#desktop-preferences");
  if (!root || !state.available || !state.preferences || pending) return;
  snapshots.set(root, state);
  root.closest(".modal")?.classList.add("desktop-modal");
  if (!root.children.length) {
    const toggle = (key: string, label: string) =>
      `<label class="desktop-toggle"><input type="checkbox" data-desktop="${key}"><span>${label}</span></label>`;
    root.innerHTML = `<h3>Widget &amp; tray</h3><p class="fine-print">Changes here apply immediately.</p>
      ${toggle("tray_enabled", "Keep running in the tray when the dashboard closes")}
      <p class="fine-print desktop-hint">Quit from the tray to stop the app.</p>
      ${toggle("widget_enabled", "Show floating usage widget")}
      <p class="fine-print desktop-hint">Covers all enabled sources in your display timezone. Drag the metrics or an account heading to move it; right-click or press Shift+F10 for its menu.</p>
      ${toggle("always_on_top", "Keep widget on top")}
      ${toggle("widget_details_expanded", "Show details above widget usage")}
      ${widgetHeightSettings}
      <fieldset><legend>Widget metrics · Today and All time</legend>${widgetMetrics.map(([key, label]) => toggle(key, label)).join("")}</fieldset>
      ${toggle("show_usage_remaining", "Show account usage beneath widget details")}
      <p class="fine-print desktop-hint">Refresh all updates the shown accounts and rereads local provider snapshots. Claude and Antigravity keep their last reading, labeled with its age.</p>
      <label id="widget-bucket-label" hidden>Widget usage bucket<select data-desktop="usage_remaining_bucket"></select></label>
      <p class="desktop-error" role="status"></p>`;
    root.addEventListener("change", async (event) => {
      const target = event.target as HTMLInputElement | HTMLSelectElement;
      const key = target.dataset.desktop;
      if (!key) return;
      const changes: Partial<DesktopPreferences> | undefined = key === "widget_height_mode" || key === "widget_height_css_px"
        ? widgetHeightChange(root, target) : widgetMetrics.some(
        ([metric]) => metric === key,
      )
        ? {
            metrics: widgetMetrics
              .filter(
                ([metric]) =>
                  root.querySelector<HTMLInputElement>(
                    `[data-desktop="${metric}"]`,
                  )!.checked,
              )
              .map(([metric]) => metric),
          }
        : key === "usage_remaining_bucket" ? { usage_remaining_bucket: target.value }
        : { [key]: (target as HTMLInputElement).checked };
      if (!changes) return;
      pending = true;
      root
        .querySelectorAll<HTMLInputElement | HTMLSelectElement>("input,select")
        .forEach((input) => (input.disabled = true));
      try {
        const updated = await call<DesktopState>("desktop_settings", changes);
        pending = false;
        syncDesktopSettings(updated);
      } catch (error) {
        pending = false;
        syncDesktopSettings(snapshots.get(root)!);
        root.querySelector(".desktop-error")!.textContent = String(error);
      } finally {
        root
          .querySelectorAll<HTMLInputElement | HTMLSelectElement>("input,select")
          .forEach((input) => (input.disabled = false));
        const current = snapshots.get(root)?.preferences;
        if (current) syncWidgetHeight(root, current);
      }
    });
  }
  for (const key of [
    "tray_enabled",
    "widget_enabled",
    "always_on_top",
    "show_usage_remaining",
    "widget_details_expanded",
  ] as const)
    root.querySelector<HTMLInputElement>(`[data-desktop="${key}"]`)!.checked =
      state.preferences[key] ?? (key === "widget_details_expanded");
  for (const [key] of widgetMetrics)
    root.querySelector<HTMLInputElement>(`[data-desktop="${key}"]`)!.checked =
      state.preferences.metrics.includes(key);
  const picker = root.querySelector<HTMLSelectElement>('[data-desktop="usage_remaining_bucket"]')!;
  if (limits) {
    picker.innerHTML = limits.buckets.map(bucket => `<option value="${esc(bucket.id)}">${esc(bucket.name)}</option>`).join("");
    root.querySelector<HTMLElement>("#widget-bucket-label")!.hidden = limits.buckets.length < 2;
  }
  picker.value = state.preferences.usage_remaining_bucket || "codex";
  syncWidgetHeight(root, state.preferences);
  root.querySelector(".desktop-error")!.textContent = state.error || "";
  syncWidgetAccountSettings(root, state, accountSnapshot, next => snapshots.set(root, next));
}

let handledSettingsRequest = 0;
let handledAccountRequest = 0;
export async function pollDesktopSettings(open: () => void, openAccount?: (id: string) => void) {
  const state = await call<DesktopState>("desktop_state");
  syncDesktopSettings(state);
  if ((state.settings_request || 0) > handledSettingsRequest) {
    handledSettingsRequest = state.settings_request!;
    open();
  }
  if (openAccount && state.account_request && state.account_request.sequence > handledAccountRequest) {
    handledAccountRequest = state.account_request.sequence;
    openAccount(state.account_request.account_id);
  }
}
