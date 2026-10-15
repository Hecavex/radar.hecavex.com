export type SourceTimeProvenance = "provider-observation-time" | "collector-time-fallback" | "legacy-normalized-unknown";

export interface ObservedHostnameRecord {
  id: string;
  domain: string;
  domainGroup: string;
  brand: string;
  firstSeen: string;
  lastSeen: string;
  firstRecordedAt: string | null;
  firstPublishedAt: string | null;
  observedDays: string[];
  observedDayLastSeen: Record<string, string>;
  sources: string[];
  sourceTimeProvenances?: SourceTimeProvenance[];
  match: { score: number | null; reasonCodes: string[]; policyVersion: string };
  assessment: { verdict: "malicious" | "suspicious" | "benign" | "inconclusive"; assessedAt: string; evidenceReferences: string[]; decisionId: string; analystConfidence: number | null } | null;
  recordAvailable: boolean;
}

export interface PeriodWindow {
  key: string;
  startInclusive: string | null;
  endExclusive: string;
  uniqueHostnames: number;
  domainGroups: number;
  candidateDays: number;
  firstRecordedHostnames: number | null;
  firstPublishedHostnames: number | null;
  exactWithinRecordedData: true;
  completeCollection: boolean;
}

/** Membership uses actual observed days, never an invented first-to-last interval. */
export function selectPeriodRecords(records: ObservedHostnameRecord[], window: Pick<PeriodWindow, "startInclusive" | "endExclusive">): ObservedHostnameRecord[] {
  const start = window.startInclusive ?? "";
  return records.filter((record) => record.observedDays.some((day) => {
    const last = record.observedDayLastSeen[day];
    return last >= start && last < window.endExclusive;
  }));
}

export function periodTotals(records: ObservedHostnameRecord[], window: Pick<PeriodWindow, "startInclusive" | "endExclusive">) {
  const selected = selectPeriodRecords(records, window);
  return {
    uniqueHostnames: selected.length,
    domainGroups: new Set(selected.map((record) => record.domainGroup)).size,
    candidateDays: selected.reduce((sum, record) => sum + record.observedDays.filter((day) =>
      record.observedDayLastSeen[day] >= (window.startInclusive ?? "") && record.observedDayLastSeen[day] < window.endExclusive).length, 0),
  };
}
import { readBoundedBytes } from "./boundedJson.ts";
import { safeCsvCell } from "./export.ts";

const MAXIMUM_BYTES = 256 * 1024;
const MAXIMUM_RECORDS = 25_000;
const MAXIMUM_PARTS = 512;
const SHA256 = /^[a-f\d]{64}$/;
const HOSTNAME = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\[\.\])+(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$/;
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

export interface PeriodGrouping {
  method: "private-psl-registrable-domain";
  version: "tldextract-5.4.0";
  privateSuffixes: true;
  pslSha256: string;
}
export interface PeriodCoverage {
  availableFrom: string | null;
  recordedFrom: string | null;
  publicationRecordedFrom: string | null;
  recoveredFrom: string | null;
  recoveredThrough: string | null;
  recoveredDays: string[];
  missingDays: string[];
  historyComplete: boolean;
  collectionComplete: boolean;
  historicalRecordingTimesComplete: boolean;
  historicalPublicationTimesComplete: boolean;
  basis: "recorded-and-recovered-observation-facts";
  partialCurrentDay: boolean;
}
export interface PeriodPolicyVersions { identity: string; matching: string; review: string; metrics: string; store: string }
interface PeriodMetadata {
  schemaVersion: 1;
  generatedAt: string;
  asOf: string;
  grouping: PeriodGrouping;
  coverage: PeriodCoverage;
  policyVersions: PeriodPolicyVersions;
}
export interface ObservedHostnameIndex extends PeriodMetadata {
  dataset: "radar-observed-hostnames";
  recordCount: number;
  partitions: { path: string; bytes: number; sha256: string; records: number }[];
}
export interface PeriodMetricsArtifact extends PeriodMetadata {
  dataset: "radar-period-metrics";
  timeBasis: "source-observation-time" | "source-observation-or-explicit-collector-fallback";
  identityUnit: "canonical-hostname";
  population: "public-eligible-recorded-hostnames";
  hostnamesSha256: string;
  windows: PeriodWindow[];
}
export interface PeriodOverviewData {
  metrics: PeriodMetricsArtifact;
  index: ObservedHostnameIndex;
  records: ObservedHostnameRecord[];
  complete: boolean;
}


const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const shape = (value: unknown, fields: string[], optionalFields: string[] = []): value is Record<string, unknown> =>
  object(value) && fields.every((key) => Object.hasOwn(value, key)) && Object.keys(value).every((key) => fields.includes(key) || optionalFields.includes(key));
const text = (value: unknown, max = 160): value is string => typeof value === "string" && value.trim().length > 0 && [...value].length <= max && !/[\p{Cc}\p{Cf}]/u.test(value);
const integer = (value: unknown, max = MAXIMUM_RECORDS): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= max;
const timestamp = (value: unknown): value is string => typeof value === "string" && UTC.test(value) && !value.startsWith("0000-") && Number.isFinite(Date.parse(value)) && new Date(value).toISOString() === value;
const date = (value: unknown): value is string => typeof value === "string" && DAY.test(value) && timestamp(`${value}T00:00:00.000Z`);
const nullableTimestamp = (value: unknown): value is string | null => value === null || timestamp(value);
const nullableDate = (value: unknown): value is string | null => value === null || date(value);
const sortedUnique = (value: unknown, item: (value: unknown) => boolean, max = 36_600): value is string[] =>
  Array.isArray(value) && value.length <= max && value.every((entry, index) => item(entry) && (index === 0 || value[index - 1] < entry));
const unique = (value: unknown, item: (value: unknown) => boolean, max: number): value is string[] => Array.isArray(value) && value.length <= max && new Set(value).size === value.length && value.every(item);
const hostname = (value: unknown): value is string => typeof value === "string" && value.replaceAll("[.]", ".").length <= 253 && HOSTNAME.test(value);

function metadata(value: Record<string, unknown>): boolean {
  const { grouping, coverage, policyVersions } = value;
  return value.schemaVersion === 1 && timestamp(value.asOf) && value.generatedAt === value.asOf &&
    shape(grouping, ["method", "version", "privateSuffixes", "pslSha256"]) &&
    grouping.method === "private-psl-registrable-domain" && grouping.version === "tldextract-5.4.0" && grouping.privateSuffixes === true && typeof grouping.pslSha256 === "string" && SHA256.test(grouping.pslSha256) &&
    shape(policyVersions, ["identity", "matching", "review", "metrics", "store"]) && Object.values(policyVersions).every((entry) => text(entry, 160)) &&
    shape(coverage, ["availableFrom", "recordedFrom", "publicationRecordedFrom", "recoveredFrom", "recoveredThrough", "recoveredDays", "missingDays", "historyComplete", "collectionComplete", "historicalRecordingTimesComplete", "historicalPublicationTimesComplete", "basis", "partialCurrentDay"]) &&
    nullableTimestamp(coverage.availableFrom) && nullableTimestamp(coverage.recordedFrom) && nullableTimestamp(coverage.publicationRecordedFrom) && nullableDate(coverage.recoveredFrom) && nullableDate(coverage.recoveredThrough) &&
    sortedUnique(coverage.recoveredDays, date) && sortedUnique(coverage.missingDays, date) &&
    [coverage.historyComplete, coverage.collectionComplete, coverage.historicalRecordingTimesComplete, coverage.historicalPublicationTimesComplete, coverage.partialCurrentDay].every((entry) => typeof entry === "boolean") && coverage.basis === "recorded-and-recovered-observation-facts" &&
    (coverage.availableFrom === null || coverage.availableFrom <= value.asOf) && (coverage.recordedFrom === null || coverage.recordedFrom <= value.asOf) && (coverage.publicationRecordedFrom === null || coverage.publicationRecordedFrom <= value.asOf);
}

const METADATA_FIELDS = ["schemaVersion", "dataset", "generatedAt", "asOf", "grouping", "coverage", "policyVersions"];
export function parseObservedHostnameIndex(value: unknown): ObservedHostnameIndex {
  if (!shape(value, [...METADATA_FIELDS, "recordCount", "partitions"]) || !metadata(value) || value.dataset !== "radar-observed-hostnames" || !integer(value.recordCount) ||
    !Array.isArray(value.partitions) || value.partitions.length > MAXIMUM_PARTS || !value.partitions.every((part) =>
      shape(part, ["path", "bytes", "sha256", "records"]) && typeof part.sha256 === "string" && SHA256.test(part.sha256) &&
      part.path === `/data/observed-hostnames-parts/${part.sha256}.json` && integer(part.bytes, MAXIMUM_BYTES) && part.bytes > 1 && integer(part.records) && part.records > 0) ||
    new Set(value.partitions.map((part) => part.path)).size !== value.partitions.length || value.partitions.reduce((sum, part) => sum + part.records, 0) !== value.recordCount) {
    throw new Error("The observed hostname index does not match its supported schema.");
  }
  return value as unknown as ObservedHostnameIndex;
}

function windowShape(value: unknown, asOf: string, coverage: PeriodCoverage): boolean {
  if (!shape(value, ["key", "startInclusive", "endExclusive", "uniqueHostnames", "domainGroups", "candidateDays", "firstRecordedHostnames", "firstPublishedHostnames", "exactWithinRecordedData", "completeCollection"]) ||
    typeof value.key !== "string" || !/^(?:30d|90d|365d|all|month:\d{4}-\d{2}|year:\d{4})$/.test(value.key) || !nullableTimestamp(value.startInclusive) || !timestamp(value.endExclusive) ||
    (value.startInclusive !== null && value.startInclusive >= value.endExclusive) || !integer(value.uniqueHostnames) || !integer(value.domainGroups) || value.domainGroups > value.uniqueHostnames || !integer(value.candidateDays, 1_000_000_000) || value.candidateDays < value.uniqueHostnames ||
    !(value.firstRecordedHostnames === null || integer(value.firstRecordedHostnames)) || !(value.firstPublishedHostnames === null || integer(value.firstPublishedHostnames)) ||
    (clockComplete(coverage, "recorded", value.startInclusive) !== (value.firstRecordedHostnames !== null)) || (clockComplete(coverage, "published", value.startInclusive) !== (value.firstPublishedHostnames !== null)) ||
    value.exactWithinRecordedData !== true || value.completeCollection !== coverage.collectionComplete) return false;
  if (value.key === "all") return value.startInclusive === null && value.endExclusive === new Date(Date.parse(asOf) + 1).toISOString();
  if (/^\d+d$/.test(value.key)) return value.startInclusive === new Date(Date.parse(asOf) - Number(value.key.slice(0, -1)) * 86_400_000).toISOString() && value.endExclusive === new Date(Date.parse(asOf) + 1).toISOString();
  const [kind, period] = value.key.split(":");
  const start = `${period}${kind === "year" ? "-01" : ""}-01T00:00:00.000Z`;
  if (!timestamp(start) || value.startInclusive !== start || start > asOf) return false;
  const end = new Date(start);
  if (kind === "year") end.setUTCFullYear(end.getUTCFullYear() + 1);
  else end.setUTCMonth(end.getUTCMonth() + 1);
  return value.endExclusive === end.toISOString();
}

function clockComplete(coverage: PeriodCoverage, clock: "recorded" | "published", start: string | null): boolean {
  const complete = clock === "recorded" ? coverage.historicalRecordingTimesComplete : coverage.historicalPublicationTimesComplete;
  const activation = clock === "recorded" ? coverage.recordedFrom : coverage.publicationRecordedFrom;
  return complete || (start !== null && activation !== null && start >= activation);
}

export function parsePeriodMetrics(value: unknown): PeriodMetricsArtifact {
  if (!shape(value, [...METADATA_FIELDS, "timeBasis", "identityUnit", "population", "hostnamesSha256", "windows"]) || !metadata(value) || value.dataset !== "radar-period-metrics" ||
    typeof value.timeBasis !== "string" || !["source-observation-time", "source-observation-or-explicit-collector-fallback"].includes(value.timeBasis) || value.identityUnit !== "canonical-hostname" || value.population !== "public-eligible-recorded-hostnames" || typeof value.hostnamesSha256 !== "string" || !SHA256.test(value.hostnamesSha256) ||
    !Array.isArray(value.windows) || value.windows.length > 10_000 || !value.windows.every((window) => windowShape(window, value.asOf as string, value.coverage as unknown as PeriodCoverage)) ||
    new Set(value.windows.map((window) => window.key)).size !== value.windows.length || !["30d", "90d", "365d", "all"].every((key) => (value.windows as PeriodWindow[]).some((window) => window.key === key))) {
    throw new Error("The period metrics do not match their supported schema.");
  }
  return value as unknown as PeriodMetricsArtifact;
}

export function parseObservedHostnameRecords(value: unknown, asOf: string): ObservedHostnameRecord[] {
  if (!Array.isArray(value) || value.length > MAXIMUM_RECORDS || !value.every((row) => {
    if (!shape(row, ["id", "domain", "domainGroup", "brand", "firstSeen", "lastSeen", "firstRecordedAt", "firstPublishedAt", "observedDays", "observedDayLastSeen", "sources", "match", "assessment", "recordAvailable"], ["sourceTimeProvenances"]) ||
      typeof row.id !== "string" || !/^[a-f\d]{20}$/.test(row.id) || !hostname(row.domain) || !hostname(row.domainGroup) || !(row.domain === row.domainGroup || row.domain.endsWith(`[.]${row.domainGroup}`)) ||
      !text(row.brand, 120) || !timestamp(row.firstSeen) || !timestamp(row.lastSeen) || row.firstSeen > row.lastSeen || row.lastSeen > asOf || !nullableTimestamp(row.firstRecordedAt) || !nullableTimestamp(row.firstPublishedAt) ||
      (row.firstRecordedAt !== null && row.firstRecordedAt > asOf) || (row.firstPublishedAt !== null && row.firstPublishedAt > asOf) ||
      (row.firstPublishedAt !== null && row.firstRecordedAt === null) ||
      !sortedUnique(row.observedDays, date) || row.observedDays.length === 0 || row.observedDays[0] !== row.firstSeen.slice(0, 10) || row.observedDays.at(-1) !== row.lastSeen.slice(0, 10) ||
      !object(row.observedDayLastSeen) || !sortedUnique(row.sources, (source) => ["CertStream", "URLScan", "HECAVEX"].includes(String(source)), 3) || row.sources.length === 0 ||
      (Object.hasOwn(row, "sourceTimeProvenances") && (!sortedUnique(row.sourceTimeProvenances, (origin) => typeof origin === "string" && ["provider-observation-time", "collector-time-fallback", "legacy-normalized-unknown"].includes(origin), 3) || row.sourceTimeProvenances.length === 0)) ||
      !shape(row.match, ["score", "reasonCodes", "policyVersion"]) || !(row.match.score === null || integer(row.match.score, 100)) || !unique(row.match.reasonCodes, (reason) => typeof reason === "string" && /^[a-z][a-z0-9-]{1,79}$/.test(reason), 32) || !text(row.match.policyVersion, 160) || typeof row.recordAvailable !== "boolean") return false;
    const dayLast = row.observedDayLastSeen;
    const firstSeen = row.firstSeen;
    const lastSeen = row.lastSeen;
    if (Object.keys(dayLast).length !== row.observedDays.length || !row.observedDays.every((day) => timestamp(dayLast[day]) && dayLast[day].slice(0, 10) === day && dayLast[day] >= firstSeen && dayLast[day] <= lastSeen) || dayLast[row.observedDays.at(-1)!] !== lastSeen) return false;
    return row.assessment === null || (shape(row.assessment, ["verdict", "assessedAt", "evidenceReferences", "decisionId", "analystConfidence"]) && ["malicious", "suspicious", "benign", "inconclusive"].includes(String(row.assessment.verdict)) && timestamp(row.assessment.assessedAt) && unique(row.assessment.evidenceReferences, (reference) => text(reference, 512), 64) && row.assessment.evidenceReferences.length > 0 && typeof row.assessment.decisionId === "string" && /^[a-f\d]{24}$/.test(row.assessment.decisionId) && (row.assessment.analystConfidence === null || integer(row.assessment.analystConfidence, 100)));
  })) throw new Error("The observed hostname records do not match their supported schema.");
  return value as ObservedHostnameRecord[];
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (object(value)) return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}
function matchingMetadata(metrics: PeriodMetricsArtifact, index: ObservedHostnameIndex): boolean {
  return metrics.asOf === index.asOf && canonical(metrics.coverage) === canonical(index.coverage) && canonical(metrics.grouping) === canonical(index.grouping) && canonical(metrics.policyVersions) === canonical(index.policyVersions);
}
async function digest(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function validatePeriodCohort(metrics: PeriodMetricsArtifact, index: ObservedHostnameIndex, records: ObservedHostnameRecord[], indexSha256: string): Promise<PeriodOverviewData> {
  parsePeriodMetrics(metrics);
  parseObservedHostnameIndex(index);
  if (metrics.hostnamesSha256 !== indexSha256) throw new Error("The observed hostname index digest does not match the period metrics.");
  if (!matchingMetadata(metrics, index) || records.length !== index.recordCount) throw new Error("The observation cohort metadata or record count does not match.");
  parseObservedHostnameRecords(records, metrics.asOf);
  if (metrics.timeBasis === "source-observation-time" && records.some((row) => row.sourceTimeProvenances?.includes("collector-time-fallback"))) throw new Error("The observation-only time basis cannot include explicit collector fallback.");
  if (new Set(records.map((row) => row.domain)).size !== records.length || records.some((row, position) => position > 0 && records[position - 1].id >= row.id)) throw new Error("Observed hostname identities must be sorted and unique.");
  const identities = await Promise.all(records.map(async (row) => (await digest(new TextEncoder().encode(row.domain))).slice(0, 20) === row.id));
  if (identities.some((valid) => !valid)) throw new Error("An observed hostname identity does not match its canonical domain.");
  for (const window of metrics.windows) {
    const totals = periodTotals(records, window);
    const clocks = (key: "firstRecordedAt" | "firstPublishedAt") => records.filter((row) => row[key] !== null && row[key]! >= (window.startInclusive ?? "") && row[key]! < window.endExclusive).length;
    if (totals.uniqueHostnames !== window.uniqueHostnames || totals.domainGroups !== window.domainGroups || totals.candidateDays !== window.candidateDays ||
      (window.firstRecordedHostnames !== null && clocks("firstRecordedAt") !== window.firstRecordedHostnames) || (window.firstPublishedHostnames !== null && clocks("firstPublishedAt") !== window.firstPublishedHostnames)) throw new Error(`Period totals do not match the complete recorded cohort (${window.key}).`);
  }
  return { metrics, index, records, complete: true };
}

export type PeriodByteReader = (path: string, maximumBytes: number, signal?: AbortSignal) => Promise<Uint8Array<ArrayBuffer>>;
const fetchBytes: PeriodByteReader = async (path, maximumBytes, signal) => {
  const response = await fetch(path, { cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer", signal });
  if (!response.ok) throw new Error(`Observation artifact request failed with HTTP ${response.status}.`);
  return readBoundedBytes(response, maximumBytes);
};
const json = (bytes: Uint8Array<ArrayBuffer>, maximum = MAXIMUM_BYTES): unknown => {
  if (bytes.byteLength > maximum) throw new Error("Observation artifact exceeds its byte limit.");
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
};
export async function loadPeriodOverview({ signal, readBytes = fetchBytes }: { signal?: AbortSignal; readBytes?: PeriodByteReader } = {}): Promise<PeriodOverviewData> {
  const [metricsBytes, indexBytes] = await Promise.all([readBytes("/data/period-metrics-v1.json", MAXIMUM_BYTES, signal), readBytes("/data/observed-hostnames-v1.json", MAXIMUM_BYTES, signal)]);
  const metrics = parsePeriodMetrics(json(metricsBytes));
  const index = parseObservedHostnameIndex(json(indexBytes));
  const indexSha256 = await digest(indexBytes);
  if (metrics.hostnamesSha256 !== indexSha256) throw new Error("The observed hostname index digest does not match the period metrics.");
  const records: ObservedHostnameRecord[] = [];
  // Bound request concurrency as the archive grows; every advertised part is required.
  for (let offset = 0; offset < index.partitions.length; offset += 4) {
    const batches = await Promise.all(index.partitions.slice(offset, offset + 4).map(async (part) => {
      const bytes = await readBytes(part.path, MAXIMUM_BYTES, signal);
      if (bytes.byteLength !== part.bytes || await digest(bytes) !== part.sha256) throw new Error("An observed hostname part has invalid bytes or digest.");
      const rows = parseObservedHostnameRecords(json(bytes), index.asOf);
      if (rows.length !== part.records) throw new Error("An observed hostname part has an invalid record count.");
      return rows;
    }));
    for (const rows of batches) records.push(...rows);
  }
  return validatePeriodCohort(metrics, index, records, indexSha256);
}

/** SSR counts remain authoritative; these records are explicitly only a bounded 30-day preview. */
export function periodOverviewPreview(data: PeriodOverviewData, maximumBytes = 64 * 1024): PeriodOverviewData {
  const records: ObservedHostnameRecord[] = [];
  let used = 2;
  const window = data.metrics.windows.find((entry) => entry.key === "30d")!;
  for (const row of selectPeriodRecords(data.records, window)) {
    const size = new TextEncoder().encode(JSON.stringify(row)).length + 1;
    if (used + size > maximumBytes) break;
    records.push(row);
    used += size;
  }
  return { ...data, records, complete: false };
}

export function parsePeriodOverviewBootstrap(value: unknown): PeriodOverviewData {
  if (!shape(value, ["metrics", "index", "records", "complete"]) || value.complete !== false) throw new Error("Invalid embedded observation preview.");
  const metrics = parsePeriodMetrics(value.metrics);
  const index = parseObservedHostnameIndex(value.index);
  const records = parseObservedHostnameRecords(value.records, metrics.asOf);
  const window = metrics.windows.find((entry) => entry.key === "30d")!;
  if (!matchingMetadata(metrics, index) || records.length > window.uniqueHostnames || records.length > index.recordCount || selectPeriodRecords(records, window).length !== records.length || new Set(records.map((row) => row.id)).size !== records.length) throw new Error("Invalid embedded observation preview cohort.");
  return { metrics, index, records, complete: false };
}

export function observedHostnamesAsJson(records: ObservedHostnameRecord[], data: PeriodOverviewData, window: Pick<PeriodWindow, "key" | "startInclusive" | "endExclusive">): string {
  if (!data.complete) throw new Error("Complete verified observations are required for export.");
  return `${JSON.stringify({ schemaVersion: 1, dataset: "filtered-recorded-hostnames", asOf: data.metrics.asOf, timeBasis: data.metrics.timeBasis, identityUnit: data.metrics.identityUnit, population: data.metrics.population, hostnamesSha256: data.metrics.hostnamesSha256, grouping: data.metrics.grouping, coverage: data.metrics.coverage, policyVersions: data.metrics.policyVersions, window, recordCount: records.length, warning: "Recorded automated candidates are not maliciousness verdicts. Defanged hostnames must not be made clickable. Observation times use provider observation time or declared collector fallback; legacy timing provenance is incomplete, and absent sourceTimeProvenances remains unknown. Per-hostname provenance summarizes all recorded observations, not the origin of each endpoint timestamp. firstPublishedAt is the first captured verified publication receipt since activation for newly tracked hostnames with known recording times only, not the earliest-ever public date. Legacy hostnames with unknown firstRecordedAt keep firstPublishedAt null.", records }, null, 2)}\n`;
}
export function observedHostnamesAsCsv(records: ObservedHostnameRecord[], data: PeriodOverviewData, window: Pick<PeriodWindow, "key" | "startInclusive" | "endExclusive">): string {
  if (!data.complete) throw new Error("Complete verified observations are required for export.");
  const headings = ["canonical_hostname_id", "defanged_hostname", "defanged_private_psl_group", "potential_brand_match", "source_first_seen_utc", "source_last_seen_utc", "radar_first_recorded_at_utc", "first_verified_publication_receipt_utc", "sources", "explicit_assessment", "assessment_at_utc", "as_of_utc", "period_key", "period_start_inclusive_utc", "period_end_exclusive_utc", "hostname_index_sha256", "source_time_provenances"];
  const rows = records.map((row) => [row.id, row.domain, row.domainGroup, row.brand, row.firstSeen, row.lastSeen, row.firstRecordedAt, row.firstPublishedAt, row.sources.join(";"), row.assessment?.verdict ?? null, row.assessment?.assessedAt ?? null, data.metrics.asOf, window.key, window.startInclusive, window.endExclusive, data.metrics.hostnamesSha256, row.sourceTimeProvenances?.join(";") ?? null]);
  return `${[headings, ...rows].map((row) => row.map(safeCsvCell).join(",")).join("\r\n")}\r\n`;
}
