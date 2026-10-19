export const SIGNAL_STATUSES = [
  "active",
  "suspected",
  "offline",
  "mitigated",
  "unknown",
] as const;

export type SignalStatus = (typeof SIGNAL_STATUSES)[number];

export const REASON_CODES = [
  "brand-domain-match",
  "brand-title-match",
  "provider-verdict",
  "primary-html-hash-pivot",
  "brand-exact-token",
  "brand-joined-affix",
  "brand-split-token",
  "brand-lookalike-edit",
  "suspicious-context",
  "punycode",
  "different-tld",
  "multiple-hyphens",
  "unicode-confusable",
  "mixed-script",
  "restricted-identifier",
  "hecavex-public-export",
  "manual-review",
  "first-publication",
  "source-status-change",
] as const;

export type ReasonCode = (typeof REASON_CODES)[number];

export const EVIDENCE_TIERS = ["name-only", "corroborated", "reviewed"] as const;
export type EvidenceTier = (typeof EVIDENCE_TIERS)[number];

export const REVIEW_STATES = [
  "unreviewed",
  "needs-review",
  "confirmed-suspicious",
  "false-positive",
  "benign-brand-reference",
  "inconclusive",
] as const;
export type ReviewState = (typeof REVIEW_STATES)[number];

export const LT_RELEVANCE_VALUES = [
  "lithuanian-targeting",
  "lithuanian-brand-relevance",
  "global-brand-reference",
  "unknown",
] as const;
export type LithuanianRelevance = (typeof LT_RELEVANCE_VALUES)[number];

export const DISCOVERY_METHODS = [
  "certstream-live",
  "ct-search-api",
  "ct-log-poll",
  "urlscan-public-report",
  "hecavex-public-export",
  "hecavex-review",
] as const;
export type DiscoveryMethod = (typeof DISCOVERY_METHODS)[number];

export const CORROBORATION_METHODS = [
  "urlscan-public-report",
  "urlscan-page-title",
  "urlscan-provider-verdict",
  "urlscan-primary-html-sha256",
  "analyst-review",
] as const;
export type CorroborationMethod = (typeof CORROBORATION_METHODS)[number];

export const BRAND_EVIDENCE_VALUES = ["domain", "title", "verdict", "primary-html-sha256"] as const;
export type BrandEvidence = (typeof BRAND_EVIDENCE_VALUES)[number];

export type RadarSignal = {
  id: string;
  url: string;
  domain: string;
  firstSeen: string;
  lastSeen: string;
  sources: string[];
  status: SignalStatus;
  brand: string | null;
  country: string | null;
  host: string | null;
  screenshotUrl: string | null;
  referenceUrl?: string | null;
  hashes?: string[];
  brandEvidence?: BrandEvidence[];
  reasonCodes?: ReasonCode[];
  detailAvailable?: true;
  /** Legacy name retained while the public contract migrates to matchScore. */
  confidence?: number;
  matchScore?: number;
  evidenceTier?: EvidenceTier;
  reviewState?: ReviewState;
  ltRelevance?: LithuanianRelevance;
  discoveredVia?: DiscoveryMethod[];
  corroboratedBy?: CorroborationMethod[];
};

export type SignalDetailSource = "URLScan" | "CertStream";

export type SignalPageDetail = {
  title: string | null;
  httpStatus: number | null;
};

export type SignalNetworkDetail = {
  ipAddress: string | null;
  asn: number | null;
  asnDescription: string | null;
  asnRegistry: string | null;
};

export type SignalAssessmentDetail = {
  urlscanVerdictScore: number | null;
  urlscanCategories: string[];
  redirectedToDomain: string | null;
};

export type SignalCertificateFingerprints = {
  md5: string | null;
  sha1: string | null;
  sha256: string | null;
};

export type SignalCertificateDetail = {
  countryName: string | null;
  issuer: string | null;
  commonName: string | null;
  notBefore: string | null;
  notAfter: string | null;
  subjectAltNames: string[];
  subjectAltNameCount: number;
  serialNumberHex: string | null;
  fingerprints: SignalCertificateFingerprints;
};

export type SignalDetailObservation = {
  source: SignalDetailSource;
  observedAt: string;
  page: SignalPageDetail | null;
  network: SignalNetworkDetail | null;
  assessment: SignalAssessmentDetail | null;
  certificate: SignalCertificateDetail | null;
};

export type SignalDnsContext = {
  a: string[];
  aaaa: string[];
  cname: string[];
  ns: string[];
  mx: string[];
  minimumTtl: number | null;
  queriesCompleted: number;
};

export type SignalRegistrationContext = {
  domain?: string;
  registrar: string | null;
  registeredAt: string | null;
  updatedAt: string | null;
  expiresAt: string | null;
  statuses: string[];
};

export type SignalDomainContext = {
  observedAt: string;
  dns: SignalDnsContext;
  registration: SignalRegistrationContext | null;
};

export type SignalContextChange = {
  eventId: string;
  observedAt: string;
  component: "dns" | "rdap" | "urlscan";
  changeType:
    | "first-resolving"
    | "stopped-resolving"
    | "dns-a-changed"
    | "dns-aaaa-changed"
    | "dns-cname-changed"
    | "dns-ns-changed"
    | "dns-mx-changed"
    | "rdap-registrar-changed"
    | "rdap-status-changed"
    | "rdap-expiry-changed"
    | "urlscan-title-changed"
    | "urlscan-redirect-changed"
    | "urlscan-http-status-changed"
    | "urlscan-ip-changed"
    | "urlscan-asn-changed"
    | "urlscan-primary-html-sha256-changed"
    | "urlscan-certificate-fingerprint-changed"
    | "certificate-reissued";
  changedFields: string[];
  source: {
    name: "Cloudflare DNS" | "RDAP" | "URLScan";
    observedAt: string;
    referenceUrl: string;
  };
  evidence: {
    previousSha256: string;
    currentSha256: string;
    primaryHtmlSha256: string[];
    certificateSha256: string | null;
  };
};

export type SignalDetail = {
  schemaVersion: 1;
  dataset: "signal-detail";
  signalId: string;
  domain: string;
  generatedAt: string;
  observations: SignalDetailObservation[];
  domainContext?: SignalDomainContext;
  contextChanges?: SignalContextChange[];
};

export type SourceState = "healthy" | "partial" | "skipped";

export type RadarSource = {
  name: string;
  homepage: string;
  fetchedAt: string | null;
  records: number;
  state: SourceState;
  note: string | null;
};

export type RadarSnapshot = {
  schemaVersion: 1 | 2;
  dataset: "live";
  generatedAt: string;
  lastSuccessfulSyncAt: string;
  signals: RadarSignal[];
  sources: RadarSource[];
};

export type Filters = {
  query: string;
  status: SignalStatus | "all";
  source: string;
  brand: string;
  country: string;
  minimumMatchScore: number;
  timeRange: "all" | "24h" | "3d" | "7d";
  evidence: "all" | "name-only" | "corroborated" | "reviewed" | "screenshot" | "urlscan" | "hashes" | "certstream-only";
  sort: "last-seen-desc" | "first-seen-desc" | "match-score-desc" | "brand-asc";
};

export type HistoryTransition = {
  eventId: string;
  observedAt: string;
  previousStatus: SignalStatus | null;
  status: SignalStatus;
  sources: string[];
  reasonCodes: ReasonCode[];
};

export type RadarHistorySignal = {
  id: string;
  domain: string;
  brand: string;
  firstSeen: string;
  lastSeen: string;
  observationCount: number;
  sources: string[];
  latestStatus: SignalStatus;
  reasonCodes: ReasonCode[];
  statusTransitions: HistoryTransition[];
};

export type RadarHistory = {
  schemaVersion: 1;
  dataset: "history";
  generatedAt: string;
  detailRetentionDays: number;
  summaryRetentionDays: number;
  signals: RadarHistorySignal[];
};
