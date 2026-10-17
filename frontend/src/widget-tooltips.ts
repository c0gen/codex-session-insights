/** Tooltips also appear on keyboard focus and escape the scrolling content clip. */
export function bindWidgetTooltips(root: HTMLElement) {
  const tip = document.createElement("div");
  tip.className = "widget-tooltip";
  tip.id = "widget-tooltip";
  tip.role = "tooltip";
  tip.hidden = true;
  document.body.append(tip);
  let target: HTMLElement | null = null;
  function hide() {
    target?.removeAttribute("aria-describedby");
    target = null;
    tip.hidden = true;
  }
  function show(event: Event) {
    const next = (event.target as Element).closest<HTMLElement>("[data-tooltip]");
    if (next === target) return;
    hide();
    if (!next) return;
    target = next;
    target.setAttribute("aria-describedby", tip.id);
    tip.textContent = target.dataset.tooltip!;
    tip.hidden = false;
    const rect = target.getBoundingClientRect();
    tip.style.left = "6px";
    tip.style.top = `${Math.max(4, Math.min(rect.bottom + 4, innerHeight - tip.offsetHeight - 4))}px`;
  }
  root.addEventListener("mouseover", show);
  root.addEventListener("focusin", show);
  root.addEventListener("mouseleave", hide);
  root.addEventListener("focusout", hide);
  root.addEventListener("scroll", hide, true);
  root.addEventListener("keydown", event => { if (event.key === "Escape") hide(); });
  new MutationObserver(() => { if (target && !target.isConnected) hide(); }).observe(root, { childList: true, subtree: true });
}
