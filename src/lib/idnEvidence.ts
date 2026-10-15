import type { RadarSignal } from "../types.ts";
import { domainToUnicode } from "./signalComparison.ts";

export const MAXIMUM_IDN_EVIDENCE_BYTES = 2 * 1024 * 1024;
export const MAXIMUM_IDN_EVIDENCE_RECORDS = 2_500;

export type IdnSubstitution = { position: number; codePoint: string; replacement: string };

export type IdnMatchEvidence = {
  signalId: string;
  domain: string;
  brand: string;
  alias: string;
  matchedLabel: string;
  labelIndex: number;
  labelRole: "registrable" | "subdomain";
  substitutions: IdnSubstitution[];
};

export type IdnEvidenceArtifact = {
  schemaVersion: 1;
  dataset: "radar-idn-matches";
  generatedAt: string;
  snapshotSha256: string;
  profile: "radar-idn-visual-v1";
  records: IdnMatchEvidence[];
};

const TOP_FIELDS = ["schemaVersion", "dataset", "generatedAt", "snapshotSha256", "profile", "records"];
const RECORD_FIELDS = ["signalId", "domain", "brand", "alias", "matchedLabel", "labelIndex", "labelRole", "substitutions"];
const SUBSTITUTION_FIELDS = ["position", "codePoint", "replacement"];
const PROFILE_REPLACEMENTS: Readonly<Record<string, readonly string[]>> = {
  "U+0199": ["k"],
  "U+04E9": ["o", "e"],
  "U+04CF": ["i", "l"],
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactFields(value: Record<string, unknown>, fields: readonly string[]): boolean {
  return Object.keys(value).length === fields.length && fields.every((field) => Object.hasOwn(value, field));
}

function isCanonicalTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/u.test(value)) return false;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString() === value;
}

function isSafeText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum &&
    !/[\p{Cc}\p{Cf}<>]/u.test(value);
}

/** Validate public explanation provenance, never infer a detector trace from visual distance. */
export function parseIdnEvidence(
  value: unknown,
  signals: readonly RadarSignal[],
  expectedGeneratedAt?: string,
  expectedSnapshotSha256?: string,
): IdnEvidenceArtifact {
  if (!isRecord(value) || !hasExactFields(value, TOP_FIELDS) || value.schemaVersion !== 1 ||
    value.dataset !== "radar-idn-matches" || value.profile !== "radar-idn-visual-v1" ||
    !isCanonicalTimestamp(value.generatedAt) || typeof value.snapshotSha256 !== "string" ||
    !/^[a-f\d]{64}$/u.test(value.snapshotSha256) ||
    (expectedGeneratedAt !== undefined && value.generatedAt !== expectedGeneratedAt) ||
    (expectedSnapshotSha256 !== undefined && value.snapshotSha256 !== expectedSnapshotSha256) ||
    !Array.isArray(value.records) || value.records.length > MAXIMUM_IDN_EVIDENCE_RECORDS) {
    throw new Error("The IDN explanation artifact does not match its supported release contract.");
  }
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > MAXIMUM_IDN_EVIDENCE_BYTES) {
    throw new Error("The IDN explanation artifact exceeds its byte budget.");
  }
  const signalsById = new Map(signals.map((signal) => [signal.id, signal]));
  const seen = new Set<string>();
  for (const record of value.records) {
    if (!isRecord(record) || !hasExactFields(record, RECORD_FIELDS) ||
      typeof record.signalId !== "string" || !/^[a-f\d]{20}$/u.test(record.signalId) || seen.has(record.signalId) ||
      typeof record.domain !== "string" || !/^[a-z\d-]+(?:\[\.\][a-z\d-]+)+$/u.test(record.domain) ||
      !record.domain.split("[.]").some((label) => label.startsWith("xn--")) ||
      !isSafeText(record.brand, 120) || !isSafeText(record.alias, 63) ||
      !/^[a-z\d]+(?:[ -][a-z\d]+)*$/u.test(record.alias) ||
      !isSafeText(record.matchedLabel, 252) || !/^[\p{L}\p{N}\p{M}-]+$/u.test(record.matchedLabel) ||
      record.matchedLabel.normalize("NFC") !== record.matchedLabel ||
      typeof record.labelIndex !== "number" || !Number.isInteger(record.labelIndex) || record.labelIndex < 0 ||
      (record.labelRole !== "registrable" && record.labelRole !== "subdomain") ||
      !Array.isArray(record.substitutions) || record.substitutions.length < 1 || record.substitutions.length > 63) {
      throw new Error("The IDN explanation artifact contains a malformed record.");
    }
    const signal = signalsById.get(record.signalId);
    const hostname = record.domain.replaceAll("[.]", ".");
    let canonicalHostname: string;
    try {
      canonicalHostname = new URL(`https://${hostname}`).hostname;
    } catch {
      throw new Error("The IDN explanation contains a malformed A-label hostname.");
    }
    const labels = domainToUnicode(record.domain).split(".");
    const characters = Array.from(record.matchedLabel);
    if (hostname.length > 253 || hostname !== canonicalHostname ||
      hostname.split(".").some((label) => label.length > 63 || label.startsWith("-") || label.endsWith("-")) ||
      !signal || signal.domain !== record.domain || signal.brand !== record.brand ||
      characters.length > 63 || labels[record.labelIndex] !== record.matchedLabel) {
      throw new Error("The IDN explanation does not correspond to the current published signal.");
    }
    let previousPosition = -1;
    for (const substitution of record.substitutions) {
      if (!isRecord(substitution) || !hasExactFields(substitution, SUBSTITUTION_FIELDS) ||
        typeof substitution.position !== "number" || !Number.isInteger(substitution.position) ||
        substitution.position <= previousPosition || substitution.position >= characters.length ||
        typeof substitution.codePoint !== "string" || typeof substitution.replacement !== "string" ||
        !Object.hasOwn(PROFILE_REPLACEMENTS, substitution.codePoint) ||
        !PROFILE_REPLACEMENTS[substitution.codePoint].includes(substitution.replacement) ||
        substitution.codePoint !== `U+${characters[substitution.position].codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`) {
        throw new Error("The IDN explanation contains a substitution outside the reviewed visual profile.");
      }
      previousPosition = substitution.position;
    }
    seen.add(record.signalId);
  }
  return value as IdnEvidenceArtifact;
}
