/** Number formatting shared by the dashboard and the chart-free widget. */
export function compact(n: number, digits = 2) {
  return Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: digits,
  }).format(n || 0);
}
/** "Oct 14, 10:48 PM" in the display timezone; adds the year only outside the current one. */
export function shortDateTime(value: string | number, timezone?: string, now = new Date()) {
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  if (Number.isNaN(date.getTime())) return "—";
  let zone = timezone;
  try { if (zone) new Intl.DateTimeFormat("en-US", { timeZone: zone }); } catch { zone = undefined; }
  const year = (d: Date) => d.toLocaleDateString("en-US", { year: "numeric", timeZone: zone });
  return date.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: zone,
    ...(year(date) === year(now) ? {} : { year: "numeric" }),
  });
}
export function currency(n: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(n || 0);
}
