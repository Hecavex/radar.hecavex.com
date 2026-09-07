import type { DailyTrendRow, DailyTrends } from "./staticPageBootstrap.ts";

// Use the same two-hour publication tolerance as the dashboard. Collection
// coverage remains anchored to the artifact cutoff, even when the page is old.
const publicationToleranceMs = 2 * 60 * 60 * 1000;

export function trendFreshness(trends: Pick<DailyTrends, "generatedAt">, now: number): "current" | "delayed" | "unknown" {
  const cutoff = Date.parse(trends.generatedAt);
  if (!Number.isFinite(cutoff) || !Number.isFinite(now) || cutoff > now + 60_000) return "unknown";
  return now - cutoff > publicationToleranceMs ? "delayed" : "current";
}

export function trendDayState(row: Pick<DailyTrendRow, "date" | "partialDay">, now: number): "complete" | "partial" | "incomplete" {
  if (!row.partialDay) return "complete";
  // "Partial" is about the saved observation window, not today's date. Never
  // silently convert its expected slots to a full day or imply later collection.
  const today = Number.isFinite(now) ? new Date(now).toISOString().slice(0, 10) : "";
  return row.date === today ? "partial" : "incomplete";
}
