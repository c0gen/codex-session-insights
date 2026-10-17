import { esc } from "./ui";
import type { ProviderAllowance, ProviderSetup } from "./types";
import { accountDate } from "./account-credits";
import { asOfText, emptyGuidance, limitState, limitWindowMarkup, providerHeadings, readingAged, sourceText, validBucket } from "./claude-limits";

const names: Record<string, string> = { claude_code: "Claude Code", antigravity: "Antigravity", antigravity_cli: "Antigravity CLI" };

function providerCard(profile: ProviderAllowance, timezone: string, now: number) {
  const buckets = Array.isArray(profile.buckets) ? profile.buckets.filter(validBucket) : [];
  const check = profile.check?.enabled ? profile.check : undefined;
  const aged = readingAged(profile, now);
  const stale = buckets.some(b => limitState(b, now, aged) !== "fresh");
  const refresh = check ? `<button class="allowance-refresh" data-provider-usage-refresh="${esc(profile.provider)}" data-claude-usage-refresh ${check.refreshing ? "disabled" : ""} title="Run ${esc(names[profile.provider] || profile.provider)} /usage now" aria-label="Refresh ${esc(providerHeadings[profile.provider] || profile.provider)}">${check.refreshing ? "Checking…" : "Refresh"}</button>` : "";
  const received = typeof profile.received_at === "number" && Number.isFinite(profile.received_at) ? profile.received_at : null;
  const footer = received === null || !buckets.length ? "" : `<div class="allowance-update" title="${esc(`${accountDate(received, timezone)} · ${timezone}`)}">${esc(`${asOfText(received, timezone, now)} · ${sourceText(profile)}`)}${profile.provider === "claude_code" ? " · Plan-wide · independent of filters" : ""}</div>`;
  return `<article class="allowance-strip provider-allowance" data-provider="${esc(profile.provider)}" aria-label="${esc(providerHeadings[profile.provider] || profile.provider)}">
    <div class="allowance-heading"><span>${esc(providerHeadings[profile.provider] || names[profile.provider] || profile.provider)}${stale ? ' <b class="allowance-stale">Stale</b>' : ""}</span>${refresh}</div>
    ${buckets.length ? `<div class="allowance-windows">${buckets.map(b => limitWindowMarkup(b, timezone, now, false, "", aged)).join("")}</div>` : `<p class="allowance-unavailable">${esc(emptyGuidance(profile))}</p>`}
    ${footer}${check?.error ? `<p class="allowance-error" role="status">${esc(check.error)}</p>` : ""}</article>`;
}

export function renderProviderAllowances(profiles?: ProviderAllowance[], selected?: string, timezone = "UTC", now = Date.now() / 1000) {
  if (!profiles?.length) return "";
  const shown = profiles.filter(p => p && (!selected || p.provider === selected));
  return shown.length ? `<section class="provider-allowances" aria-label="Local provider allowances">${shown.map(p => providerCard(p, timezone, now)).join("")}</section>` : "";
}

/** One delegated listener survives the cards' live re-renders. */
export function bindProviderAllowances(root: HTMLElement, refresh: (provider: string) => Promise<unknown>) {
  root.addEventListener("click", async event => {
    const button = (event.target as Element).closest<HTMLButtonElement>("[data-provider-usage-refresh]");
    if (!button || button.disabled) return;
    button.disabled = true;
    button.textContent = "Checking…";
    try { await refresh(button.dataset.providerUsageRefresh || "claude_code"); } catch { /* The card shows the check's error. */ }
  });
}

const setupStatus: Record<string, string> = { installed: "Installed", not_installed: "Not installed", disabled: "Disabled", unavailable: "Unavailable" };

/** Offer only the operations that change something in the current state. */
function setupActions(s: ProviderSetup) {
  const action = (operation: string, label: string) =>
    `<button class="button small" data-provider-target="${esc(s.target)}" data-provider-operation="${operation}">${label}</button>`;
  const installed = s.status === "installed";
  return `${action("preview", "Preview configuration")}${!installed ? action("install", "Install")
    : s.upgrade_available ? action("install", "Update") : ""}${installed ? action("disable", "Disable") : ""}${s.status !== "not_installed" ? action("uninstall", "Uninstall") : ""}`;
}

export function providerSetupCards(states?: ProviderSetup[]) {
  if (!states?.length) return "";
  return `<section class="panel provider-setup"><h2>Local provider bridges</h2><p>Opt in to receive allowances and Antigravity activity. Sign-in stays in the official apps. Refresh rereads local files. Local profile identity is unverified. Automatic CLI quota checks are available in Settings.</p><div class="provider-setup-rows">${states.map(s => `<article><strong>${esc(names[s.target] || s.target)}</strong><span class="status-pill ${s.status === "installed" ? "" : "muted"}">${esc(setupStatus[s.status] || s.status)}</span><div class="provider-setup-actions">${s.error ? `<p>${esc(s.error)}</p>` : setupActions(s)}</div></article>`).join("")}</div><p>Existing hooks and status-line output are preserved. Uninstall restores only settings still owned by this integration.</p></section>`;
}

export function bindProviderSetup(root: HTMLElement, action: (target: string, operation: string) => Promise<unknown>) {
  root.querySelectorAll<HTMLButtonElement>("[data-provider-target]").forEach(button => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try { await action(button.dataset.providerTarget!, button.dataset.providerOperation!); }
      catch (error) { button.title = String(error); }
      finally { button.disabled = false; }
    });
  });
}
