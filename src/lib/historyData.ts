import {
  REASON_CODES,
  SIGNAL_STATUSES,
  type HistoryTransition,
  type RadarHistory,
  type ReasonCode,
  type SignalStatus,
} from "../types.ts";
import { readBoundedBytes, readBoundedJson } from "./boundedJson.ts";

const MAXIMUM_HISTORY_BYTES = 512 * 1024;

const ISO_UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
const SOURCES = ["CertStream", "URLScan", "HECAVEX"];
const TRANSITION_FIELDS = ["eventId", "observedAt", "previousStatus", "status", "sources", "reasonCodes"];
const SIGNAL_FIELDS = [
  "id",
  "domain",
  "brand",
  "firstSeen",
  "lastSeen",
  "observationCount",
  "sources",
  "latestStatus",
  "reasonCodes",
  "statusTransitions",
];
const HISTORY_FIELDS = [
  "schemaVersion",
  "dataset",
  "generatedAt",
  "detailRetentionDays",
  "summaryRetentionDays",
  "signals",
];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const hasExactKeys = (value: Record<string, unknown>, expected: string[]) =>
  Object.keys(value).length === expected.length && expected.every((key) => Object.hasOwn(value, key));

const isCanonicalDomain = (value: unknown): value is string => {
  if (typeof value !== "string" || value !== value.toLowerCase() || value.length > 257) return false;
  const labels = value.split("[.]");
  return (
    labels.length >= 2 &&
    labels.every(
      (label) =>
        label.length >= 1 &&
        label.length <= 63 &&
        /^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/u.test(label),
    )
  );
};

const stableSignalId = async (domain: string) => {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(domain));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 20);
};

const isTimestamp = (value: unknown): value is string => {
  if (typeof value !== "string" || !ISO_UTC_TIMESTAMP.test(value)) return false;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) && new Date(parsed).toISOString() === value;
};

const isSources = (value: unknown): value is string[] =>
  Array.isArray(value) &&
  value.length >= 1 &&
  value.length <= SOURCES.length &&
  value.every((source) => typeof source === "string" && SOURCES.includes(source)) &&
  new Set(value).size === value.length &&
  value.join("\0") === [...value].sort().join("\0");

const isReasonCodes = (value: unknown): value is ReasonCode[] =>
  Array.isArray(value) &&
  value.length >= 1 &&
  value.length <= 16 &&
  new Set(value).size === value.length &&
  value.every((reason) => typeof reason === "string" && REASON_CODES.includes(reason as ReasonCode));

const isStatus = (value: unknown): value is SignalStatus =>
  typeof value === "string" && SIGNAL_STATUSES.includes(value as SignalStatus);

const isTransition = (value: unknown): value is HistoryTransition =>
  isRecord(value) &&
  hasExactKeys(value, TRANSITION_FIELDS) &&
  typeof value.eventId === "string" &&
  /^[a-f\d]{32}$/.test(value.eventId) &&
  isTimestamp(value.observedAt) &&
  (value.previousStatus === null || isStatus(value.previousStatus)) &&
  isStatus(value.status) &&
  isSources(value.sources) &&
  isReasonCodes(value.reasonCodes);

const isHistorySignal = async (value: unknown): Promise<boolean> => {
  if (!isRecord(value)) return false;
  const firstSeen = isTimestamp(value.firstSeen) ? Date.parse(value.firstSeen) : null;
  const lastSeen = isTimestamp(value.lastSeen) ? Date.parse(value.lastSeen) : null;
  return (
    hasExactKeys(value, SIGNAL_FIELDS) &&
    typeof value.id === "string" &&
    /^[a-f\d]{20}$/.test(value.id) &&
    isCanonicalDomain(value.domain) &&
    value.id === await stableSignalId(value.domain) &&
    typeof value.brand === "string" &&
    value.brand.length > 0 &&
    value.brand.length <= 120 &&
    value.brand.trim() === value.brand &&
    firstSeen !== null &&
    lastSeen !== null &&
    firstSeen <= lastSeen &&
    typeof value.observationCount === "number" &&
    Number.isInteger(value.observationCount) &&
    value.observationCount >= 0 &&
    value.observationCount <= 2_147_483_647 &&
    isSources(value.sources) &&
    isStatus(value.latestStatus) &&
    isReasonCodes(value.reasonCodes) &&
    Array.isArray(value.statusTransitions) &&
    value.statusTransitions.length <= 16 &&
    value.statusTransitions.every(isTransition)
  );
};

type PartReader = (path: string, maximumBytes: number) => Promise<Uint8Array<ArrayBuffer>>;

export async function parseHistory(value: unknown, readPart?: PartReader): Promise<RadarHistory> {
  if (isRecord(value) && "partitionFormat" in value) {
    if (!readPart || value.schemaVersion !== 2 || value.partitionFormat !== "hecavex-history-partitions-v1" ||
      !hasExactKeys(value, [...HISTORY_FIELDS, "partitionFormat", "partitions", "signalCount"]) ||
      !Array.isArray(value.signals) || value.signals.length !== 0 ||
      !Number.isInteger(value.signalCount) || (value.signalCount as number) < 0 || (value.signalCount as number) > 25_000 ||
      !Array.isArray(value.partitions) || value.partitions.length < 1 || value.partitions.length > 512) {
      throw new Error("Invalid or unsupported history partition index.");
    }
    const rows: unknown[] = [];
    const seen = new Set<string>();
    for (const part of value.partitions) {
      if (!isRecord(part) || !hasExactKeys(part, ["path", "bytes", "sha256", "signals"]) ||
        typeof part.path !== "string" || !/^history-parts\/[a-f0-9]{64}\.json$/.test(part.path) ||
        !Number.isInteger(part.bytes) || (part.bytes as number) < 1 || (part.bytes as number) > 256 * 1024 ||
        !Number.isInteger(part.signals) || (part.signals as number) < 1 || (part.signals as number) > 25_000 ||
        seen.has(part.path)) throw new Error("Invalid history partition descriptor.");
      seen.add(part.path);
      const bytes = await readPart(part.path, 256 * 1024);
      const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
        .map((byte) => byte.toString(16).padStart(2, "0")).join("");
      if (bytes.byteLength !== part.bytes || digest !== part.sha256 || part.path !== `history-parts/${digest}.json`) {
        throw new Error("History partition integrity check failed.");
      }
      const chunk: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
      if (!Array.isArray(chunk) || chunk.length !== part.signals) throw new Error("History partition count mismatch.");
      rows.push(...chunk);
      if (rows.length > (value.signalCount as number)) throw new Error("History exceeds its declared total.");
    }
    if (rows.length !== value.signalCount) throw new Error("History is incomplete.");
    value = Object.fromEntries(Object.entries({ ...value, schemaVersion: 1, signals: rows })
      .filter(([key]) => !["partitionFormat", "partitions", "signalCount"].includes(key)));
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, HISTORY_FIELDS) ||
    value.schemaVersion !== 1 ||
    value.dataset !== "history" ||
    !isTimestamp(value.generatedAt) ||
    !Number.isInteger(value.detailRetentionDays) ||
    (value.detailRetentionDays as number) < 7 ||
    (value.detailRetentionDays as number) > 90 ||
    !Number.isInteger(value.summaryRetentionDays) ||
    (value.summaryRetentionDays as number) < 30 ||
    (value.summaryRetentionDays as number) > 3_650 ||
    (value.summaryRetentionDays as number) < (value.detailRetentionDays as number) ||
    !Array.isArray(value.signals) ||
    value.signals.length > 25_000
  ) {
    throw new Error("The radar history does not match schema version 1.");
  }
  const validity = await Promise.all(value.signals.map((signal) => isHistorySignal(signal)));
  const ids = value.signals.map((signal) => (isRecord(signal) ? signal.id : null));
  if (!validity.every(Boolean) || new Set(ids).size !== ids.length) {
    throw new Error("The radar history does not match schema version 1.");
  }
  return value as RadarHistory;
}

export async function loadHistory(signal?: AbortSignal): Promise<RadarHistory> {
  const response = await fetch("/data/history.json", {
    cache: "no-store",
    credentials: "omit",
    referrerPolicy: "no-referrer",
    signal,
  });
  if (!response.ok) throw new Error(`History request failed with HTTP ${response.status}.`);
  return parseHistory(await readBoundedJson(response, MAXIMUM_HISTORY_BYTES), async (path, maximum) => {
    const part = await fetch(`/data/${path}`, {
      cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer", signal,
    });
    if (!part.ok) throw new Error(`History partition request failed with HTTP ${part.status}.`);
    return readBoundedBytes(part, maximum);
  });
}
