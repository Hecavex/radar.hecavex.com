import type { RelatedObservations } from "./relatedObservations.ts";
import type { RadarHistory, RadarSnapshot } from "../types.ts";

export type RadarEvent = {
  id: string;
  signalId: string;
  type: "first-publication" | "reobservation" | "status-change" | "retraction";
  occurredAt: string;
  domain: string;
  brand: string;
  status: string;
  previousStatus: string | null;
  sources: string[];
  signalPath: string;
};

export type RadarEventArtifact = {
  schemaVersion: 1;
  dataset: "radar-events";
  generatedAt: string;
  window: { days: number; from: string; to: string };
  totalAvailable: number;
  truncated: boolean;
  events: RadarEvent[];
};

export type DailyTrendRow = {
  date: string;
  partialDay: boolean;
  collectorCoverage: {
    windowSeconds: number;
    scheduledSlots: number;
    recordedAttempts: number;
    healthyAttempts: number;
    recordedSchedulePercent: number | null;
    listeningCoveragePercent: number | null;
    scheduledListeningCeilingPercent: number | null;
    listeningSeconds: number;
    coverageBounds?: { methodVersion: 2; lowerSeconds: number; upperSeconds: number;
      precision: "exact" | "bounded" | "unknown"; unknownAttempts: number; reportedWorkerSeconds: number };
    outcomes: Record<string, number>;
  };
  discovery: {
    events: number;
    uniqueSignals: number;
    observations: number;
    reobservations: number;
    firstPublications: number;
    statusChanges: number;
    facetSampleSize: number;
    evidenceClassifiedSignals: number;
    byBrand: Record<string, number>;
    bySource: Record<string, number>;
    byEvidenceTier: Record<string, number>;
    byReason: Record<string, number>;
  };
};

export type DailyTrends = {
  schemaVersion: 1;
  dataset: "radar-daily-trends";
  generatedAt: string;
  retentionDays: number;
  from: string;
  to: string;
  semantics: string;
  facetSemantics: string;
  seriesSemantics: string;
  omittedZeroDays: number;
  collectorSchedule: { expectedIntervalSeconds: number; expectedListeningSeconds: number; derivedFrom: string };
  series: DailyTrendRow[];
  privacy: string;
};

export type QualityMetrics = {
  schemaVersion: 1;
  dataset: "radar-quality-metrics";
  generatedAt: string;
  semantics: string;
  reviewSample: {
    assessments: number;
    uniqueSignals: number;
    outcomes: Record<string, number>;
    byBrand: Record<string, number>;
    bySource: Record<string, number>;
    sourceLinkedAssessments: number;
    byEvidence: Record<string, number>;
    byDispositionReason: Record<string, number>;
    byDetectionReason: Record<string, number>;
  };
  reviewCoverage: { eligiblePublishedSignals: number; assessedSignals: number; percent: number | null; scope: string };
  reviewLatencyHours: { sampleSize: number; median: number | null; p90: number | null; minimum: number | null; maximum: number | null; scope: string };
  currentExclusions: { sampleSize: number; exact: number; subdomainPolicies: number; byReason: Record<string, number>; scope: string };
  precision: { available: boolean; sampleSize: number; estimatePercent: number | null; reason: string };
  privacy: string;
};

export type StaticPageData = {
  snapshot: RadarSnapshot;
  history: RadarHistory;
  historyTotal?: number;
  events: RadarEventArtifact;
  trends: DailyTrends;
  quality: QualityMetrics;
  related: RelatedObservations;
  renderedAt: number;
};

export type StaticPageKind = "changes" | "trends" | "associations" | "tools" | "dataset";

const identifierPattern = /^[a-f\d]{20}$/u;
const eventIdentifierPattern = /^[a-f\d]{32}$/u;
const timestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/u;
const eventTypes = new Set(["first-publication", "reobservation", "status-change", "retraction"]);
const eventStatuses = new Set(["active", "suspected", "offline", "mitigated", "unknown", "retracted"]);
const previousStatuses = new Set(["active", "suspected", "offline", "mitigated", "unknown"]);
const eventSources = new Set(["CertStream", "URLScan", "HECAVEX"]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactFields(value: Record<string, unknown>, fields: readonly string[]): boolean {
  const keys = Object.keys(value).sort();
  return keys.length === fields.length && keys.every((key, index) => key === [...fields].sort()[index]);
}

export function parseEventArtifact(
  value: unknown,
  availableSignalIds?: ReadonlySet<string>,
): RadarEventArtifact {
  const artifactFields = ["schemaVersion", "dataset", "generatedAt", "window", "totalAvailable", "truncated", "events"];
  if (!isObject(value) || !hasExactFields(value, artifactFields) || value.schemaVersion !== 1 || value.dataset !== "radar-events") {
    throw new Error("The Radar event artifact does not use the supported v1 contract.");
  }
  const window = value.window;
  if (
    !isObject(window) || !hasExactFields(window, ["days", "from", "to"]) || window.days !== 30 ||
    typeof window.from !== "string" || !timestampPattern.test(window.from) ||
    typeof window.to !== "string" || !timestampPattern.test(window.to) ||
    typeof value.generatedAt !== "string" || !timestampPattern.test(value.generatedAt) ||
    value.generatedAt !== window.to ||
    typeof value.totalAvailable !== "number" || !Number.isInteger(value.totalAvailable) || value.totalAvailable < 0 ||
    typeof value.truncated !== "boolean" || !Array.isArray(value.events) || value.events.length > 1_000 ||
    value.totalAvailable < value.events.length
  ) {
    throw new Error("The Radar event artifact has invalid window or count metadata.");
  }
  const eventFields = [
    "id", "type", "occurredAt", "signalId", "signalPath", "domain", "brand",
    "status", "previousStatus", "sources",
  ];
  const seen = new Set<string>();
  for (const event of value.events) {
    if (!isObject(event) || !hasExactFields(event, eventFields)) throw new Error("The Radar event artifact contains a malformed event.");
    if (
      typeof event.id !== "string" || !eventIdentifierPattern.test(event.id) || seen.has(event.id) ||
      typeof event.signalId !== "string" || !identifierPattern.test(event.signalId) ||
      typeof event.occurredAt !== "string" || !timestampPattern.test(event.occurredAt) ||
      typeof event.type !== "string" || !eventTypes.has(event.type) ||
      event.signalPath !== `/signals/${event.signalId}/` ||
      typeof event.domain !== "string" || event.domain.length === 0 || event.domain.length > 512 ||
      typeof event.brand !== "string" || event.brand.length === 0 || event.brand.length > 120 ||
      typeof event.status !== "string" || !eventStatuses.has(event.status) ||
      (event.previousStatus !== null && (typeof event.previousStatus !== "string" || !previousStatuses.has(event.previousStatus))) ||
      !Array.isArray(event.sources) || event.sources.length === 0 || event.sources.length > 3 ||
      new Set(event.sources).size !== event.sources.length ||
      event.sources.some((source) => typeof source !== "string" || !eventSources.has(source)) ||
      (availableSignalIds !== undefined && !availableSignalIds.has(event.signalId))
    ) {
      throw new Error("The Radar event artifact contains an invalid or unavailable signal route.");
    }
    seen.add(event.id);
  }
  return value as RadarEventArtifact;
}

export function encodeStaticPageBootstrap(data: StaticPageData): string {
  return encodeURIComponent(JSON.stringify(data));
}

export function decodeStaticPageBootstrap(value: string): StaticPageData {
  const parsed: unknown = JSON.parse(decodeURIComponent(value));
  if (!isObject(parsed) || !("snapshot" in parsed) || !("history" in parsed) || !("events" in parsed)) {
    throw new Error("The embedded Radar page data is invalid.");
  }
  parseEventArtifact(parsed.events);
  return parsed as StaticPageData;
}
