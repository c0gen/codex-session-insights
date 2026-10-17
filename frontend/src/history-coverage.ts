export function historyCoverage(states?: Record<string, number>) {
  return Object.entries(states || {}).filter(([state, n]) => state !== "Available" && n > 0)
    .map(([state, n]) => `${n} ${state.toLowerCase()} source${n === 1 ? "" : "s"}`).join(" · ");
}
