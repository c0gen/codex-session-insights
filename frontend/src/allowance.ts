import type { AllowanceWindow, ProviderAllowance, UsageLimits } from "./types";
import { call } from "./api";
import { esc } from "./ui";
import { burnRateMarkup, localBurnRatesMarkup } from "./burn-rate";
import { limitsRowMarkup } from "./limits-row";

/** One vocabulary for every provider's windows: "5-hour", "Weekly", "Daily", else the span itself. */
export function windowName(mins: number | null): string {
  if (mins === null) return "Window";
  if (mins === 300) return "5-hour";
  if (mins === 10080) return "Weekly";
  if (mins === 1440) return "Daily";
  if (mins % 1440 === 0) return `${mins / 1440}-day`;
  if (mins % 60 === 0) return `${mins / 60}-hour`;
  return `${mins}-minute`;
}

export function windowDuration(mins: number | null, _compact = false): string {
  return mins === null ? "Window unavailable" : `${windowName(mins)} limit`;
}

/** Whole percents, rounded down so a window never looks fuller than reported. */
export function remainingPercent(value: number): string {
  const clamped = Math.max(0, Math.min(100, value));
  return clamped > 0 && clamped < 1 ? "<1%" : `${Math.floor(clamped)}%`;
}

export function resetCountdown(reset: number | null, now = Date.now() / 1000, compact = false): string {
  if (reset === null) return "Reset unavailable";
  const remaining = Math.ceil((reset - now) / 60);
  if (remaining <= 0) return compact ? "Awaiting update" : "Reset due · awaiting update";
  const days = Math.floor(remaining / 1440), hours = Math.floor((remaining % 1440) / 60), minutes = remaining % 60;
  const value = days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m`;
  return `Resets in ${value}`;
}

function windowMarkup(window: AllowanceWindow, compact: boolean, identity: string[]) {
  const remaining = window.remaining_percent;
  const percent = remaining === null ? "Unavailable" : `${remainingPercent(remaining)} remaining`;
  const reset = resetCountdown(window.resets_at, undefined, compact);
  const title = `${windowDuration(window.window_duration_mins)}. ${percent}. ${reset}.${window.resets_at === null ? "" : ` Reset time: ${new Date(window.resets_at * 1000).toLocaleString()}.`}`;
  return `<div class="allowance-window" title="${esc(title)}"><div class="allowance-window-label"><span>${esc(windowDuration(window.window_duration_mins, compact))}</span><strong>${percent}</strong></div>${remaining === null ? "" : `<div class="allowance-track"><span style="width:${remaining}%"></span></div>`}<small>${esc(reset)}</small>${compact ? "" : burnRateMarkup(window.burn_rate, "allowance", [...identity, window.id])}</div>`;
}

export function allowanceMarkup(limits: UsageLimits, requestedBucket = "codex", compact = false, headingControl?: string, scope = "dashboard"): string {
  const bucket = limits.buckets.find(b => b.id === requestedBucket) || limits.buckets.find(b => b.id === "codex") || limits.buckets[0];
  const selector = limits.buckets.length > 1 ? `<label class="allowance-bucket-label">Bucket <select class="allowance-bucket" aria-label="Allowance bucket">${limits.buckets.map(b => `<option value="${esc(b.id)}" ${b.id === bucket?.id ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select></label>` : `<span class="allowance-bucket-name" title="Allowance bucket">Bucket · ${esc(bucket?.name || "Codex")}</span>`;
  const last = limits.last_success_at === null ? "No successful update" : `Updated ${new Date(limits.last_success_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  const detail = !limits.enabled ? "Live allowance fetching is disabled. Enable it in Settings." : limits.error || (limits.refreshing && !bucket ? "Connecting to Codex…" : bucket ? "This bucket returned no allowance windows." : "Allowance unavailable. Install Codex and sign in with ChatGPT, then refresh.");
  return `<div class="allowance-heading"><span>${headingControl ?? (compact ? "Usage" : "Account allowance")}${limits.stale ? ' <b class="allowance-stale">Stale</b>' : ""}</span>${selector}<button class="allowance-refresh" ${limits.refreshing || !limits.enabled ? "disabled" : ""} title="Refresh account allowance" aria-label="Refresh account allowance">${limits.refreshing ? "Updating…" : "Refresh"}</button></div>${compact ? "" : localBurnRatesMarkup(limits, [scope])}<div class="allowance-windows">${bucket?.windows.length ? bucket.windows.map(w => windowMarkup(w, compact, [scope, bucket.id])).join("") : `<p class="allowance-unavailable">${esc(detail)}</p>`}</div><div class="allowance-update" title="${limits.last_success_at === null ? "" : esc(new Date(limits.last_success_at * 1000).toLocaleString())}">${esc(last)}${!compact ? " · Signed-in account · independent of filters" : ""}</div>${(limits.error || !limits.enabled) && bucket?.windows.length ? `<p class="allowance-error" role="status">${esc(!limits.enabled ? detail : limits.error)}</p>` : ""}`;
}

export function bindAllowance(root: HTMLElement, select: (bucket: string) => void, refresh: () => void) {
  root.querySelector<HTMLSelectElement>(".allowance-bucket")?.addEventListener("change", event => select((event.target as HTMLSelectElement).value));
  root.querySelector<HTMLButtonElement>(".allowance-refresh")?.addEventListener("click", refresh);
}

/**
 * Owns the Overview limits row. It updates only the row, even while analytics
 * reloads are deferred by a form; full allowance cards live on Accounts.
 */
export class DashboardAllowance {
  private limits?: UsageLimits;
  private providers?: ProviderAllowance[];
  private selected?: string;
  private timezone = "UTC";
  private blocked = true;
  private busy = false;

  constructor(private openAccounts: () => void = () => {}) {}

  snapshot() { return this.limits; }

  mount(limits: UsageLimits | undefined, blocked: boolean, providers?: ProviderAllowance[], timezone = "UTC", selected?: string) {
    this.blocked = blocked;
    if (limits) this.limits = limits;
    this.providers = providers;
    this.timezone = timezone;
    this.selected = selected;
    this.render();
  }

  setProviders(providers?: ProviderAllowance[]) {
    this.providers = providers;
    this.render();
  }

  private render() {
    const root = document.querySelector<HTMLElement>("#limits-row");
    if (!root) return;
    const markup = limitsRowMarkup(this.blocked ? undefined : this.limits, this.providers, this.selected, this.timezone);
    root.hidden = !markup;
    if (root.dataset.markup === markup) return;
    const active = root.contains(document.activeElement) ? document.activeElement as HTMLElement : null;
    const focusedLimit = active?.dataset.limit;
    const focusedRate = active ? Array.from(root.querySelectorAll(".burn-rate")).indexOf(active) : -1;
    root.innerHTML = markup;
    root.dataset.markup = markup;
    root.querySelectorAll<HTMLButtonElement>("[data-limit]").forEach(button => button.addEventListener("click", this.openAccounts));
    if (focusedLimit) root.querySelector<HTMLElement>(`[data-limit="${CSS.escape(focusedLimit)}"]`)?.focus({ preventScroll: true });
    if (focusedRate >= 0) root.querySelectorAll<HTMLElement>(".burn-rate")[focusedRate]?.focus({ preventScroll: true });
  }

  async poll() {
    if (this.blocked || this.busy) return;
    this.busy = true;
    try { this.limits = await call<UsageLimits>("usage_limits"); this.render(); }
    finally { this.busy = false; }
  }
}
