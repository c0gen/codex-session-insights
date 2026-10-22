/** Coalesce redraws and wait until the user has finished editing. */
export class DeferredReload {
  private pending = false;
  private running = false;
  private priority = false;

  constructor(private reload: (priority: boolean) => Promise<void>) {
    document.addEventListener("focusout", () => setTimeout(() => this.flush(), 0));
    document.addEventListener("input", (event) => {
      (event.target as Element).closest<HTMLElement>(".date-fields")?.setAttribute("data-unsaved", "true");
    });
  }

  editing() {
    return !!document.querySelector('[role="dialog"],.date-fields[data-unsaved],[data-pending-edit]') ||
      !!document.activeElement?.matches("input,textarea,select,[contenteditable=true]");
  }

  request(priority = false) {
    this.pending = true;
    this.priority ||= priority;
    void this.flush();
  }

  finishEditing() {
    document.querySelector(".date-fields")?.removeAttribute("data-unsaved");
    void this.flush();
  }

  async flush() {
    if (!this.pending || this.running || this.editing()) return;
    this.pending = false;
    const priority = this.priority;
    this.priority = false;
    this.running = true;
    try {
      await this.reload(priority);
    } finally {
      this.running = false;
      if (this.pending && !this.editing()) void this.flush();
    }
  }
}

export function captureView(root: HTMLElement) {
  const active = document.activeElement;
  const input = active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement ? active : null;
  return {
    x: window.scrollX, y: window.scrollY,
    focus: active && root.contains(active) ? active.id : "",
    selection: input && (input instanceof HTMLTextAreaElement || ["text", "search", "url", "tel", "password"].includes(input.type))
      ? [input.selectionStart, input.selectionEnd] : null,
    search: root.querySelector<HTMLInputElement>("#project-search")?.value,
    range: root.querySelector<HTMLSelectElement>("#filter-range")?.value,
    dates: Array.from(root.querySelectorAll<HTMLInputElement>(".date-fields input"), (field) => [field.id, field.value]),
    unsaved: !!root.querySelector(".date-fields[data-unsaved]"),
    scrolls: Array.from(root.querySelectorAll<HTMLElement>(".table-scroll"), element => [element.scrollLeft, element.scrollTop]),
    namedScrolls: Array.from(root.querySelectorAll<HTMLElement>("[data-preserve-scroll][id]"), element => ({ id: element.id, x: element.scrollLeft, y: element.scrollTop })),
  };
}

export function restoreView(root: HTMLElement, view: ReturnType<typeof captureView>) {
  const search = root.querySelector<HTMLInputElement>("#project-search");
  if (search && view.search !== undefined) {
    search.value = view.search;
    search.dispatchEvent(new Event("input", { bubbles: true }));
  }
  if (view.range === root.querySelector<HTMLSelectElement>("#filter-range")?.value) {
    for (const [id, value] of view.dates) {
      const field = document.getElementById(id) as HTMLInputElement | null;
      if (field) field.value = value;
    }
    if (view.unsaved) root.querySelector(".date-fields")?.setAttribute("data-unsaved", "true");
  }
  const focused = view.focus && document.getElementById(view.focus);
  if (focused) {
    focused.focus({ preventScroll: true });
    if (view.selection && (focused instanceof HTMLInputElement || focused instanceof HTMLTextAreaElement)) {
      focused.setSelectionRange(view.selection[0], view.selection[1]);
    }
  }
  window.scrollTo(view.x, view.y);
  root.querySelectorAll<HTMLElement>(".table-scroll").forEach((element, index) => {
    const scroll = view.scrolls[index];
    if (scroll) { element.scrollLeft = scroll[0]; element.scrollTop = scroll[1]; }
  });
  for (const scroll of view.namedScrolls) {
    const element = document.getElementById(scroll.id);
    if (element) { element.scrollLeft = scroll.x; element.scrollTop = scroll.y; }
  }
}
