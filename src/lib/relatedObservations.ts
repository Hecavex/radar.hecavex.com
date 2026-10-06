import { readBoundedJson } from "./boundedJson.ts";

const ISO_UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
const IDENTIFIER = /^[a-f\d]{20}$/;
const CLUSTER_IDENTIFIER = /^[a-f\d]{16}$/;
const SHA256 = /^[a-f\d]{64}$/;
const CONTROL_OR_FORMAT = /[\p{Cc}\p{Cf}]/u;
const MAXIMUM_ARTIFACT_BYTES = 512 * 1024;

export const RELATION_EVIDENCE_TYPES = [
  "primary-html-sha256",
  "certificate-sha256",
  "certificate-san",
  "redirect-domain",
  "ip-address",
  "asn",
  "dns-a",
  "dns-aaaa",
  "dns-cname",
  "dns-ns",
  "dns-mx",
] as const;

export type RelationEvidenceType = (typeof RELATION_EVIDENCE_TYPES)[number];
export type RelationStrength = "strong" | "corroborated-supporting" | "shared-context";

export type RelatedObservationNode = {
  signalId: string;
  domain: string;
  clusterId: string;
};

export type RelatedObservationEvidence = {
  type: RelationEvidenceType;
  value: string;
};

export type RelatedObservationEdge = {
  id: string;
  source: string;
  target: string;
  strength: RelationStrength;
  evidence: RelatedObservationEvidence[];
};

export type RelatedObservations = {
  schemaVersion: 1;
  dataset: "radar-related-observations";
  generatedAt: string;
  semantics: string;
  nodes: RelatedObservationNode[];
  edges: RelatedObservationEdge[];
  suppressedEvidence: {
    highFanoutValues: number;
    temporalPairs: number;
    edgeLimit: number;
  };
};

const STRONG_EVIDENCE = new Set<RelationEvidenceType>(["primary-html-sha256", "certificate-sha256"]);
const SUPPORTING_FAMILY: Partial<Record<RelationEvidenceType, string>> = {
  "certificate-san": "certificate-name",
  "redirect-domain": "redirect-destination",
  "ip-address": "network-location",
  asn: "network-location",
  "dns-a": "network-location",
  "dns-aaaa": "network-location",
  "dns-cname": "dns-alias",
  "dns-ns": "dns-authority",
  "dns-mx": "mail-routing",
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function hasExactFields(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && expected.every((field) => Object.hasOwn(value, field));
}

function isCanonicalTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !ISO_UTC_TIMESTAMP.test(value)) return false;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) && new Date(parsed).toISOString() === value;
}

function isCleanText(value: unknown, maximum: number): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= maximum &&
    value.trim() === value &&
    value.replace(/\s+/gu, " ") === value &&
    !CONTROL_OR_FORMAT.test(value)
  );
}

function isDefangedDomain(value: unknown, allowWildcard = false): value is string {
  if (allowWildcard && typeof value === "string" && value.startsWith("*[.]")) {
    return isDefangedDomain(value.slice(4));
  }
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 505 ||
    value !== value.toLowerCase() ||
    /[@/?#:\\]/u.test(value) ||
    value.replaceAll("[.]", "").includes(".")
  ) return false;
  const labels = value.split("[.]");
  if (labels.length < 2 || labels.some((label) => label.length === 0 || label.length > 63)) return false;
  if (!labels.every((label) => /^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/u.test(label))) return false;
  const tld = labels.at(-1)!;
  return tld.startsWith("xn--") || /^[a-z]{2,63}$/u.test(tld);
}

function isDefangedIp(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 80 || /[@/?#]/u.test(value)) return false;
  if (value.includes("[.]")) {
    if (value.includes(":") || value.replaceAll("[.]", "").includes(".")) return false;
    const octets = value.split("[.]");
    return (
      octets.length === 4 &&
      octets.every((octet) => /^\d{1,3}$/u.test(octet) && String(Number(octet)) === octet && Number(octet) <= 255)
    );
  }
  if (!value.includes("[:]") || value.replaceAll("[:]", "").includes(":") || value.includes(".")) return false;
  const refanged = value.replaceAll("[:]", ":");
  if (!/^[a-f\d:]+$/u.test(refanged) || (refanged.match(/::/gu) ?? []).length > 1 || refanged.includes(":::")) {
    return false;
  }
  const segments = refanged.split(":");
  const compacted = refanged.includes("::");
  return (
    (compacted ? segments.filter(Boolean).length < 8 : segments.length === 8) &&
    segments.filter(Boolean).every((segment) => /^[a-f\d]{1,4}$/u.test(segment)) &&
    (compacted || segments.length === 8)
  );
}

function isEvidenceValue(type: RelationEvidenceType, value: unknown): value is string {
  if (type === "primary-html-sha256" || type === "certificate-sha256") {
    return typeof value === "string" && SHA256.test(value);
  }
  if (type === "asn") {
    if (typeof value !== "string" || !/^\d{1,10}$/u.test(value) || String(Number(value)) !== value) return false;
    const asn = Number(value);
    return Number.isSafeInteger(asn) && asn > 0 && asn <= 4_294_967_295;
  }
  if (type === "ip-address" || type === "dns-a" || type === "dns-aaaa") return isDefangedIp(value);
  return isDefangedDomain(value, type === "certificate-san");
}

function isNode(value: unknown): value is RelatedObservationNode {
  return (
    isRecord(value) &&
    hasExactFields(value, ["signalId", "domain", "clusterId"]) &&
    typeof value.signalId === "string" && IDENTIFIER.test(value.signalId) &&
    isDefangedDomain(value.domain) &&
    typeof value.clusterId === "string" && CLUSTER_IDENTIFIER.test(value.clusterId)
  );
}

function isEvidence(value: unknown): value is RelatedObservationEvidence {
  if (!isRecord(value) || !hasExactFields(value, ["type", "value"])) return false;
  if (typeof value.type !== "string" || !RELATION_EVIDENCE_TYPES.includes(value.type as RelationEvidenceType)) {
    return false;
  }
  return isEvidenceValue(value.type as RelationEvidenceType, value.value);
}

function isEdge(value: unknown): value is RelatedObservationEdge {
  if (!(
    isRecord(value) &&
    hasExactFields(value, ["id", "source", "target", "strength", "evidence"]) &&
    typeof value.id === "string" && IDENTIFIER.test(value.id) &&
    typeof value.source === "string" && IDENTIFIER.test(value.source) &&
    typeof value.target === "string" && IDENTIFIER.test(value.target) &&
    value.source !== value.target &&
    (value.strength === "strong" || value.strength === "corroborated-supporting" || value.strength === "shared-context") &&
    Array.isArray(value.evidence) &&
    value.evidence.length >= 1 &&
    value.evidence.length <= 8 &&
    value.evidence.every(isEvidence) &&
    new Set(value.evidence.map((item) => `${item.type}\u0000${item.value}`)).size === value.evidence.length
  )) return false;
  const types = value.evidence.map((item) => item.type);
  const hasStrongEvidence = types.some((type) => STRONG_EVIDENCE.has(type));
  const supportingFamilies = new Set(types.map((type) => SUPPORTING_FAMILY[type]).filter(Boolean));
  return value.strength === "strong" ? hasStrongEvidence : !hasStrongEvidence && supportingFamilies.size >= 2;
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

export function parseRelatedObservations(value: unknown): RelatedObservations {
  if (
    !isRecord(value) ||
    !hasExactFields(value, [
      "schemaVersion",
      "dataset",
      "generatedAt",
      "semantics",
      "nodes",
      "edges",
      "suppressedEvidence",
    ]) ||
    value.schemaVersion !== 1 ||
    value.dataset !== "radar-related-observations" ||
    !isCanonicalTimestamp(value.generatedAt) ||
    !isCleanText(value.semantics, 320) ||
    !value.semantics.toLowerCase().includes("not") ||
    !value.semantics.toLowerCase().includes("attribution") ||
    !Array.isArray(value.nodes) ||
    value.nodes.length > 25_000 ||
    !value.nodes.every(isNode) ||
    !Array.isArray(value.edges) ||
    value.edges.length > 2_000 ||
    !value.edges.every(isEdge) ||
    !isRecord(value.suppressedEvidence) ||
    !hasExactFields(value.suppressedEvidence, ["highFanoutValues", "temporalPairs", "edgeLimit"]) ||
    !isNonNegativeInteger(value.suppressedEvidence.highFanoutValues) ||
    !isNonNegativeInteger(value.suppressedEvidence.temporalPairs) ||
    !isNonNegativeInteger(value.suppressedEvidence.edgeLimit)
  ) {
    throw new Error("The related-observation artifact does not match its supported schema.");
  }

  const nodes = value.nodes as RelatedObservationNode[];
  const edges = value.edges as RelatedObservationEdge[];
  const nodeIds = new Set(nodes.map((node) => node.signalId));
  const nodeDomains = new Set(nodes.map((node) => node.domain));
  const edgeIds = new Set(edges.map((edge) => edge.id));
  const edgePairs = new Set(edges.map((edge) => [edge.source, edge.target].sort().join("\u0000")));
  const validReferences = edges.every((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const clustersBySignal = new Map(nodes.map((node) => [node.signalId, node.clusterId]));
  const validClusters = edges.every((edge) => clustersBySignal.get(edge.source) === clustersBySignal.get(edge.target));
  if (
    nodeIds.size !== nodes.length ||
    nodeDomains.size !== nodes.length ||
    edgeIds.size !== edges.length ||
    edgePairs.size !== edges.length ||
    !validReferences ||
    !validClusters ||
    (edges.length === 0 && nodes.length !== 0)
  ) {
    throw new Error("The related-observation artifact contains inconsistent graph references.");
  }
  return value as RelatedObservations;
}

export async function loadRelatedObservations(signal?: AbortSignal): Promise<RelatedObservations | null> {
  try {
    const response = await fetch("/data/related-observations.json", {
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      signal,
    });
    if (!response.ok) return null;
    return parseRelatedObservations(await readBoundedJson(response, MAXIMUM_ARTIFACT_BYTES));
  } catch {
    return null;
  }
}
