import type { Filters } from "./types";

export const defaultFilters = (): Filters => ({ range: "all", project_id: "", model: "", source_id: "", provider: "", start: "", end: "" });
const keys = Object.keys(defaultFilters()) as (keyof Filters)[];
const ranges = new Set(["all", "today", "7", "30", "90", "custom"]);

function validDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function validateFilters(value: unknown): Filters {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid saved filters.");
  const filters = { ...value, provider: (value as Filters).provider ?? "" } as Filters;
  if (!["", "codex", "claude_code", "antigravity"].includes(filters.provider || "")) throw new Error("Invalid provider filter.");
  if (keys.some(key => typeof filters[key] !== "string") || !ranges.has(filters.range)) throw new Error("Invalid saved filters.");
  if (filters.range === "custom") {
    if (!validDate(filters.start) || !validDate(filters.end)) throw new Error("Choose valid From and To dates before applying.");
    if (filters.start > filters.end) throw new Error("From must be on or before To.");
  }
  // Dates outside a custom range are drafts, not applied query parameters.
  return { ...defaultFilters(), ...Object.fromEntries(keys.map(key => [key, filters[key]])),
    start: filters.range === "custom" ? filters.start : "", end: filters.range === "custom" ? filters.end : "" };
}

export function restoreFilters(raw: string | null) {
  try {
    return { filters: raw === null ? defaultFilters() : validateFilters(JSON.parse(raw)), recovered: false };
  } catch {
    return { filters: defaultFilters(), recovered: true };
  }
}

type Request = { id: number; filters: Filters; draft: Filters };

/** Draft controls, in-flight request, and displayed response have separate lifetimes. */
export class FilterState {
  draft: Filters;
  private applied: Filters | null = null;
  private pending: Request | null = null;
  private sequence = 0;
  error: string | null = null;

  get loading() { return this.pending !== null; }

  constructor(initial: Filters) { this.draft = { ...initial }; }

  begin(automatic = false): Request | null {
    if (automatic && (this.pending || this.error)) return null;
    const filters = validateFilters(automatic && this.applied ? this.applied : this.draft);
    const request = { id: ++this.sequence, filters, draft: { ...this.draft } };
    this.pending = request;
    this.error = null;
    return request;
  }

  current(request: Request) { return this.pending?.id === request.id; }

  finish(request: Request) {
    if (this.current(request)) this.pending = null;
  }

  fail(request: Request, message: string) {
    if (!this.current(request)) return;
    this.pending = null;
    this.error = message;
  }

  accept(request: Request, response: unknown = request.filters): Filters | null {
    if (!this.current(request)) return null;
    const applied = validateFilters(response);
    this.applied = applied;
    // Resolve server-normalized IDs, but never replace edits made during a request.
    for (const key of keys) {
      if (this.draft[key] === request.draft[key] && request.draft[key] === request.filters[key]) this.draft[key] = applied[key] ?? "";
    }
    this.pending = null;
    return { ...applied };
  }

  exportSnapshot(): Readonly<Filters> {
    if (!this.applied) throw new Error("Wait for the dashboard to load before exporting.");
    return Object.freeze({ ...this.applied });
  }
}
