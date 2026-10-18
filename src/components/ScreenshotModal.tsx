import { ArrowRight, Check, Copy, ExternalLink, Flag, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { formatDateTime } from "../lib/format.ts";
import { evidenceTierLabel, explainReasons, signalEvidenceTier, signalMatchScore } from "../lib/dashboard.ts";
import { loadSignalDetail } from "../lib/signalDetail.ts";
import { signalPath } from "../lib/signalRoutes.ts";
import type { RadarSignal, SignalCertificateDetail, SignalContextChange, SignalDetail, SignalDetailObservation, SignalDomainContext } from "../types.ts";
import { formatDateTimeLt } from "../lt/formatLt.ts";
import type { SiteLanguage } from "./SiteHeader.tsx";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

interface IsolatedElement {
  element: HTMLElement;
  inert: string | null;
  ariaHidden: string | null;
}

function focusableElements(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => element.tabIndex >= 0 && !element.closest("[hidden], [inert], [aria-hidden='true']"),
  );
}

function isolateBackground(modalBackdrop: HTMLElement) {
  const isolated: IsolatedElement[] = [];
  let branch = modalBackdrop;

  while (branch.parentElement) {
    const parent = branch.parentElement;
    for (const sibling of Array.from(parent.children)) {
      if (sibling === branch || !(sibling instanceof HTMLElement)) continue;
      isolated.push({
        element: sibling,
        inert: sibling.getAttribute("inert"),
        ariaHidden: sibling.getAttribute("aria-hidden"),
      });
      sibling.setAttribute("inert", "");
      sibling.setAttribute("aria-hidden", "true");
    }

    if (parent === document.body) break;
    branch = parent;
  }

  return () => {
    for (const { element, inert, ariaHidden } of isolated.reverse()) {
      if (inert === null) element.removeAttribute("inert");
      else element.setAttribute("inert", inert);

      if (ariaHidden === null) element.removeAttribute("aria-hidden");
      else element.setAttribute("aria-hidden", ariaHidden);
    }
  };
}

interface ScreenshotModalProps {
  signal: RadarSignal;
  snapshotGeneratedAt: string;
  returnFocus: HTMLElement;
  onClose: () => void;
  language?: SiteLanguage;
}

type DetailLoadState =
  | { status: "idle" | "loading" }
  | { status: "ready"; detail: SignalDetail }
  | { status: "error" };

const modalCopy = {
  en: {
    copied: "Copied",
    copiedLabel: (label: string) => `${label} copied`,
    copyLabel: (label: string, value: string) => `Copy ${label} ${value}`,
    tlsCertificate: "TLS certificate",
    issuer: "Issuer",
    declaredCountry: "Declared country",
    commonName: "Common name",
    certificateCommonName: "certificate common name",
    serialNumber: "Serial number",
    certificateSerialNumber: "certificate serial number",
    validFrom: "Valid from",
    validUntil: "Valid until",
    relatedCertificateNames: "Related certificate names",
    certificateDnsName: "certificate DNS name",
    showingCertificateNames: (shown: number, total: number) => `Showing ${shown} of ${total} related certificate names.`,
    certificateFingerprints: "Certificate fingerprints",
    fingerprintNote: "MD5 and SHA-1 values are legacy identifiers for pivots, not proof of certificate security.",
    certificateFingerprint: (algorithm: string) => `${algorithm} certificate fingerprint`,
    observedAt: (timestamp: string) => `Observed ${timestamp}`,
    observedPage: "Observed page",
    pageTitle: "Page title",
    pageHttpStatus: "Page HTTP status",
    observedNetwork: "Observed network",
    ipAddress: "IP address",
    defangedIpAddress: "defanged IP address",
    autonomousSystem: "Autonomous system",
    asDescription: "AS description",
    asRegistry: "AS registry",
    urlscanAssessment: "URLScan assessment",
    urlscanVerdictScore: "URLScan verdict score",
    scoreScale: " / -100 to 100",
    reportedCategories: "Reported categories",
    observedRedirectDestination: "Observed redirect destination",
    defangedRedirectDestination: "defanged redirect destination",
    providerAssessmentNote: "Provider assessment is separate from the Radar match score. A redirect is observed behavior, not a benign verdict; destination and content can vary by visitor, time, or cloaking rules.",
    boundedContextObserved: (timestamp: string) => `Bounded context observed ${timestamp}`,
    dnsContext: "DNS context",
    dnsRecordsObserved: "DNS records observed",
    queriesCompleted: "Queries completed",
    minimumTtl: "Minimum TTL",
    seconds: (value: number) => `${value} seconds`,
    dnsRecord: (recordType: string) => `${recordType} record`,
    noDnsRecords: "No answer records were retained. Missing data is unknown.",
    registrationContext: "Registration context",
    registeredDomain: "Registered domain",
    registeredDomainCopy: "registered domain",
    registrar: "Registrar",
    registered: "Registered",
    updated: "Updated",
    expires: "Expires",
    statuses: "Statuses",
    noRegistration: "No registration record was retained. Missing RDAP context is unknown.",
    dnsRegistrationBoundary: "DNS and registration values are point-in-time context, not ownership or maliciousness evidence.",
    passiveEvidence: "Passive evidence",
    closeDetails: "Close signal details",
    whyIncluded: "Why Radar included this",
    automatedExplanation: "Automated candidate explanation",
    candidateEvidenceState: "Candidate evidence state",
    matchScore: (score: number) => `Match score ${score}/100`,
    noReason: "No granular public reason was retained for this candidate.",
    signalId: "Signal ID",
    signalIdCopy: "signal ID",
    potentialBrand: "Potential brand match",
    unclassified: "Unclassified",
    sourceState: "Source-reported state",
    sources: "Sources",
    discoveredVia: "Discovered via",
    corroboratedBy: "Corroborated by",
    firstSeen: "First seen",
    lastSeen: "Last seen",
    snapshotGenerated: "Snapshot generated",
    lithuanianRelevance: "Lithuanian relevance",
    scoreBoundary: "The match score ranks rule strength. It is not a probability, maliciousness verdict, or block recommendation.",
    domainIntelligence: "Domain intelligence",
    passiveContext: "Passive context",
    loadingContext: "Loading bounded public metadata from Radar's static archive.",
    contextUnavailable: "Domain intelligence is temporarily unavailable. The core signal and any archived evidence remain below.",
    tryAgain: "Try again",
    noDomainContext: "No bounded DNS/RDAP context is published for this candidate. Missing context is unknown.",
    screenshotAlt: (domain: string) => `Archived screenshot for ${domain}`,
    noScreenshot: "No archived screenshot is available for this observation.",
    observedHashes: "Observed SHA-256 hashes",
    hashesNote: "Primary HTML response evidence supplied with this observation; hashes are safe to copy for defensive pivots.",
    reasonCodes: "Publication reason codes",
    reasonCodesNote: "Controlled public provenance labels explain why this candidate passed validation; they are not verdicts.",
    externalBoundary: "Viewing a screenshot or report contacts urlscan.io. The suspicious website is not contacted.",
    openPermanentRecord: "Open permanent record",
    requestCorrection: "Request correction",
    openImage: "Open image",
    openReport: "Open report",
    correctionSubject: (id: string) => `HECAVEX Radar correction ${id}`,
    correctionBody: (signal: RadarSignal, snapshot: string) => [
      `Signal ID: ${signal.id}`,
      `Defanged indicator: ${signal.url}`,
      `Snapshot: ${snapshot}`,
    ].join("\n"),
  },
  lt: {
    copied: "Nukopijuota",
    copiedLabel: (label: string) => `${label}: nukopijuota`,
    copyLabel: (label: string, value: string) => `Kopijuoti: ${label}, ${value}`,
    tlsCertificate: "TLS sertifikatas",
    issuer: "Išdavėjas",
    declaredCountry: "Deklaruota šalis",
    commonName: "Bendrasis vardas",
    certificateCommonName: "sertifikato bendrasis vardas",
    serialNumber: "Serijos numeris",
    certificateSerialNumber: "sertifikato serijos numeris",
    validFrom: "Galioja nuo",
    validUntil: "Galioja iki",
    relatedCertificateNames: "Susiję sertifikato vardai",
    certificateDnsName: "sertifikato DNS vardas",
    showingCertificateNames: (shown: number, total: number) => `Rodomi ${shown} iš ${total} susijusių sertifikato vardų.`,
    certificateFingerprints: "Sertifikato kontrolinės sumos",
    fingerprintNote: "MD5 ir SHA-1 reikšmės yra pasenę pivotų identifikatoriai, o ne sertifikato saugumo įrodymas.",
    certificateFingerprint: (algorithm: string) => `${algorithm} sertifikato kontrolinė suma`,
    observedAt: (timestamp: string) => `Stebėta ${timestamp}`,
    observedPage: "Stebėtas puslapis",
    pageTitle: "Puslapio pavadinimas",
    pageHttpStatus: "Puslapio HTTP būsena",
    observedNetwork: "Stebėtas tinklas",
    ipAddress: "IP adresas",
    defangedIpAddress: "neutralizuotas IP adresas",
    autonomousSystem: "Autonominė sistema",
    asDescription: "AS aprašymas",
    asRegistry: "AS registras",
    urlscanAssessment: "URLScan vertinimas",
    urlscanVerdictScore: "URLScan verdikto balas",
    scoreScale: " / nuo -100 iki 100",
    reportedCategories: "Nurodytos kategorijos",
    observedRedirectDestination: "Stebėta peradresavimo paskirties vieta",
    defangedRedirectDestination: "neutralizuota peradresavimo paskirties vieta",
    providerAssessmentNote: "Paslaugos teikėjo vertinimas nėra Radaro atitikimo balas. Peradresavimas yra stebėtas elgesys, o ne saugumo patvirtinimas; paskirties vieta ir turinys gali kisti pagal lankytoją, laiką ar maskavimo taisykles.",
    boundedContextObserved: (timestamp: string) => `Ribotas kontekstas stebėtas ${timestamp}`,
    dnsContext: "DNS kontekstas",
    dnsRecordsObserved: "Stebėti DNS įrašai",
    queriesCompleted: "Atlikta užklausų",
    minimumTtl: "Mažiausias TTL",
    seconds: (value: number) => `${value} sek.`,
    dnsRecord: (recordType: string) => `${recordType} įrašas`,
    noDnsRecords: "Atsakymo įrašų neišsaugota. Trūkstami duomenys lieka nežinomi.",
    registrationContext: "Registracijos kontekstas",
    registeredDomain: "Registruotas domenas",
    registeredDomainCopy: "registruotas domenas",
    registrar: "Registratorius",
    registered: "Užregistruota",
    updated: "Atnaujinta",
    expires: "Galioja iki",
    statuses: "Būsenos",
    noRegistration: "Registracijos įrašas neišsaugotas. Trūkstamas RDAP kontekstas lieka nežinomas.",
    dnsRegistrationBoundary: "DNS ir registracijos reikšmės yra konkretaus laiko kontekstas, o ne nuosavybės ar kenkėjiškumo įrodymas.",
    passiveEvidence: "Pasyvūs įrodymai",
    closeDetails: "Užverti signalo informaciją",
    whyIncluded: "Kodėl Radaras įtraukė šį kandidatą",
    automatedExplanation: "Automatinis kandidato paaiškinimas",
    candidateEvidenceState: "Kandidato įrodymų būsena",
    matchScore: (score: number) => `Atitikimo balas ${score}/100`,
    noReason: "Išsami vieša šio kandidato įtraukimo priežastis neišsaugota.",
    signalId: "Signalo ID",
    signalIdCopy: "signalo ID",
    potentialBrand: "Galimas prekės ženklas",
    unclassified: "Neklasifikuota",
    sourceState: "Šaltinio nurodyta būsena",
    sources: "Šaltiniai",
    discoveredVia: "Aptikta per",
    corroboratedBy: "Patvirtinta per",
    firstSeen: "Pirmą kartą stebėta",
    lastSeen: "Paskutinį kartą stebėta",
    snapshotGenerated: "Suvestinė sukurta",
    lithuanianRelevance: "Aktualumas Lietuvai",
    scoreBoundary: "Atitikimo balas rikiuoja taisyklių stiprumą. Tai nėra tikimybė, kenkėjiškumo verdiktas ar blokavimo rekomendacija.",
    domainIntelligence: "Domeno žvalgybos duomenys",
    passiveContext: "Pasyvus kontekstas",
    loadingContext: "Kraunami riboti vieši metaduomenys iš statinio Radaro archyvo.",
    contextUnavailable: "Domeno žvalgybos duomenys laikinai nepasiekiami. Pagrindinis signalas ir išsaugoti įrodymai lieka pateikti žemiau.",
    tryAgain: "Bandyti dar kartą",
    noDomainContext: "Šiam kandidatui nepaskelbtas ribotas DNS/RDAP kontekstas. Trūkstami duomenys lieka nežinomi.",
    screenshotAlt: (domain: string) => `Išsaugota ${domain} ekrano kopija`,
    noScreenshot: "Šiam stebėjimui išsaugotos ekrano kopijos nėra.",
    observedHashes: "Stebėtos SHA-256 maišos",
    hashesNote: "Su šiuo stebėjimu pateikti pirminio HTML atsako įrodymai; maišų reikšmes saugu kopijuoti gynybiniams pivotams.",
    reasonCodes: "Paskelbimo priežasčių kodai",
    reasonCodesNote: "Kontroliuojamos viešos kilmės žymos paaiškina, kodėl kandidatas praėjo patikrą; jos nėra verdiktai.",
    externalBoundary: "Atidarius ekrano kopiją ar ataskaitą susisiekiama su urlscan.io. Su įtartina svetaine ryšys neužmezgamas.",
    openPermanentRecord: "Atverti nuolatinį įrašą",
    requestCorrection: "Pranešti apie klaidą",
    openImage: "Atverti vaizdą",
    openReport: "Atverti ataskaitą",
    correctionSubject: (id: string) => `HECAVEX Radaro pataisymas ${id}`,
    correctionBody: (signal: RadarSignal, snapshot: string) => [
      `Signalo ID: ${signal.id}`,
      `Neutralizuotas indikatorius: ${signal.url}`,
      `Suvestinė: ${snapshot}`,
    ].join("\n"),
  },
} as const;

const statusLabels: Record<SiteLanguage, Record<RadarSignal["status"], string>> = {
  en: { active: "active", suspected: "suspected", offline: "offline", mitigated: "mitigated", unknown: "unknown" },
  lt: { active: "aktyvus", suspected: "įtariamas", offline: "nepasiekiamas", mitigated: "suvaldytas", unknown: "nežinomas" },
};

const reviewStateLabels: Record<SiteLanguage, Record<NonNullable<RadarSignal["reviewState"]>, string>> = {
  en: {
    unreviewed: "unreviewed",
    "needs-review": "needs review",
    "confirmed-suspicious": "confirmed suspicious",
    "false-positive": "false positive",
    "benign-brand-reference": "benign brand reference",
    inconclusive: "inconclusive",
  },
  lt: {
    unreviewed: "neperžiūrėta",
    "needs-review": "reikia peržiūros",
    "confirmed-suspicious": "patvirtinta kaip įtartina",
    "false-positive": "klaidingas teigiamas rezultatas",
    "benign-brand-reference": "teisėta prekės ženklo nuoroda",
    inconclusive: "nepakanka duomenų",
  },
};

const relevanceLabels: Record<SiteLanguage, Record<NonNullable<RadarSignal["ltRelevance"]>, string>> = {
  en: {
    "lithuanian-targeting": "Lithuanian targeting",
    "lithuanian-brand-relevance": "Brand is in Radar's reviewed Lithuanian scope",
    "global-brand-reference": "Global brand reference",
    unknown: "Unknown",
  },
  lt: {
    "lithuanian-targeting": "Taikymasis į Lietuvą",
    "lithuanian-brand-relevance": "Prekės ženklas yra peržiūrėtoje Lietuvos apimtyje",
    "global-brand-reference": "Pasaulinio prekės ženklo paminėjimas",
    unknown: "Nežinoma",
  },
};

function localizedTimestamp(value: string, language: SiteLanguage): string {
  return language === "lt" ? `${formatDateTimeLt(value)} Lietuvos laiku` : `${formatDateTime(value)} UTC`;
}

export function DetailItem({ label, children, fullRow = false }: { label: string; children: ReactNode; fullRow?: boolean }) {
  return (
    <div className={fullRow ? "candidate-provenance-full" : undefined}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function CopyableValue({ value, label, language = "en" }: { value: string; label: string; language?: SiteLanguage }) {
  const [copied, setCopied] = useState(false);
  const copyText = modalCopy[language];

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  return (
    <span className="detail-copyable">
      <code>{value}</code>
      <button
        type="button"
        onClick={() => void copy()}
        aria-label={copied ? copyText.copiedLabel(label) : copyText.copyLabel(label, value)}
      >
        {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      </button>
      <span className="sr-only" aria-live="polite">{copied ? copyText.copied : ""}</span>
    </span>
  );
}

function CertificateDetail({ certificate, language }: { certificate: SignalCertificateDetail; language: SiteLanguage }) {
  const copy = modalCopy[language];
  const fingerprints = [
    ["MD5", certificate.fingerprints.md5],
    ["SHA-1", certificate.fingerprints.sha1],
    ["SHA-256", certificate.fingerprints.sha256],
  ] as const;
  const hasFingerprints = fingerprints.some(([, digest]) => digest !== null);

  return (
    <section className="detail-group" aria-label={copy.tlsCertificate}>
      <h5>{copy.tlsCertificate}</h5>
      <dl className="detail-grid">
        {certificate.issuer ? <DetailItem label={copy.issuer}><span>{certificate.issuer}</span></DetailItem> : null}
        {certificate.countryName ? <DetailItem label={copy.declaredCountry}><span>{certificate.countryName}</span></DetailItem> : null}
        {certificate.commonName ? (
          <DetailItem label={copy.commonName}><CopyableValue value={certificate.commonName} label={copy.certificateCommonName} language={language} /></DetailItem>
        ) : null}
        {certificate.serialNumberHex ? (
          <DetailItem label={copy.serialNumber}><CopyableValue value={certificate.serialNumberHex} label={copy.certificateSerialNumber} language={language} /></DetailItem>
        ) : null}
        {certificate.notBefore ? (
          <DetailItem label={copy.validFrom}><time dateTime={certificate.notBefore}>{localizedTimestamp(certificate.notBefore, language)}</time></DetailItem>
        ) : null}
        {certificate.notAfter ? (
          <DetailItem label={copy.validUntil}><time dateTime={certificate.notAfter}>{localizedTimestamp(certificate.notAfter, language)}</time></DetailItem>
        ) : null}
      </dl>
      {certificate.subjectAltNames.length > 0 ? (
        <div className="detail-list">
          <h6>{copy.relatedCertificateNames}</h6>
          <ul>
            {certificate.subjectAltNames.map((name) => (
              <li key={name}><CopyableValue value={name} label={copy.certificateDnsName} language={language} /></li>
            ))}
          </ul>
          {certificate.subjectAltNameCount > certificate.subjectAltNames.length ? (
            <p>{copy.showingCertificateNames(certificate.subjectAltNames.length, certificate.subjectAltNameCount)}</p>
          ) : null}
        </div>
      ) : null}
      {hasFingerprints ? (
        <div className="detail-list">
          <h6>{copy.certificateFingerprints}</h6>
          <p>{copy.fingerprintNote}</p>
          <ul>
            {fingerprints.map(([algorithm, digest]) => digest ? (
              <li key={algorithm}>
                <span>{algorithm}</span>
                <CopyableValue value={digest} label={copy.certificateFingerprint(algorithm)} language={language} />
              </li>
            ) : null)}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

export function ObservationDetail({ observation, language = "en" }: { observation: SignalDetailObservation; language?: SiteLanguage }) {
  const copy = modalCopy[language];
  return (
    <article className="detail-observation">
      <header>
        <div>
          <span className="source-chip">{observation.source}</span>
          <h4>{copy.observedAt(localizedTimestamp(observation.observedAt, language))}</h4>
        </div>
      </header>
      {observation.page ? (
        <section className="detail-group" aria-label={copy.observedPage}>
          <h5>{copy.observedPage}</h5>
          <dl className="detail-grid">
            {observation.page.title ? <DetailItem label={copy.pageTitle}><span>{observation.page.title}</span></DetailItem> : null}
            {observation.page.httpStatus !== null ? (
              <DetailItem label={copy.pageHttpStatus}><code>{observation.page.httpStatus}</code></DetailItem>
            ) : null}
          </dl>
        </section>
      ) : null}
      {observation.network ? (
        <section className="detail-group" aria-label={copy.observedNetwork}>
          <h5>{copy.observedNetwork}</h5>
          <dl className="detail-grid">
            {observation.network.ipAddress ? (
              <DetailItem label={copy.ipAddress}><CopyableValue value={observation.network.ipAddress} label={copy.defangedIpAddress} language={language} /></DetailItem>
            ) : null}
            {observation.network.asn !== null ? (
              <DetailItem label={copy.autonomousSystem}><CopyableValue value={`AS${observation.network.asn}`} label={copy.autonomousSystem} language={language} /></DetailItem>
            ) : null}
            {observation.network.asnDescription ? (
              <DetailItem label={copy.asDescription}><span>{observation.network.asnDescription}</span></DetailItem>
            ) : null}
            {observation.network.asnRegistry ? (
              <DetailItem label={copy.asRegistry}><span>{observation.network.asnRegistry}</span></DetailItem>
            ) : null}
          </dl>
        </section>
      ) : null}
      {observation.assessment ? (
        <section className="detail-group" aria-label={copy.urlscanAssessment}>
          <h5>{copy.urlscanAssessment}</h5>
          <dl className="detail-grid">
            {observation.assessment.urlscanVerdictScore !== null ? (
              <DetailItem label={copy.urlscanVerdictScore}>
                <strong>{observation.assessment.urlscanVerdictScore}</strong><span className="detail-scale">{copy.scoreScale}</span>
              </DetailItem>
            ) : null}
            {observation.assessment.urlscanCategories.length > 0 ? (
              <DetailItem label={copy.reportedCategories}>
                <span className="detail-tags">
                  {observation.assessment.urlscanCategories.map((category) => <span key={category}>{category}</span>)}
                </span>
              </DetailItem>
            ) : null}
            {observation.assessment.redirectedToDomain ? (
              <DetailItem label={copy.observedRedirectDestination}>
                <CopyableValue
                  value={observation.assessment.redirectedToDomain}
                  label={copy.defangedRedirectDestination}
                  language={language}
                />
              </DetailItem>
            ) : null}
          </dl>
          <p className="detail-note">{copy.providerAssessmentNote}</p>
        </section>
      ) : null}
      {observation.certificate ? <CertificateDetail certificate={observation.certificate} language={language} /> : null}
    </article>
  );
}

export function DomainContext({ context, language = "en" }: { context: SignalDomainContext; language?: SiteLanguage }) {
  const copy = modalCopy[language];
  const recordGroups = [
    ["A", context.dns.a],
    ["AAAA", context.dns.aaaa],
    ["CNAME", context.dns.cname],
    ["NS", context.dns.ns],
    ["MX", context.dns.mx],
  ] as const;
  const registration = context.registration;
  return (
    <article className="detail-observation domain-context">
      <header>
        <div>
          <span className="source-chip">DNS / RDAP</span>
          <h4>{copy.boundedContextObserved(localizedTimestamp(context.observedAt, language))}</h4>
        </div>
      </header>
      <section className="detail-group" aria-label={copy.dnsContext}>
        <h5>{copy.dnsRecordsObserved}</h5>
        <dl className="detail-grid">
          <DetailItem label={copy.queriesCompleted}><span>{context.dns.queriesCompleted} / 5</span></DetailItem>
          {context.dns.minimumTtl !== null ? <DetailItem label={copy.minimumTtl}><span>{copy.seconds(context.dns.minimumTtl)}</span></DetailItem> : null}
        </dl>
        <div className="detail-list">
          <ul>
            {recordGroups.flatMap(([recordType, values]) => values.map((value) => (
              <li key={`${recordType}-${value}`}><span>{recordType}</span><CopyableValue value={value} label={copy.dnsRecord(recordType)} language={language} /></li>
            )))}
          </ul>
          {recordGroups.every(([, values]) => values.length === 0) ? <p>{copy.noDnsRecords}</p> : null}
        </div>
      </section>
      <section className="detail-group" aria-label={copy.registrationContext}>
        <h5>{copy.registrationContext}</h5>
        {registration ? (
          <dl className="detail-grid">
            {registration.domain ? <DetailItem label={copy.registeredDomain}><CopyableValue value={registration.domain} label={copy.registeredDomainCopy} language={language} /></DetailItem> : null}
            {registration.registrar ? <DetailItem label={copy.registrar}><span>{registration.registrar}</span></DetailItem> : null}
            {registration.registeredAt ? <DetailItem label={copy.registered}><time dateTime={registration.registeredAt}>{localizedTimestamp(registration.registeredAt, language)}</time></DetailItem> : null}
            {registration.updatedAt ? <DetailItem label={copy.updated}><time dateTime={registration.updatedAt}>{localizedTimestamp(registration.updatedAt, language)}</time></DetailItem> : null}
            {registration.expiresAt ? <DetailItem label={copy.expires}><time dateTime={registration.expiresAt}>{localizedTimestamp(registration.expiresAt, language)}</time></DetailItem> : null}
            {registration.statuses.length ? <DetailItem label={copy.statuses}><span>{registration.statuses.join(", ")}</span></DetailItem> : null}
          </dl>
        ) : <p className="detail-note">{copy.noRegistration}</p>}
        <p className="detail-note">{copy.dnsRegistrationBoundary}</p>
      </section>
    </article>
  );
}

export function ContextChanges({ changes, language = "en" }: { changes: SignalContextChange[]; language?: SiteLanguage }) {
  const title = language === "lt" ? "Konteksto pokyčiai" : "Context changes";
  const changedFields = language === "lt" ? "Pasikeitę laukai" : "Changed fields";
  const sourceReference = language === "lt" ? "Šaltinio nuoroda" : "Source reference";
  const providerObserved = language === "lt" ? "Šaltinio stebėjimo laikas" : "Provider observed";
  const boundary = language === "lt"
    ? "Tai riboti pasyviai stebėti pokyčiai, o ne veikėjo tapatybės ar kenkėjiško ketinimo įrodymas."
    : "These are bounded passive changes, not evidence of operator identity or malicious intent.";
  return (
    <article className="detail-observation context-changes">
      <header><div><span className="source-chip">{title}</span><h4>{title}</h4></div></header>
      <ol className="signal-timeline">
        {changes.map((change) => (
          <li key={change.eventId}>
            <time dateTime={change.observedAt}>{localizedTimestamp(change.observedAt, language)}</time>
            <strong>{change.changeType.replaceAll("-", " ")}</strong>
            <span>{changedFields}: {change.changedFields.join(", ")}</span>
            <span>{providerObserved}: <time dateTime={change.source.observedAt}>{localizedTimestamp(change.source.observedAt, language)}</time></span>
            <a href={change.source.referenceUrl} target="_blank" rel="noreferrer noopener">{sourceReference}: {change.source.name} <ExternalLink aria-hidden="true" /></a>
            <CopyableValue value={change.evidence.currentSha256} label="component SHA-256" language={language} />
            {change.evidence.primaryHtmlSha256.map((digest) => <CopyableValue key={digest} value={digest} label="primary HTML SHA-256" language={language} />)}
            {change.evidence.certificateSha256 ? <CopyableValue value={change.evidence.certificateSha256} label="certificate SHA-256" language={language} /> : null}
          </li>
        ))}
      </ol>
      <p className="detail-note">{boundary}</p>
    </article>
  );
}

export function ScreenshotModal({ signal, snapshotGeneratedAt, returnFocus, onClose, language = "en" }: ScreenshotModalProps) {
  const backdropRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const copy = modalCopy[language];
  const [detailState, setDetailState] = useState<DetailLoadState>({
    status: signal.detailAvailable ? "loading" : "idle",
  });
  const [detailAttempt, setDetailAttempt] = useState(0);
  const evidenceTier = signalEvidenceTier(signal);
  const reasonExplanations = explainReasons(signal, language);
  const correctionBody = copy.correctionBody(signal, snapshotGeneratedAt);
  const correctionHref = `mailto:info@hecavex.com?subject=${encodeURIComponent(copy.correctionSubject(signal.id))}&body=${encodeURIComponent(correctionBody)}`;

  useEffect(() => {
    if (!signal.detailAvailable) {
      setDetailState({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    setDetailState({ status: "loading" });
    void loadSignalDetail(signal, controller.signal)
      .then((detail) => {
        if (!controller.signal.aborted) setDetailState({ status: "ready", detail });
      })
      .catch(() => {
        if (!controller.signal.aborted) setDetailState({ status: "error" });
      });
    return () => controller.abort();
  }, [detailAttempt, signal.detailAvailable, signal.domain, signal.id]);

  useLayoutEffect(() => {
    const backdrop = backdropRef.current;
    const dialog = dialogRef.current;
    if (!backdrop || !dialog) return;

    closeRef.current?.focus({ preventScroll: true });
    const restoreBackground = isolateBackground(backdrop);

    const focusInsideDialog = (last = false) => {
      const focusable = focusableElements(dialog);
      const target = last ? focusable.at(-1) : focusable[0];
      (target ?? dialog).focus({ preventScroll: true });
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }

      if (event.key !== "Tab") return;
      const focusable = focusableElements(dialog);
      const first = focusable[0];
      const last = focusable.at(-1);
      const active = document.activeElement;

      if (!first || !last) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
      } else if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    };

    const onFocusIn = (event: FocusEvent) => {
      if (!(event.target instanceof Node) || dialog.contains(event.target)) return;
      focusInsideDialog();
    };

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", onFocusIn);
      restoreBackground();
      if (returnFocus.isConnected) returnFocus.focus({ preventScroll: true });
    };
  }, [onClose, returnFocus]);

  return (
    <div ref={backdropRef} className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="capture-modal" role="dialog" aria-modal="true" aria-labelledby="capture-title" tabIndex={-1}>
        <div className="capture-heading">
          <div>
            <p className="eyebrow">{copy.passiveEvidence}</p>
            <h2 id="capture-title">{signal.domain}</h2>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label={copy.closeDetails}>
            <X aria-hidden="true" />
          </button>
        </div>
        <section className="candidate-summary" aria-labelledby="candidate-summary-title">
          <div className="candidate-summary-heading">
            <div>
              <p className="eyebrow">{copy.whyIncluded}</p>
              <h3 id="candidate-summary-title">{copy.automatedExplanation}</h3>
            </div>
            <div className="evidence-badges" aria-label={copy.candidateEvidenceState}>
              <span className={`evidence-tier ${evidenceTier}`}>{evidenceTierLabel(evidenceTier, language)}</span>
              <span>{copy.matchScore(signalMatchScore(signal))}</span>
              {signal.reviewState && signal.reviewState !== "unreviewed" ? <span>{reviewStateLabels[language][signal.reviewState]}</span> : null}
            </div>
          </div>
          {reasonExplanations.length ? (
            <ul className="reason-explanations">
              {reasonExplanations.map((reason, index) => <li key={`${signal.id}-${index}`}>{reason}</li>)}
            </ul>
          ) : (
            <p className="candidate-explanation-empty">{copy.noReason}</p>
          )}
          <dl className="candidate-provenance">
            <DetailItem label={copy.signalId}><CopyableValue value={signal.id} label={copy.signalIdCopy} language={language} /></DetailItem>
            <DetailItem label={copy.potentialBrand}><span>{signal.brand ?? copy.unclassified}</span></DetailItem>
            <DetailItem label={copy.sourceState}><span>{statusLabels[language][signal.status]}</span></DetailItem>
            <DetailItem label={copy.sources}><span>{signal.sources.join(", ")}</span></DetailItem>
            {signal.discoveredVia?.length ? <DetailItem label={copy.discoveredVia}><span>{signal.discoveredVia.join(", ")}</span></DetailItem> : null}
            {signal.corroboratedBy?.length ? <DetailItem label={copy.corroboratedBy}><span>{signal.corroboratedBy.join(", ")}</span></DetailItem> : null}
            <DetailItem label={copy.firstSeen}><time dateTime={signal.firstSeen}>{localizedTimestamp(signal.firstSeen, language)}</time></DetailItem>
            <DetailItem label={copy.lastSeen}><time dateTime={signal.lastSeen}>{localizedTimestamp(signal.lastSeen, language)}</time></DetailItem>
            <DetailItem label={copy.snapshotGenerated}><time dateTime={snapshotGeneratedAt}>{localizedTimestamp(snapshotGeneratedAt, language)}</time></DetailItem>
            {signal.ltRelevance ? <DetailItem label={copy.lithuanianRelevance} fullRow><span>{relevanceLabels[language][signal.ltRelevance]}</span></DetailItem> : null}
          </dl>
          <p className="candidate-boundary">{copy.scoreBoundary}</p>
        </section>
        {signal.detailAvailable ? (
          <section className="signal-intelligence" aria-labelledby="signal-intelligence-title">
            <div className="signal-intelligence-heading">
              <div>
                <p className="eyebrow">{copy.domainIntelligence}</p>
                <h3 id="signal-intelligence-title">{copy.passiveContext}</h3>
              </div>
              <span>{copy.matchScore(signalMatchScore(signal))}</span>
            </div>
            {detailState.status === "loading" ? (
              <div className="detail-state" role="status" aria-live="polite">
                <p>{copy.loadingContext}</p>
              </div>
            ) : null}
            {detailState.status === "error" ? (
              <div className="detail-state error" role="status">
                <p>{copy.contextUnavailable}</p>
                <button type="button" onClick={() => setDetailAttempt((attempt) => attempt + 1)}>{copy.tryAgain}</button>
              </div>
            ) : null}
            {detailState.status === "ready" ? (
              <div className="detail-observations">
                {detailState.detail.observations.map((observation) => (
                  <ObservationDetail key={observation.source} observation={observation} language={language} />
                ))}
                {detailState.detail.domainContext ? <DomainContext context={detailState.detail.domainContext} language={language} /> : (
                  <p className="detail-context-missing">{copy.noDomainContext}</p>
                )}
                {detailState.detail.contextChanges?.length ? <ContextChanges changes={detailState.detail.contextChanges} language={language} /> : null}
              </div>
            ) : null}
          </section>
        ) : null}
        {signal.screenshotUrl ? (
          <div className="capture-frame">
            <img src={signal.screenshotUrl} alt={copy.screenshotAlt(signal.domain)} referrerPolicy="no-referrer" />
          </div>
        ) : (
          <div className="evidence-empty"><p>{copy.noScreenshot}</p></div>
        )}
        {signal.hashes?.length ? (
          <section className="evidence-hashes" aria-labelledby="hashes-title">
            <h3 id="hashes-title">{copy.observedHashes}</h3>
            <p>{copy.hashesNote}</p>
            <ul>{signal.hashes.map((digest) => <li key={digest}><code>{digest}</code></li>)}</ul>
          </section>
        ) : null}
        {signal.reasonCodes?.length ? (
          <section className="evidence-hashes" aria-labelledby="reasons-title">
            <h3 id="reasons-title">{copy.reasonCodes}</h3>
            <p>{copy.reasonCodesNote}</p>
            <ul>{signal.reasonCodes.map((reason) => <li key={reason}><code>{reason}</code></li>)}</ul>
          </section>
        ) : null}
        <div className="capture-footer">
          <p>{copy.externalBoundary}</p>
          <div className="capture-links">
            <a className="permanent-record-link" href={signalPath(signal, language)}>
              {copy.openPermanentRecord} <ArrowRight aria-hidden="true" />
            </a>
            <a href={correctionHref}>
              {copy.requestCorrection} <Flag aria-hidden="true" />
            </a>
            {signal.screenshotUrl ? (
              <a href={signal.screenshotUrl} target="_blank" rel="noreferrer noopener">
                {copy.openImage} <ExternalLink aria-hidden="true" />
              </a>
            ) : null}
            {signal.referenceUrl ? (
              <a href={signal.referenceUrl} target="_blank" rel="noreferrer noopener">
                {copy.openReport} <ExternalLink aria-hidden="true" />
              </a>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
