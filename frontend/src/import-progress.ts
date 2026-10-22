import { count } from "./ui";

/** Import diagnostics are optional; ordinary scans keep their existing notice. */
export function incrementalCounts(value: Record<string, unknown> | null | undefined) {
  const names = ["checked", "reused", "added", "changed", "removed", "recalculated"];
  return names.filter(name => typeof value?.[name] === "number")
    .map(name => `${count(value![name] as number)} ${name}`).join(" · ");
}
