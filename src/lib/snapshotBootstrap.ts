import { parseSnapshot } from "./data.ts";
import type { RadarSnapshot } from "../types.ts";
import { parsePeriodOverviewBootstrap, type PeriodOverviewData } from "./periodMetrics.ts";

export type SnapshotBootstrap = {
  snapshot: RadarSnapshot;
  renderedAt: number;
  periodData?: PeriodOverviewData;
};

export function encodeSnapshotBootstrap(snapshot: RadarSnapshot, renderedAt: number, periodData?: PeriodOverviewData): string {
  if (!Number.isInteger(renderedAt) || renderedAt < 0) {
    throw new Error("The prerender timestamp is invalid.");
  }
  return encodeURIComponent(JSON.stringify({ snapshot, renderedAt, periodData }));
}

export function decodeSnapshotBootstrap(value: string): SnapshotBootstrap {
  const decoded: unknown = JSON.parse(decodeURIComponent(value));
  if (typeof decoded !== "object" || decoded === null || Array.isArray(decoded)) {
    throw new Error("The embedded radar snapshot is invalid.");
  }

  const candidate = decoded as Record<string, unknown>;
  if (!Number.isInteger(candidate.renderedAt) || (candidate.renderedAt as number) < 0) {
    throw new Error("The embedded radar render timestamp is invalid.");
  }

  return {
    snapshot: parseSnapshot(candidate.snapshot),
    renderedAt: candidate.renderedAt as number,
    periodData: candidate.periodData === undefined ? undefined : parsePeriodOverviewBootstrap(candidate.periodData),
  };
}
