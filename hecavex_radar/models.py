from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict

SignalStatus = Literal["active", "suspected", "offline", "mitigated", "unknown"]
SourceState = Literal["healthy", "partial", "skipped"]
BrandEvidence = Literal["domain", "title", "verdict", "primary-html-sha256"]
EvidenceTier = Literal["name-only", "corroborated", "reviewed"]
ReviewState = Literal[
    "unreviewed",
    "needs-review",
    "confirmed-suspicious",
    "false-positive",
    "benign-brand-reference",
    "inconclusive",
]
LithuanianRelevance = Literal[
    "lithuanian-targeting",
    "lithuanian-brand-relevance",
    "global-brand-reference",
    "unknown",
]
DiscoveryMethod = Literal[
    "certstream-live",
    "ct-search-api",
    "ct-log-poll",
    "urlscan-public-report",
    "hecavex-public-export",
    "hecavex-review",
]
CorroborationMethod = Literal[
    "urlscan-public-report",
    "urlscan-page-title",
    "urlscan-provider-verdict",
    "urlscan-primary-html-sha256",
    "analyst-review",
]
ReasonCode = Literal[
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
]


class SourceTimeEvidence(TypedDict):
    timestamp: str
    providerObservedAt: str | None
    originalProviderTime: str | None
    originalProviderTimeTruncated: bool
    originalProviderTimeSha256: str | None
    collectorTime: str | None
    source: str
    boundary: str
    reason: str | None
    origin: str


@dataclass(slots=True)
class RawSignal:
    url: str
    source: str
    first_seen: str | None = None
    last_seen: str | None = None
    status: str | None = None
    brand: str | None = None
    country: str | None = None
    host: str | None = None
    screenshot_url: str | None = None
    reference_url: str | None = None
    hashes: list[str] | None = None
    confidence: float | None = None
    reason_codes: Sequence[str] | None = None
    discovered_via: Sequence[str] | None = None
    corroborated_by: Sequence[str] | None = None
    # Internal capture evidence; never serialized in snapshot v2.
    source_time_evidence: list[SourceTimeEvidence] | None = None


class RadarSource(TypedDict):
    name: str
    homepage: str
    fetchedAt: str | None
    records: int
    state: SourceState
    note: str | None


class RadarSignal(TypedDict):
    id: str
    url: str
    domain: str
    firstSeen: str
    lastSeen: str
    sources: list[str]
    status: SignalStatus
    brand: str | None
    country: str | None
    host: str | None
    screenshotUrl: str | None
    referenceUrl: NotRequired[str | None]
    hashes: NotRequired[list[str]]
    brandEvidence: NotRequired[list[BrandEvidence]]
    reasonCodes: NotRequired[list[ReasonCode]]
    discoveredVia: NotRequired[list[DiscoveryMethod]]
    corroboratedBy: NotRequired[list[CorroborationMethod]]
    detailAvailable: NotRequired[Literal[True]]
    matchScore: int
    evidenceTier: EvidenceTier
    reviewState: ReviewState
    ltRelevance: LithuanianRelevance
    # Deprecated compatibility alias. New consumers must use matchScore.
    confidence: int


@dataclass(slots=True)
class SourceResult:
    source: RadarSource
    signals: list[RawSignal]
    intelligence: list[RawDomainIntelligence] = field(default_factory=list)


@dataclass(slots=True)
class RawDomainIntelligence:
    """Untrusted source metadata awaiting the public sidecar boundary."""

    domain: str
    source: str
    observed_at: str | None = None
    page: dict[str, object] | None = None
    network: dict[str, object] | None = None
    assessment: dict[str, object] | None = None
    certificate: dict[str, object] | None = None


class PageDetail(TypedDict):
    title: str | None
    httpStatus: int | None


class NetworkDetail(TypedDict):
    ipAddress: str | None
    asn: int | None
    asnDescription: str | None
    asnRegistry: str | None


class AssessmentDetail(TypedDict):
    urlscanVerdictScore: int | None
    urlscanCategories: list[str]
    redirectedToDomain: str | None


class CertificateFingerprints(TypedDict):
    md5: str | None
    sha1: str | None
    sha256: str | None


class CertificateDetail(TypedDict):
    countryName: str | None
    issuer: str | None
    commonName: str | None
    notBefore: str | None
    notAfter: str | None
    subjectAltNames: list[str]
    subjectAltNameCount: int
    serialNumberHex: str | None
    fingerprints: CertificateFingerprints


class SignalObservation(TypedDict):
    source: Literal["CertStream", "URLScan"]
    observedAt: str
    page: PageDetail | None
    network: NetworkDetail | None
    assessment: AssessmentDetail | None
    certificate: CertificateDetail | None


class SignalDnsContext(TypedDict):
    a: list[str]
    aaaa: list[str]
    cname: list[str]
    ns: list[str]
    mx: list[str]
    minimumTtl: int | None
    queriesCompleted: int


class SignalRegistrationContext(TypedDict):
    domain: NotRequired[str]
    registrar: str | None
    registeredAt: str | None
    updatedAt: str | None
    expiresAt: str | None
    statuses: list[str]


class SignalDomainContext(TypedDict):
    observedAt: str
    dns: SignalDnsContext
    registration: SignalRegistrationContext | None


class SignalDomainContextRecord(SignalDomainContext):
    signalId: str
    domain: str


class SignalContextChangeSource(TypedDict):
    name: Literal["Cloudflare DNS", "RDAP", "URLScan"]
    observedAt: str
    referenceUrl: str


class SignalContextChangeEvidence(TypedDict):
    previousSha256: str
    currentSha256: str
    primaryHtmlSha256: list[str]
    certificateSha256: str | None


class SignalContextChange(TypedDict):
    eventId: str
    observedAt: str
    component: Literal["dns", "rdap", "urlscan"]
    changeType: Literal[
        "first-resolving",
        "stopped-resolving",
        "dns-a-changed",
        "dns-aaaa-changed",
        "dns-cname-changed",
        "dns-ns-changed",
        "dns-mx-changed",
        "rdap-registrar-changed",
        "rdap-status-changed",
        "rdap-expiry-changed",
        "urlscan-title-changed",
        "urlscan-redirect-changed",
        "urlscan-http-status-changed",
        "urlscan-ip-changed",
        "urlscan-asn-changed",
        "urlscan-primary-html-sha256-changed",
        "urlscan-certificate-fingerprint-changed",
        "certificate-reissued",
    ]
    changedFields: list[str]
    source: SignalContextChangeSource
    evidence: SignalContextChangeEvidence


class SignalDetail(TypedDict):
    schemaVersion: Literal[1]
    dataset: Literal["signal-detail"]
    signalId: str
    domain: str
    generatedAt: str
    observations: list[SignalObservation]
    domainContext: NotRequired[SignalDomainContext]
    contextChanges: NotRequired[list[SignalContextChange]]


@dataclass(frozen=True, slots=True)
class SafeUrl:
    key: str
    display_url: str
    display_domain: str


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    domain: str
    registrable_domain: str
    brand: str
    confidence: int
    reasons: list[str]


class CertStreamCandidate(TypedDict):
    schemaVersion: Literal[1]
    id: str
    observedAt: str
    indicatorType: Literal["domain"]
    domain: str
    registrableDomain: str
    source: Literal["CertStream"]
    brand: str
    confidence: int
    reasons: list[str]
    collectionMethod: NotRequired[Literal["certstream-live", "ct-search-api", "ct-log-poll"]]
    certificate: NotRequired[CertificateDetail]
    sourceTimeEvidence: NotRequired[list[SourceTimeEvidence]]
