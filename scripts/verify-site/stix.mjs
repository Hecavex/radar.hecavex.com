/* global URL */

// Data distributions: STIX bundle, signal-detail sidecars, syndication feeds and published defanging.

import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { JSDOM } from "jsdom";
import { findFangedStrings } from "../published-defanging.mjs";
import { signalDetailFileRawBytes, signalDetailSetRawBytes, stixBundleRawBytes } from "./budgets.mjs";
import {
  assert,
  collectReleasedDocuments,
  output,
  outputPath,
  publicOrigin,
  releaseDocument,
  root,
  walk,
} from "./shared.mjs";

const detailFields = ["schemaVersion", "dataset", "signalId", "domain", "generatedAt", "observations"];
const domainContextFields = ["observedAt", "dns", "registration"];
const dnsContextFields = ["a", "aaaa", "cname", "ns", "mx", "minimumTtl", "queriesCompleted"];
const registrationContextFields = ["registrar", "registeredAt", "updatedAt", "expiresAt", "statuses"];
const observationFields = ["source", "observedAt", "page", "network", "assessment", "certificate"];
const pageFields = ["title", "httpStatus"];
const networkFields = ["ipAddress", "asn", "asnDescription", "asnRegistry"];
const assessmentFields = ["urlscanVerdictScore", "urlscanCategories", "redirectedToDomain"];
const certificateFields = [
  "countryName",
  "issuer",
  "commonName",
  "notBefore",
  "notAfter",
  "subjectAltNames",
  "subjectAltNameCount",
  "serialNumberHex",
  "fingerprints",
];
const fingerprintFields = ["md5", "sha1", "sha256"];
const contextChangeFields = ["eventId", "observedAt", "component", "changeType", "changedFields", "source", "evidence"];
const contextSourceFields = ["name", "observedAt", "referenceUrl"];
const contextEvidenceFields = ["previousSha256", "currentSha256", "primaryHtmlSha256", "certificateSha256"];
const utcTimestamp = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/u;
const signalIdentifier = /^[a-f\d]{20}$/u;
const lowerHex = /^[a-f\d]+$/u;
const stixUuid = /^[a-f\d]{8}-[a-f\d]{4}-5[a-f\d]{3}-[89ab][a-f\d]{3}-[a-f\d]{12}$/u;
const stixBundleFields = ["type", "id", "objects"];
const stixDomainFields = ["type", "spec_version", "id", "value"];
const stixObservedRequiredFields = [
  "type",
  "spec_version",
  "id",
  "created",
  "modified",
  "first_observed",
  "last_observed",
  "number_observed",
  "object_refs",
  "x_hecavex_com_signal_id",
  "x_hecavex_com_sources",
  "x_hecavex_com_status",
  "x_hecavex_com_matching_score",
  "x_hecavex_com_evidence_tier",
  "x_hecavex_com_review_state",
  "x_hecavex_com_lt_relevance",
  "x_hecavex_com_observation_only",
  "x_hecavex_com_radar_first_seen",
  "x_hecavex_com_radar_last_seen",
];
const stixObservedOptionalFields = ["external_references", "x_hecavex_com_brand", "x_hecavex_com_reason_codes"];
const supportedSources = new Set(["CertStream", "URLScan", "HECAVEX"]);
const stixDomainNamespace = "00abedb4-aa42-466c-9c01-fed23315a9b7";
const urlNamespace = "6ba7b811-9dad-11d1-80b4-00c04fd430c8";

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactFields(value, fields) {
  return isRecord(value) && Object.keys(value).length === fields.length && fields.every((field) => Object.hasOwn(value, field));
}

function hasRequiredAndOptionalFields(value, required, optional) {
  const allowed = new Set([...required, ...optional]);
  return (
    isRecord(value) &&
    required.every((field) => Object.hasOwn(value, field)) &&
    Object.keys(value).every((field) => allowed.has(field))
  );
}

function timestampValue(value) {
  if (typeof value !== "string" || !utcTimestamp.test(value)) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) && new Date(parsed).toISOString() === value ? parsed : null;
}

function uuidBytes(value) {
  const compact = value.replaceAll("-", "");
  assert(/^[a-f\d]{32}$/u.test(compact), `Invalid UUID namespace ${value}.`);
  return Uint8Array.from(compact.match(/.{2}/gu), (pair) => Number.parseInt(pair, 16));
}

function uuid5(namespace, name) {
  // UUIDv5 requires SHA-1 under RFC 9562 section 5.5. This is deterministic
  // naming for public STIX identifiers, never a security or integrity hash.
  const digest = createHash("sha1").update(uuidBytes(namespace)).update(name, "utf8").digest().subarray(0, 16);
  digest[6] = (digest[6] & 0x0f) | 0x50;
  digest[8] = (digest[8] & 0x3f) | 0x80;
  const hex = [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function refangedRadarDomain(value) {
  if (typeof value !== "string" || value.length === 0 || value.includes("[:]") || value.includes(":")) return null;
  const domain = value.replaceAll("[.]", ".");
  if (domain.length > 253 || domain !== domain.toLowerCase() || domain.includes("[") || domain.includes("]")) return null;
  const labels = domain.split(".");
  if (labels.length < 2) return null;
  return labels.every((label) => /^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/u.test(label)) ? domain : null;
}

function isDefangedIp(value) {
  if (typeof value !== "string" || /[@/?#]/u.test(value)) return false;
  if (value.includes("[.]")) {
    if (value.includes(":") || value.replaceAll("[.]", "").includes(".")) return false;
    const octets = value.split("[.]");
    return octets.length === 4 && octets.every((octet) => /^\d{1,3}$/u.test(octet) && Number(octet) <= 255);
  }
  const refanged = value.replaceAll("[:]", ":");
  return value.includes("[:]") && !refanged.includes("[") && !refanged.includes("]") && /^[a-f\d:]+$/u.test(refanged);
}

function verifyDomainContext(context, generatedAt, label) {
  assert(hasExactFields(context, domainContextFields), `${label} has unexpected fields.`);
  const observedAt = timestampValue(context.observedAt);
  assert(observedAt !== null && observedAt <= generatedAt + 5 * 60 * 1000, `${label} has an invalid observedAt.`);
  assert(hasExactFields(context.dns, dnsContextFields), `${label} has invalid DNS fields.`);
  const dns = context.dns;
  const uniqueList = (value, validator) =>
    Array.isArray(value) && value.length <= 12 && new Set(value).size === value.length && value.every(validator);
  assert(uniqueList(dns.a, isDefangedIp) && uniqueList(dns.aaaa, isDefangedIp), `${label} has invalid IP answers.`);
  for (const field of ["cname", "ns"]) {
    assert(uniqueList(dns[field], (value) => refangedRadarDomain(value) !== null), `${label} has invalid ${field} answers.`);
  }
  assert(
    uniqueList(dns.mx, (value) => {
      if (typeof value !== "string") return false;
      const separator = value.indexOf(" ");
      return separator > 0 && /^\d{1,5}$/u.test(value.slice(0, separator)) && refangedRadarDomain(value.slice(separator + 1)) !== null;
    }),
    `${label} has invalid MX answers.`,
  );
  assert(
    (dns.minimumTtl === null || (Number.isInteger(dns.minimumTtl) && dns.minimumTtl >= 0)) &&
      Number.isInteger(dns.queriesCompleted) &&
      dns.queriesCompleted >= 0 &&
      dns.queriesCompleted <= 5,
    `${label} has invalid DNS counters.`,
  );
  if (context.registration === null) return;
  const registration = context.registration;
  assert(
    hasRequiredAndOptionalFields(registration, registrationContextFields, ["domain"]),
    `${label} has invalid registration fields.`,
  );
  assert(
    registration.domain === undefined || refangedRadarDomain(registration.domain) !== null,
    `${label} has an invalid registration scope.`,
  );
  assert(
    registration.registrar === null ||
      (typeof registration.registrar === "string" && registration.registrar.length > 0 && registration.registrar.length <= 160),
    `${label} has an invalid registrar.`,
  );
  for (const field of ["registeredAt", "updatedAt", "expiresAt"]) {
    assert(registration[field] === null || timestampValue(registration[field]) !== null, `${label} has an invalid ${field}.`);
  }
  assert(
    uniqueList(registration.statuses, (value) => typeof value === "string" && /^[a-z\d-]{1,64}$/u.test(value)),
    `${label} has invalid registration statuses.`,
  );
}

function verifyContextChange(change, generatedAt, label) {
  assert(hasExactFields(change, contextChangeFields), `${label} has unexpected fields.`);
  const changedFieldSemantics = {
    "first-resolving": ["a", "aaaa", "cname"],
    "stopped-resolving": ["a", "aaaa", "cname"],
    "dns-a-changed": ["a"],
    "dns-aaaa-changed": ["aaaa"],
    "dns-cname-changed": ["cname"],
    "dns-ns-changed": ["ns"],
    "dns-mx-changed": ["mx"],
    "rdap-registrar-changed": ["registrar"],
    "rdap-status-changed": ["statuses"],
    "rdap-expiry-changed": ["expiresAt"],
    "urlscan-title-changed": ["pageTitle"],
    "urlscan-redirect-changed": ["redirectedToDomain"],
    "urlscan-http-status-changed": ["httpStatus"],
    "urlscan-ip-changed": ["ipAddress"],
    "urlscan-asn-changed": ["asn"],
    "urlscan-primary-html-sha256-changed": ["primaryHtmlSha256"],
    "urlscan-certificate-fingerprint-changed": ["certificateFingerprintSha256"],
    "certificate-reissued": ["certificateFingerprintSha256", "certificateIssuer", "certificateNotBefore", "certificateNotAfter"],
  };
  const semantics = {
    dns: {
      types: ["first-resolving", "stopped-resolving", "dns-a-changed", "dns-aaaa-changed", "dns-cname-changed", "dns-ns-changed", "dns-mx-changed"],
      source: "Cloudflare DNS",
      reference: "https://cloudflare-dns.com/dns-query",
    },
    rdap: {
      types: ["rdap-registrar-changed", "rdap-status-changed", "rdap-expiry-changed"],
      source: "RDAP",
      reference: "https://data.iana.org/rdap/dns.json",
    },
    urlscan: {
      types: ["urlscan-title-changed", "urlscan-redirect-changed", "urlscan-http-status-changed", "urlscan-ip-changed", "urlscan-asn-changed", "urlscan-primary-html-sha256-changed", "urlscan-certificate-fingerprint-changed", "certificate-reissued"],
      source: "URLScan",
      reference: null,
    },
  };
  assert(Object.hasOwn(semantics, change.component), `${label} component is unsupported.`);
  assert(semantics[change.component].types.includes(change.changeType), `${label} semantic type is inconsistent.`);
  assert(/^[a-f\d]{32}$/u.test(change.eventId), `${label} event ID is malformed.`);
  const observedAt = timestampValue(change.observedAt);
  assert(observedAt !== null && observedAt <= generatedAt + 5 * 60 * 1000, `${label} timestamp is malformed.`);
  assert(
    Array.isArray(change.changedFields) && change.changedFields.length >= 1 && change.changedFields.length <= 32 &&
      new Set(change.changedFields).size === change.changedFields.length &&
      change.changedFields.every((field) =>
        typeof field === "string" &&
        /^[A-Za-z][A-Za-z0-9]{0,63}$/u.test(field) &&
        changedFieldSemantics[change.changeType].includes(field),
      ),
    `${label} changed-field list is malformed.`,
  );
  assert(hasExactFields(change.source, contextSourceFields), `${label} source has unexpected fields.`);
  const sourceObservedAt = timestampValue(change.source.observedAt);
  assert(
    change.source.name === semantics[change.component].source &&
      sourceObservedAt !== null && sourceObservedAt <= observedAt + 5 * 60 * 1000,
    `${label} source identity or provider timestamp drifted.`,
  );
  if (change.component === "urlscan") {
    assert(/^https:\/\/urlscan\.io\/(?:|result\/[a-f\d-]{36}\/)$/u.test(change.source.referenceUrl), `${label} URLScan reference is unsafe.`);
  } else {
    assert(change.source.referenceUrl === semantics[change.component].reference, `${label} source reference is unsafe.`);
  }
  assert(hasExactFields(change.evidence, contextEvidenceFields), `${label} evidence has unexpected fields.`);
  assert(/^[a-f\d]{64}$/u.test(change.evidence.previousSha256) && /^[a-f\d]{64}$/u.test(change.evidence.currentSha256), `${label} component digests are malformed.`);
  assert(
    Array.isArray(change.evidence.primaryHtmlSha256) && change.evidence.primaryHtmlSha256.length <= 2 &&
      new Set(change.evidence.primaryHtmlSha256).size === change.evidence.primaryHtmlSha256.length &&
      change.evidence.primaryHtmlSha256.every((digest) => /^[a-f\d]{64}$/u.test(digest)),
    `${label} HTML hashes are malformed.`,
  );
  assert(isNullableHex(change.evidence.certificateSha256, 64), `${label} certificate hash is malformed.`);
  if (change.component !== "urlscan") {
    assert(change.evidence.primaryHtmlSha256.length === 0 && change.evidence.certificateSha256 === null, `${label} leaks URLScan evidence into another source.`);
  }
}

export function verifyStixBundle() {
  const snapshot = JSON.parse(readFileSync(join(output, "data", "radar.json"), "utf8"));
  assert(Array.isArray(snapshot.signals), "Built radar.json has no signal list for STIX verification.");
  const path = join(output, "data", "radar.stix.json");
  const rawBytes = statSync(path).size;
  assert(rawBytes > 0 && rawBytes <= stixBundleRawBytes, "Built radar.stix.json is empty or larger than 2 MiB.");

  let bundle;
  try {
    bundle = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    throw new Error("Built radar.stix.json is not valid UTF-8 JSON.");
  }
  assert(hasExactFields(bundle, stixBundleFields), "STIX bundle does not use its exact top-level fields.");
  assert(bundle.type === "bundle" && typeof bundle.id === "string", "STIX bundle has the wrong type or no identifier.");
  assert(stixUuid.test(bundle.id.replace(/^bundle--/u, "")), "STIX bundle identifier is not a namespaced UUIDv5.");
  assert(Array.isArray(bundle.objects), "STIX bundle has no object list.");
  assert(bundle.objects.length === snapshot.signals.length * 2, "STIX bundle is not a one-to-one projection of live signals.");

  const expectedSignals = [...snapshot.signals].sort((left, right) => {
    const leftDomain = refangedRadarDomain(left.domain) ?? "";
    const rightDomain = refangedRadarDomain(right.domain) ?? "";
    return leftDomain.localeCompare(rightDomain) || String(left.id).localeCompare(String(right.id));
  });
  const radarNamespace = uuid5(urlNamespace, "https://radar.hecavex.com/data/radar.stix.json");
  const objectIds = new Set();
  const expectedObjectIds = [];
  for (let index = 0; index < expectedSignals.length; index += 1) {
    const signal = expectedSignals[index];
    const domain = refangedRadarDomain(signal.domain);
    assert(domain !== null, `Live signal ${signal.id} cannot be safely represented as a STIX domain-name.`);
    const domainObject = bundle.objects[index * 2];
    const observed = bundle.objects[index * 2 + 1];
    const label = `STIX signal ${signal.id}`;

    assert(hasExactFields(domainObject, stixDomainFields), `${label} domain-name object has unexpected fields.`);
    assert(domainObject.type === "domain-name" && domainObject.spec_version === "2.1", `${label} has the wrong SCO type or version.`);
    assert(typeof domainObject.id === "string" && domainObject.id.startsWith("domain-name--"), `${label} has no domain-name ID.`);
    assert(stixUuid.test(domainObject.id.slice("domain-name--".length)), `${label} domain-name ID is not a UUIDv5.`);
    assert(
      domainObject.id === `domain-name--${uuid5(stixDomainNamespace, JSON.stringify({ value: domain }))}`,
      `${label} domain-name ID is not the deterministic STIX 2.1 identifier.`,
    );
    assert(domainObject.value === domain, `${label} does not contain the corresponding raw normalized domain.`);
    assert(
      !["[", "]", "/", "?", ":", "#"].some((character) => domainObject.value.includes(character)),
      `${label} domain-name value is defanged or contains URL data.`,
    );

    assert(isRecord(observed), `${label} has no Observed Data object.`);
    const observedKeys = Object.keys(observed);
    assert(
      stixObservedRequiredFields.every((field) => Object.hasOwn(observed, field)) &&
        observedKeys.every((field) => stixObservedRequiredFields.includes(field) || stixObservedOptionalFields.includes(field)),
      `${label} Observed Data object has missing or unexpected fields.`,
    );
    assert(observed.type === "observed-data" && observed.spec_version === "2.1", `${label} has the wrong SDO type or version.`);
    assert(typeof observed.id === "string" && observed.id.startsWith("observed-data--"), `${label} has no Observed Data ID.`);
    assert(stixUuid.test(observed.id.slice("observed-data--".length)), `${label} Observed Data ID is not a UUIDv5.`);
    assert(
      observed.id === `observed-data--${uuid5(radarNamespace, `observed-data:${signal.id}:${signal.firstSeen}`)}`,
      `${label} Observed Data ID is not the deterministic Radar identifier.`,
    );
    assert(observed.created === signal.firstSeen && observed.modified === snapshot.generatedAt, `${label} version timestamps drift from the snapshot.`);
    assert(timestampValue(observed.created) !== null && timestampValue(observed.modified) !== null, `${label} version timestamps are malformed.`);
    assert(timestampValue(observed.created) <= timestampValue(observed.modified), `${label} was modified before it was created.`);
    assert(
      observed.first_observed === signal.lastSeen && observed.last_observed === signal.lastSeen && observed.number_observed === 1,
      `${label} must represent exactly one latest observation.`,
    );
    assert(Array.isArray(observed.object_refs) && observed.object_refs.length === 1 && observed.object_refs[0] === domainObject.id, `${label} does not reference its SCO exactly once.`);
    assert(observed.x_hecavex_com_signal_id === signal.id, `${label} lost the Radar signal identifier.`);
    const expectedSources = [...signal.sources].sort();
    assert(expectedSources.every((source) => supportedSources.has(source)), `${label} contains an unsupported Radar source.`);
    assert(JSON.stringify(observed.x_hecavex_com_sources) === JSON.stringify(expectedSources), `${label} source metadata drifted.`);
    assert(observed.x_hecavex_com_status === signal.status, `${label} status metadata drifted.`);
    assert(observed.x_hecavex_com_matching_score === signal.confidence, `${label} matching score metadata drifted.`);
    assert(observed.x_hecavex_com_evidence_tier === signal.evidenceTier, `${label} evidence tier metadata drifted.`);
    assert(observed.x_hecavex_com_review_state === signal.reviewState, `${label} review state metadata drifted.`);
    assert(observed.x_hecavex_com_lt_relevance === signal.ltRelevance, `${label} Lithuanian-relevance metadata drifted.`);
    assert(observed.x_hecavex_com_observation_only === true, `${label} lost its observation-only boundary.`);
    assert(
      observed.x_hecavex_com_radar_first_seen === signal.firstSeen && observed.x_hecavex_com_radar_last_seen === signal.lastSeen,
      `${label} lost its Radar observation interval.`,
    );
    if (signal.brand === null) {
      assert(!Object.hasOwn(observed, "x_hecavex_com_brand"), `${label} invents a null brand property.`);
    } else {
      assert(observed.x_hecavex_com_brand === signal.brand, `${label} brand metadata drifted.`);
    }
    const expectedReasons = signal.reasonCodes ?? [];
    if (expectedReasons.length === 0) {
      assert(!Object.hasOwn(observed, "x_hecavex_com_reason_codes"), `${label} invents empty reason metadata.`);
    } else {
      assert(JSON.stringify(observed.x_hecavex_com_reason_codes) === JSON.stringify(expectedReasons), `${label} reason metadata drifted.`);
    }
    assert(!Object.hasOwn(observed, "confidence") && !Object.hasOwn(observed, "revoked"), `${label} misuses a standard STIX verdict property.`);

    const expectedReferenceUrl =
      expectedSources.includes("URLScan") && typeof signal.referenceUrl === "string" ? signal.referenceUrl : null;
    if (expectedReferenceUrl === null) {
      assert(!Object.hasOwn(observed, "external_references"), `${label} exposes an external reference without a URLScan result.`);
    } else {
      assert(
        Array.isArray(observed.external_references) && observed.external_references.length === 1,
        `${label} must expose exactly one URLScan external reference.`,
      );
      const reference = observed.external_references[0];
      assert(
        hasExactFields(reference, ["source_name", "url"]) &&
          reference.source_name === "URLScan" &&
          reference.url === expectedReferenceUrl &&
          /^https:\/\/urlscan\.io\/result\/[a-f\d-]{36}\/$/u.test(reference.url),
        `${label} exposes an unsafe or mismatched URLScan external reference.`,
      );
    }

    for (const id of [domainObject.id, observed.id]) {
      assert(!objectIds.has(id), `STIX bundle contains duplicate object ID ${id}.`);
      objectIds.add(id);
      expectedObjectIds.push(id);
    }
  }
  const bundleKey = JSON.stringify({ generated_at: snapshot.generatedAt, object_ids: expectedObjectIds });
  assert(bundle.id === `bundle--${uuid5(radarNamespace, bundleKey)}`, "STIX bundle identifier does not match its exact projected contents.");
  return { path, rawBytes };
}

function isNullableText(value, maximum) {
  return (
    value === null ||
    (typeof value === "string" &&
      value.length > 0 &&
      value.length <= maximum &&
      value.trim() === value &&
      !/[\p{Cc}\p{Cf}]/u.test(value) &&
      !/https?:\/\//iu.test(value) &&
      !/\S+@\S+/u.test(value))
  );
}

function isNullableHex(value, length) {
  return value === null || (typeof value === "string" && value.length === length && lowerHex.test(value));
}

function verifyPageDetail(value, label) {
  if (value === null) return;
  assert(hasExactFields(value, pageFields), `${label} page does not use the exact version-1 fields.`);
  assert(isNullableText(value.title, 160), `${label} page title is unsafe or malformed.`);
  assert(
    value.httpStatus === null ||
      (Number.isInteger(value.httpStatus) && value.httpStatus >= 100 && value.httpStatus <= 599),
    `${label} page status is malformed.`,
  );
  assert(value.title !== null || value.httpStatus !== null, `${label} contains an empty page object.`);
}

function verifyNetworkDetail(value, label) {
  if (value === null) return;
  assert(hasExactFields(value, networkFields), `${label} network does not use the exact version-1 fields.`);
  assert(
    value.ipAddress === null ||
      (typeof value.ipAddress === "string" &&
        value.ipAddress.length <= 80 &&
        (value.ipAddress.includes("[.]") || value.ipAddress.includes("[:]"))),
    `${label} network address is not defanged.`,
  );
  assert(
    value.asn === null || (Number.isInteger(value.asn) && value.asn >= 1 && value.asn <= 4_294_967_295),
    `${label} ASN is malformed.`,
  );
  assert(isNullableText(value.asnDescription, 160), `${label} ASN description is unsafe or malformed.`);
  assert(isNullableText(value.asnRegistry, 32), `${label} ASN registry is unsafe or malformed.`);
  assert(
    value.ipAddress !== null || value.asn !== null || value.asnDescription !== null || value.asnRegistry !== null,
    `${label} contains an empty network object.`,
  );
}

function verifyAssessmentDetail(value, label) {
  if (value === null) return;
  assert(hasExactFields(value, assessmentFields), `${label} assessment does not use the exact version-1 fields.`);
  assert(
    value.urlscanVerdictScore === null ||
      (Number.isInteger(value.urlscanVerdictScore) &&
        value.urlscanVerdictScore >= -100 &&
        value.urlscanVerdictScore <= 100),
    `${label} URLScan verdict score is malformed.`,
  );
  assert(
    Array.isArray(value.urlscanCategories) &&
      value.urlscanCategories.length <= 8 &&
      new Set(value.urlscanCategories).size === value.urlscanCategories.length &&
      value.urlscanCategories.every(
        (category) => typeof category === "string" && /^[a-z\d](?:[a-z\d-]{0,30}[a-z\d])?$/u.test(category),
      ),
    `${label} URLScan categories are malformed.`,
  );
  assert(
    value.redirectedToDomain === null ||
      (typeof value.redirectedToDomain === "string" &&
        value.redirectedToDomain.length <= 505 &&
        value.redirectedToDomain.includes("[.]") &&
        !/[@/?#:\\]/u.test(value.redirectedToDomain)),
    `${label} redirect destination is not a defanged domain.`,
  );
  assert(
    value.urlscanVerdictScore !== null ||
      value.urlscanCategories.length > 0 ||
      value.redirectedToDomain !== null,
    `${label} contains an empty assessment object.`,
  );
}

function verifyCertificateDetail(value, label) {
  if (value === null) return;
  assert(hasExactFields(value, certificateFields), `${label} certificate does not use the exact version-1 fields.`);
  assert(
    hasExactFields(value.fingerprints, fingerprintFields),
    `${label} certificate fingerprints do not use the exact version-1 fields.`,
  );
  assert(isNullableHex(value.fingerprints.md5, 32), `${label} certificate MD5 is malformed.`);
  assert(isNullableHex(value.fingerprints.sha1, 40), `${label} certificate SHA-1 is malformed.`);
  assert(isNullableHex(value.fingerprints.sha256, 64), `${label} certificate SHA-256 is malformed.`);
  assert(
    value.countryName === null || (typeof value.countryName === "string" && /^[A-Z]{2}$/u.test(value.countryName)),
    `${label} certificate country is malformed.`,
  );
  assert(isNullableText(value.issuer, 200), `${label} certificate issuer is unsafe or malformed.`);
  assert(
    value.commonName === null ||
      (typeof value.commonName === "string" &&
        value.commonName.length <= 509 &&
        !/[@/?#:\\]/u.test(value.commonName) &&
        value.commonName.includes("[.]")),
    `${label} certificate common name is not defanged.`,
  );
  const notBefore = value.notBefore === null ? null : timestampValue(value.notBefore);
  const notAfter = value.notAfter === null ? null : timestampValue(value.notAfter);
  assert(value.notBefore === null || notBefore !== null, `${label} certificate not-before timestamp is malformed.`);
  assert(value.notAfter === null || notAfter !== null, `${label} certificate not-after timestamp is malformed.`);
  assert(notBefore === null || notAfter === null || notBefore <= notAfter, `${label} certificate validity range is reversed.`);
  assert(
    Array.isArray(value.subjectAltNames) &&
      value.subjectAltNames.length <= 12 &&
      new Set(value.subjectAltNames).size === value.subjectAltNames.length &&
      value.subjectAltNames.every(
        (name) => typeof name === "string" && name.length <= 509 && !/[@/?#:\\]/u.test(name) && name.includes("[.]"),
      ),
    `${label} certificate subject alternative names are malformed.`,
  );
  assert(
    Number.isInteger(value.subjectAltNameCount) &&
      value.subjectAltNameCount >= value.subjectAltNames.length &&
      value.subjectAltNameCount <= 500,
    `${label} certificate subject alternative name count is malformed.`,
  );
  assert(
    value.serialNumberHex === null ||
      (typeof value.serialNumberHex === "string" &&
        value.serialNumberHex.length >= 1 &&
        value.serialNumberHex.length <= 80 &&
        lowerHex.test(value.serialNumberHex)),
    `${label} certificate serial number is malformed.`,
  );
  assert(
    value.countryName !== null ||
      value.issuer !== null ||
      value.commonName !== null ||
      value.notBefore !== null ||
      value.notAfter !== null ||
      value.subjectAltNameCount > 0 ||
      value.serialNumberHex !== null ||
      Object.values(value.fingerprints).some((fingerprint) => fingerprint !== null),
    `${label} contains an empty certificate object.`,
  );
}

function verifyObservation(value, signal, generatedAt, label) {
  assert(hasExactFields(value, observationFields), `${label} does not use the exact version-1 fields.`);
  assert(value.source === "URLScan" || value.source === "CertStream", `${label} source is unsupported.`);
  assert(signal.sources.includes(value.source), `${label} source is absent from its live signal.`);
  const observedAt = timestampValue(value.observedAt);
  assert(observedAt !== null && observedAt <= generatedAt + 5 * 60 * 1000, `${label} timestamp is malformed or in the future.`);
  verifyPageDetail(value.page, label);
  verifyNetworkDetail(value.network, label);
  verifyAssessmentDetail(value.assessment, label);
  verifyCertificateDetail(value.certificate, label);
  if (value.source === "CertStream") {
    assert(
      value.page === null && value.network === null && value.assessment === null && value.certificate !== null,
      `${label} exposes fields CertStream does not supply.`,
    );
  } else {
    assert(
      value.page !== null || value.network !== null || value.assessment !== null || value.certificate !== null,
      `${label} contains no URLScan evidence.`,
    );
  }
}

export function verifySignalDetails() {
  const snapshot = JSON.parse(readFileSync(join(output, "data", "radar.json"), "utf8"));
  assert(Array.isArray(snapshot.signals), "Built radar.json has no signal list for sidecar verification.");
  const signals = new Map();
  const expected = new Map();
  for (const signal of snapshot.signals) {
    assert(isRecord(signal) && signalIdentifier.test(signal.id), "Built radar.json contains an invalid signal identifier.");
    assert(!signals.has(signal.id), `Built radar.json contains duplicate signal ${signal.id}.`);
    signals.set(signal.id, signal);
    if (signal.detailAvailable === true) {
      expected.set(`data/signals/${signal.id.slice(0, 2)}/${signal.id}.json`, signal);
    }
  }

  const detailRoot = join(output, "data", "signals");
  const files = existsSync(detailRoot) ? walk(detailRoot) : [];
  let totalBytes = 0;
  for (const path of files) {
    const relativePath = relative(output, path).split(sep).join("/");
    assert(
      /^data\/signals\/[a-f\d]{2}\/[a-f\d]{20}\.json$/u.test(relativePath),
      `Unexpected file inside the signal-detail tree: ${relativePath}.`,
    );
    const signal = expected.get(relativePath);
    assert(signal, `${relativePath} is an orphan sidecar without detailAvailable=true.`);
    const byteLength = statSync(path).size;
    assert(byteLength > 0, `${relativePath} is empty.`);
    assert(byteLength <= signalDetailFileRawBytes, `${relativePath} is larger than 16 KiB.`);
    totalBytes += byteLength;
    assert(totalBytes <= signalDetailSetRawBytes, "Signal-detail sidecars exceed the 3 MiB aggregate budget.");

    let detail;
    try {
      detail = JSON.parse(readFileSync(path, "utf8"));
    } catch {
      throw new Error(`${relativePath} is not valid UTF-8 JSON.`);
    }
    assert(
      hasRequiredAndOptionalFields(detail, detailFields, ["domainContext", "contextChanges"]),
      `${relativePath} does not use the allowed version-1 top-level fields.`,
    );
    assert(detail.schemaVersion === 1 && detail.dataset === "signal-detail", `${relativePath} has the wrong schema identity.`);
    assert(detail.signalId === signal.id && detail.domain === signal.domain, `${relativePath} does not match its live signal.`);
    const generatedAt = timestampValue(detail.generatedAt);
    assert(generatedAt !== null, `${relativePath} has an invalid generatedAt timestamp.`);
    assert(
      Array.isArray(detail.observations) && detail.observations.length <= 2,
      `${relativePath} must contain at most two observations.`,
    );
    detail.observations.forEach((observation, index) =>
      verifyObservation(observation, signal, generatedAt, `${relativePath} observation ${index + 1}`),
    );
    assert(
      new Set(detail.observations.map((observation) => observation.source)).size === detail.observations.length,
      `${relativePath} contains duplicate observation sources.`,
    );
    if (Object.hasOwn(detail, "domainContext")) {
      verifyDomainContext(detail.domainContext, generatedAt, `${relativePath} domain context`);
    }
    if (Object.hasOwn(detail, "contextChanges")) {
      assert(
        Array.isArray(detail.contextChanges) && detail.contextChanges.length >= 1 && detail.contextChanges.length <= 6 &&
          new Set(detail.contextChanges.map((change) => change.eventId)).size === detail.contextChanges.length,
        `${relativePath} context-change list is malformed.`,
      );
      detail.contextChanges.forEach((change, index) => verifyContextChange(change, generatedAt, `${relativePath} context change ${index + 1}`));
    }
    assert(
      detail.observations.length > 0 || Object.hasOwn(detail, "domainContext") || Object.hasOwn(detail, "contextChanges"),
      `${relativePath} has neither a source observation nor passive context.`,
    );
    expected.delete(relativePath);
  }
  assert(expected.size === 0, `Missing signal-detail sidecars: ${[...expected.keys()].join(", ")}.`);
  return { files, totalBytes };
}

function assertPublicFeedUrl(value, label) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${label} is not an absolute URL.`);
  }
  assert(parsed.protocol === "https:" && parsed.origin === publicOrigin, `${label} leaves the canonical Radar origin.`);
  assert(!parsed.username && !parsed.password && !parsed.search && !parsed.hash, `${label} contains unsafe URL components.`);
  return parsed;
}

export function verifySyndicationFeeds() {
  const directory = JSON.parse(readFileSync(join(output, "data", "brand-feeds.json"), "utf8"));
  const registry = JSON.parse(readFileSync(join(root, "data", "brands-lt.json"), "utf8"));
  assert(directory?.dataset === "radar-brand-feeds" && Array.isArray(directory.brands), "Brand feed directory is malformed.");
  assert(directory.brands.length === registry.entries.length, "Brand feed directory does not cover every reviewed brand.");
  assert(new Set(directory.brands.map((entry) => entry.slug)).size === directory.brands.length, "Brand feed directory contains duplicate slugs.");

  const groups = [
    {
      label: "global",
      atom: "/data/events.atom.xml",
      rss: "/data/events.rss.xml",
      jsonFeed: "/data/events.feed.json",
    },
    ...directory.brands,
  ];
  for (const group of groups) {
    const label = `${group.label ?? group.brand} feed`;
    for (const [format, path] of Object.entries({ atom: group.atom, rss: group.rss, jsonFeed: group.jsonFeed })) {
      assert(typeof path === "string" && path.startsWith("/data/"), `${label} has an invalid ${format} path.`);
      assert(existsSync(outputPath(path)), `${label} ${format} file is missing.`);
      assert(existsSync(outputPath(`${path}.sha256`)), `${label} ${format} checksum is missing.`);
    }

    let atom = new JSDOM(readFileSync(outputPath(group.atom), "utf8"), { contentType: "text/xml" }).window.document;
    assert(!atom.querySelector("parsererror") && atom.documentElement.localName === "feed", `${label} Atom document is malformed.`);
    for (const link of atom.querySelectorAll("link[href]")) {
      assertPublicFeedUrl(link.getAttribute("href"), `${label} Atom link`);
    }
    releaseDocument(atom);
    atom = null;
    collectReleasedDocuments();

    let rss = new JSDOM(readFileSync(outputPath(group.rss), "utf8"), { contentType: "text/xml" }).window.document;
    assert(!rss.querySelector("parsererror") && rss.documentElement.localName === "rss", `${label} RSS document is malformed.`);
    for (const link of rss.querySelectorAll("channel > link, item > link")) {
      assertPublicFeedUrl(link.textContent?.trim(), `${label} RSS link`);
    }
    releaseDocument(rss);
    rss = null;
    collectReleasedDocuments();

    const jsonFeed = JSON.parse(readFileSync(outputPath(group.jsonFeed), "utf8"));
    assert(jsonFeed.version === "https://jsonfeed.org/version/1.1" && Array.isArray(jsonFeed.items), `${label} JSON Feed is malformed.`);
    assertPublicFeedUrl(jsonFeed.home_page_url, `${label} JSON Feed home_page_url`);
    assertPublicFeedUrl(jsonFeed.feed_url, `${label} JSON Feed feed_url`);
    for (const item of jsonFeed.items) assertPublicFeedUrl(item.url, `${label} JSON Feed item URL`);
  }

  // Pages serves XML without a CSP: only the global and per-brand feeds may be XML.
  const feedXml = new Set(groups.flatMap((group) => [group.atom, group.rss]));
  for (const path of feedXml) {
    assert(/^\/data\/(?:brands\/[a-z0-9-]+\/)?events\.(?:atom|rss)\.xml$/u.test(path), `Unexpected feed XML path ${path}.`);
  }
  for (const path of walk(join(output, "data"))) {
    const reference = `/${relative(output, path).split(sep).join("/")}`;
    assert(!reference.endsWith(".xml") || feedXml.has(reference), `Unexpected XML file in the published data: ${reference}.`);
  }
}

export function verifyPublishedDefanging() {
  const registry = JSON.parse(readFileSync(join(root, "data", "brands-lt.json"), "utf8"));
  const findings = findFangedStrings(join(output, "data"), {
    brandNames: registry.entries.map((entry) => entry.brand),
    officialDomains: registry.entries.flatMap((entry) => entry.officialDomains),
  });
  assert(
    findings.length === 0,
    `Published data contains ${findings.length} fanged hostname or URL string(s) outside the raw-field allowlist:\n${findings.slice(0, 20).join("\n")}`,
  );
}
