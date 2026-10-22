import { esc } from "./ui";
import { icon } from "./icons";

const controls = 'button,input,select,textarea,a[href],[tabindex],[contenteditable="true"]';
const usable = (element: HTMLElement) => !element.matches(':disabled,[hidden],[aria-hidden="true"]') && element.tabIndex >= 0 && element.getClientRects().length > 0 && getComputedStyle(element).visibility !== "hidden";

function openerMatcher(opener: HTMLElement | null) {
  const id = opener?.id, page = opener?.getAttribute("data-page");
  const label = opener?.getAttribute("aria-label"), title = opener?.getAttribute("title");
  const account = opener?.closest("[data-account-id]")?.getAttribute("data-account-id");
  const action = opener?.getAttribute("data-account-action");
  return (element: HTMLElement) => {
    if (id) return element.id === id;
    if (account && action) return element.getAttribute("data-account-action") === action &&
      element.closest("[data-account-id]")?.getAttribute("data-account-id") === account;
    if (page) return element.getAttribute("data-page") === page;
    if (label) return element.getAttribute("aria-label") === label;
    return !!title && element.getAttribute("title") === title;
  };
}

/** Accessible modal lifecycle without requiring inert or native dialog support. */
export class ModalManager {
  private opener: HTMLElement | null = null;
  private openerMatch?: (element: HTMLElement) => boolean;
  private hidden = new Map<HTMLElement, string | null>();
  private observer?: MutationObserver;
  private active = false;
  constructor(private closed: () => void) {}
  private get root() { return document.getElementById("dialog-root")!; }
  private get modal() { return this.root.querySelector<HTMLElement>('[role="dialog"]'); }
  private targets() { return Array.from(this.modal?.querySelectorAll<HTMLElement>(controls) ?? []).filter(usable); }
  private focus = () => {
    if (!this.active || this.root.contains(document.activeElement)) return;
    (this.targets()[0] ?? this.modal)?.focus({ preventScroll: true });
  };
  private conceal = () => {
    for (const sibling of Array.from(document.body.children)) {
      if (!(sibling instanceof HTMLElement) || sibling === this.root || sibling.id === "toast" || ["SCRIPT", "STYLE"].includes(sibling.tagName)) continue;
      if (!this.hidden.has(sibling)) this.hidden.set(sibling, sibling.getAttribute("aria-hidden"));
      if (sibling.getAttribute("aria-hidden") !== "true") sibling.setAttribute("aria-hidden", "true");
    }
    this.focus();
  };
  private keydown = (event: KeyboardEvent) => {
    if (event.key === "Escape") { event.preventDefault(); this.close(); return; }
    if (event.key !== "Tab") return;
    const targets = this.targets(), index = targets.indexOf(document.activeElement as HTMLElement);
    event.preventDefault();
    if (!targets.length) this.modal?.focus();
    else targets[index < 0 ? (event.shiftKey ? targets.length - 1 : 0) : (index + (event.shiftKey ? -1 : 1) + targets.length) % targets.length].focus();
  };

  open(title: string, body: string, footer: string, bind: () => void) {
    const focusId = this.active && this.root.contains(document.activeElement) ? (document.activeElement as HTMLElement).id : "";
    if (!this.active) {
      this.opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      this.openerMatch = openerMatcher(this.opener);
      this.active = true;
      document.addEventListener("keydown", this.keydown, true);
      document.addEventListener("focusin", this.focus, true);
      this.observer = new MutationObserver(this.conceal);
      this.observer.observe(document.body, { childList: true, subtree: true });
    }
    this.root.innerHTML = `<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}" tabindex="-1"><div class="panel-heading"><h2>${esc(title)}</h2><button id="dialog-close" class="icon-button" aria-label="Close dialog">${icon("close")}</button></div><div class="modal-body">${body}</div><div class="modal-footer">${footer}</div></section></div>`;
    document.getElementById("dialog-close")!.onclick = () => this.close();
    bind();
    const targets = this.targets();
    const previous = focusId ? targets.find(element => element.id === focusId) : undefined;
    (previous ?? targets.find(element => element.matches("input,select,textarea")) ?? targets[0] ?? this.modal)?.focus({ preventScroll: true });
    this.conceal();
  }

  close() {
    if (!this.active) return;
    this.active = false;
    this.observer?.disconnect();
    document.removeEventListener("keydown", this.keydown, true);
    document.removeEventListener("focusin", this.focus, true);
    this.root.innerHTML = "";
    for (const [element, value] of this.hidden) {
      if (value === null) element.removeAttribute("aria-hidden"); else element.setAttribute("aria-hidden", value);
    }
    this.hidden.clear();
    const replacement = Array.from(document.querySelectorAll<HTMLElement>(controls)).find(element => this.openerMatch?.(element) && usable(element));
    const target = this.opener?.isConnected && usable(this.opener) ? this.opener : replacement ?? document.querySelector<HTMLElement>('.nav-item[aria-current="page"]');
    target?.focus({ preventScroll: true });
    this.opener = null;
    this.closed();
  }
}
