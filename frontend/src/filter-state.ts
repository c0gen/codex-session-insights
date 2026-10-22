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

export type RequestIntent = "initial" | "apply" | "navigation" | "refresh" | "retry" | "background";
type Request = { id: number; intent: RequestIntent; filters: Filters; draft: Filters; scope: string };

/** Draft controls, submitted requests, and accepted results have independent lifetimes. */
export class FilterState {
  draft: Filters;
  private initial: Filters;
  private applied: Filters | null = null;
  private pending: Request | null = null;
  private failed: Request | null = null;
  private failures = new Map<string, { request: Request; message: string }>();
  private scope = "";
  private sequence = 0;
  interaction = 0;
  get error() { return this.failures.get(this.scope)?.message ?? null; }

  get loading() { return this.pending !== null; }
  get hasApplied() { return this.applied !== null; }

  constructor(initial: Filters) { this.initial = { ...initial }; this.draft = { ...initial }; }

  begin(intent: RequestIntent = "apply", scope = ""): Request | null {
    this.failed = intent === "retry" ? this.failures.get(this.scope)?.request ?? null : null;
    if (intent === "background" && (this.pending || this.error)) return null;
    const snapshot = intent === "apply" ? this.draft
      : intent === "retry" && this.failed ? this.failed.filters
      : this.pending?.filters ?? this.applied ?? this.initial;
    const filters = validateFilters(snapshot);
    this.scope = JSON.stringify([scope, filters]);
    if (intent !== "background" && intent !== "initial") this.interaction++;
    const request = { id: ++this.sequence, intent, filters, draft: { ...this.draft }, scope: this.scope };
    this.pending = request;
    // Keep a failed update visible until a replacement succeeds.
    return request;
  }

  current(request: Request) { return this.pending?.id === request.id; }

  finish(request: Request) {
    if (this.current(request)) this.pending = null;
  }

  fail(request: Request, message: string) {
    if (!this.current(request)) return;
    this.pending = null;
    this.failed = request;
    this.failures.set(request.scope, { request, message });
  }

  accept(request: Request, response: unknown = request.filters): Filters | null {
    if (!this.current(request)) return null;
    const applied = validateFilters(response);
    this.applied = applied;
    // Resolve normalized IDs only when the corresponding draft was submitted.
    for (const key of keys) {
      if (this.draft[key] === request.draft[key] && request.draft[key] === request.filters[key]) this.draft[key] = applied[key] ?? "";
    }
    this.pending = null;
    this.failed = null;
    this.failures.delete(request.scope);
    return { ...applied };
  }

  exportSnapshot(): Readonly<Filters> {
    if (!this.applied) throw new Error("Wait for the dashboard to load before exporting.");
    return Object.freeze({ ...this.applied });
  }
}
