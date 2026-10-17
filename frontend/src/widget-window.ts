import { call } from "./api";

/** Native code owns screen coordinates; the DOM only supplies content size. */
export function bindWidgetWindow(
  root: HTMLElement,
  error: (message: string) => void,
) {
  let sent = "";
  let pending = false;
  let frame = 0;
  function syncViewport() { root.style.height = `${window.innerHeight}px`; }
  async function measure() {
    frame = 0;
    // WebView2's 100vh can exceed integer innerHeight at fractional display
    // scales. Keep the border inside the viewport and round intrinsic size up.
    syncViewport();
    if (!window.pywebview?.api || pending) return;
    const rect = root.getBoundingClientRect();
    const content = root.querySelector<HTMLElement>("#widget-content")!;
    const toolbar = root.querySelector<HTMLElement>("#widget-toolbar")!;
    const style = getComputedStyle(root);
    const chrome = [style.paddingTop, style.paddingBottom, style.borderTopWidth, style.borderBottomWidth].reduce((sum, value) => sum + parseFloat(value), 0);
    const layout = {
      width: Math.round(rect.width),
      height: Math.min(65536, Math.ceil(toolbar.getBoundingClientRect().height + content.getBoundingClientRect().height + chrome)),
      scale: devicePixelRatio,
      anchor: root.dataset.layoutAnchor || "top",
    };
    const key = JSON.stringify(layout);
    if (key === sent || !rect.width || !rect.height) return;
    pending = true;
    try {
      await call("widget_layout", layout);
      sent = key;
    } catch {
      error("Could not resize widget · retrying…");
    } finally {
      pending = false;
      // A render can change the content while the bridge request is in flight.
      if (sent === key) schedule();
    }
  }
  function schedule() {
    // WebView2 does not paint a hidden window. Its first measurement must not
    // wait for an animation frame, because that measurement makes it visible.
    if (document.hidden) {
      cancelAnimationFrame(frame);
      frame = 0;
      void measure();
    } else if (!frame) frame = requestAnimationFrame(measure);
  }
  async function command(command: "drag" | "menu" | "dismiss_menu" | "resize_top" | "resize_bottom", keyboard = false) {
    if (!window.pywebview?.api) return;
    try {
      await call("widget_command", { command, keyboard });
    } catch {
      error("Widget controls unavailable · retrying…");
    }
  }
  // Include the fractional viewport gutter, even while native menus pause paint.
  document.addEventListener("mousedown", event => {
    if (event.button !== 2) void command("dismiss_menu");
  }, true);
  root.addEventListener("mousedown", (event) => {
    const handle = (event.target as Element).closest<HTMLElement>("[data-resize]");
    if (event.button === 0 && handle) {
      event.preventDefault();
      void command(handle.dataset.resize === "top" ? "resize_top" : "resize_bottom");
      return;
    }
    if (
      event.button !== 0 ||
      (event.target as Element).closest("button, a, input, select, [data-tooltip]") ||
      !(event.target as Element).closest("#widget-toolbar, #totals, .widget-account-heading")
    )
      return;
    event.preventDefault();
    root.focus({ preventScroll: true });
    void command("drag");
  });
  root.querySelector("#widget-menu")?.addEventListener("click", () => { void command("menu", true); });
  document.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    void command("menu", event.clientX === 0 && event.clientY === 0);
  });
  root.addEventListener("keydown", (event) => {
    if (event.key === "Escape") void command("dismiss_menu");
    if (
      event.key === "ContextMenu" ||
      (event.shiftKey && event.key === "F10")
    ) {
      event.preventDefault();
      void command("menu", true);
    }
  });
  const observer = new ResizeObserver(schedule);
  observer.observe(root);
  observer.observe(root.querySelector("#widget-content")!);
  observer.observe(root.querySelector("#widget-toolbar")!);
  window.addEventListener("resize", () => { syncViewport(); schedule(); });
  window.addEventListener("pywebviewready", schedule);
  document.fonts.ready.then(schedule);
  function watchScale() {
    matchMedia(`(resolution: ${devicePixelRatio}dppx)`).addEventListener(
      "change",
      () => {
        syncViewport();
        schedule();
        watchScale();
      },
      { once: true },
    );
  }
  watchScale();
  syncViewport();
  schedule();
  return schedule;
}
