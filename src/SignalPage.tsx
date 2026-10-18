import { ExternalLink, Flag, GitCompareArrows, History, Link2, Network, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { SiteFooter } from "./components/SiteFooter.tsx";
import { ResearchBrief } from "./components/ResearchBrief.tsx";
import { ContextChanges, CopyableValue, DetailItem, DomainContext, ObservationDetail } from "./components/ScreenshotModal.tsx";
import { SiteHeader } from "./components/SiteHeader.tsx";
import { brandPath, defangDomain } from "./lib/brandRegistry.ts";
import { evidenceTierLabel, explainReasons, signalEvidenceTier, signalMatchScore } from "./lib/dashboard.ts";
import { statusLt } from "./lt/formatLt.ts";
import { formatDateTime, sentenceCase } from "./lib/format.ts";
import type { SignalPageData } from "./lib/pageBootstrap.ts";
import { compareToOfficialDomain } from "./lib/signalComparison.ts";
import { signalPath } from "./lib/signalRoutes.ts";

const copy = {
  en: {
    back: "All recent signals",
    eyebrow: "Durable signal record",
    title: "Potential impersonation candidate",
    explanation: "Why Radar included this candidate",
    comparison: "Observed name compared with official scope",
    timeline: "Observation timeline",
    context: "Passive context",
    related: "Published associations",
    limits: "This is an automated research lead, not a maliciousness verdict. Do not visit the candidate domain.",
    none: "No bounded passive enrichment is published for this signal. Missing evidence is unknown.",
    noRelated: "No publishable association currently meets Radar's evidence threshold.",
  },
  lt: {
    back: "Visi naujausi signalai",
    eyebrow: "Išsaugotas signalo įrašas",
    title: "Galimas apsimetimo kandidatas",
    explanation: "Kodėl Radar įtraukė šį kandidatą",
    comparison: "Stebėtas vardas ir oficiali sritis",
    timeline: "Stebėjimo laiko juosta",
    context: "Pasyvus kontekstas",
    related: "Paskelbtos sąsajos",
    limits: "Tai automatinis tyrimo signalas, o ne kenkėjiškumo verdiktas. Kandidato domeno neatidarykite.",
    none: "Šiam signalui nepaskelbta ribota pasyvaus praturtinimo informacija. Duomenų nebuvimas nieko nepatvirtina.",
    noRelated: "Šiuo metu nėra sąsajos, atitinkančios viešo įrodymo ribą.",
  },
} as const;

function scriptLabel(character: string, language: "en" | "lt"): string {
  if (/\p{Script=Latin}/u.test(character)) return language === "lt" ? "lotynų raštas" : "Latin script";
  if (/\p{Script=Cyrillic}/u.test(character)) return language === "lt" ? "kirilica" : "Cyrillic script";
  if (/\p{Script=Greek}/u.test(character)) return language === "lt" ? "graikų raštas" : "Greek script";
  if (/\p{Script=Inherited}/u.test(character)) return language === "lt" ? "paveldėtas raštas" : "Inherited script";
  return language === "lt" ? "kita rašto sistema" : "Other script";
}

export function SignalPage({ data }: { data: SignalPageData }) {
  const [showImage, setShowImage] = useState(false);
  const language = data.language;
  const text = copy[language];
  const tier = signalEvidenceTier(data.signal);
  const reasons = explainReasons(data.signal, language);
  const comparison = compareToOfficialDomain(data.signal.domain, data.brand ?? undefined, language);
  const idnMatch = data.idnMatch?.signalId === data.signal.id && data.idnMatch.domain === data.signal.domain &&
    data.idnMatch.brand === data.signal.brand ? data.idnMatch : null;
  const unicodeCharacters = comparison ? [...new Set(Array.from(comparison.observedUnicode).filter((character) => character.codePointAt(0)! > 127))] : [];
  const alternatePath = signalPath(data.signal, language === "en" ? "lt" : "en");
  const relatedById = new Map(data.relatedNodes.map((node) => [node.signalId, node]));
  const connected = data.relatedEdges.map((edge) => ({
    edge,
    other: relatedById.get(edge.source === data.signal.id ? edge.target : edge.source),
  })).filter((item) => item.other !== undefined);
  const correctionBody = language === "lt"
    ? `Signalo ID: ${data.signal.id}\nNeutralizuotas indikatorius: ${data.signal.url}\nSuvestinė: ${data.generatedAt}`
    : `Signal ID: ${data.signal.id}\nDefanged indicator: ${data.signal.url}\nSnapshot: ${data.generatedAt}`;
  const correctionHref = `mailto:info@hecavex.com?subject=${encodeURIComponent(`${language === "lt" ? "HECAVEX Radaro pataisymas" : "HECAVEX Radar correction"} ${data.signal.id}`)}&body=${encodeURIComponent(correctionBody)}`;

  return (
    <div className="site-shell">
      <SiteHeader currentPage="signal" language={language} alternateHref={alternatePath} />
      <main className="permanent-page signal-profile" id="main-content">
        <nav className="breadcrumb" aria-label={language === "lt" ? "Naršymo kelias" : "Breadcrumb"}>
          <a href={language === "lt" ? "/lt/#signalai" : "/#signals"}>← {text.back}</a>
          <span>/</span><span>{data.signal.id}</span>
        </nav>

        <header className="profile-hero">
          <div>
            <p className="eyebrow"><ShieldAlert aria-hidden="true" /> {text.eyebrow}</p>
            <h1>{data.signal.domain}</h1>
            <p>{text.title}. {text.limits}</p>
          </div>
          <dl className="profile-summary">
            <DetailItem label={language === "lt" ? "Būsena" : "Source-reported state"}><span>{language === "lt" ? statusLt[data.signal.status] : sentenceCase(data.signal.status)}</span></DetailItem>
            <DetailItem label={language === "lt" ? "Atitikimo balas" : "Match score"}><strong>{signalMatchScore(data.signal)}/100</strong></DetailItem>
            <DetailItem label={language === "lt" ? "Įrodymų lygis" : "Evidence tier"}><span>{evidenceTierLabel(tier, language)}</span></DetailItem>
            <DetailItem label="Signal ID"><CopyableValue value={data.signal.id} label={language === "lt" ? "signalo ID" : "signal ID"} language={language} /></DetailItem>
          </dl>
        </header>

        <div className="profile-layout">
          <div className="profile-main">
            <section className="profile-section" aria-labelledby="explanation-title">
              <p className="eyebrow">01 / {text.explanation}</p>
              <h2 id="explanation-title">{text.explanation}</h2>
              {reasons.length ? <ul className="reason-explanations">{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>{text.none}</p>}
              {idnMatch ? <div className="idn-explanation">
                <h3>{language === "lt" ? "Peržiūrėtas IDN vaizdinio panašumo profilis" : "Curated IDN visual profile"}</h3>
                <p>{language === "lt"
                  ? "Šiame leidinyje pritaikytas ribotas vaizdinio panašumo profilis, papildantis esamą Radar palyginimą pagal UTS #39 duomenis. Tai nėra tikslus UTS #39 sutapimas, naršyklės patikros rezultatas ar analitiko patvirtinimas."
                  : "This release used a bounded visual profile that supplements Radar's existing comparison derived from UTS #39 data. This is not an exact UTS #39 match, a browser-check result, or analyst confirmation."}</p>
                <dl className="candidate-provenance">
                  <DetailItem label={language === "lt" ? "Profilis" : "Profile"}><code>radar-idn-visual-v1</code></DetailItem>
                  <DetailItem label={language === "lt" ? "Registro pavadinimas" : "Registry alias"}><code>{idnMatch.alias}</code></DetailItem>
                  <DetailItem label={language === "lt" ? "Sutapusi dalis" : "Matched label"}><code>{idnMatch.matchedLabel}</code></DetailItem>
                  <DetailItem label={language === "lt" ? "Dalies vieta" : "Label position"}><span>{idnMatch.labelIndex + 1} · {idnMatch.labelRole === "registrable" ? (language === "lt" ? "registruojama dalis" : "registrable label") : (language === "lt" ? "subdomenas" : "subdomain")}</span></DetailItem>
                </dl>
                <ul className="comparison-notes">{idnMatch.substitutions.map((substitution) => <li key={substitution.position}>
                  {language === "lt" ? "Ženklas" : "Character"} {substitution.position + 1}: <code>{Array.from(idnMatch.matchedLabel)[substitution.position]} {substitution.codePoint} → {substitution.replacement}</code> · {scriptLabel(Array.from(idnMatch.matchedLabel)[substitution.position], language)}
                </li>)}</ul>
                <p className="boundary-note">{language === "lt" ? "Rodoma dabartinio leidinio analizė, o ne ankstesnio stebėjimo aptikimo istorija." : "This is current-release analysis, not a reconstruction of detection at an earlier observation."}</p>
                <a href="/data/idn-matches-v1.json">{language === "lt" ? "IDN paaiškinimų JSON" : "IDN explanation JSON"}</a>
              </div> : null}
              <dl className="candidate-provenance">
                <DetailItem label={language === "lt" ? "Galimas prekės ženklas" : "Potential brand match"}>
                  {data.brand ? <a href={brandPath(data.brand.brand, language)}>{data.brand.brand}</a> : <span>{language === "lt" ? "Nepriskirta" : "Unclassified"}</span>}
                </DetailItem>
                <DetailItem label={language === "lt" ? "Šaltiniai" : "Sources"}><span>{data.signal.sources.join(", ")}</span></DetailItem>
                <DetailItem label={language === "lt" ? "Aptikta per" : "Discovered via"}><span>{data.signal.discoveredVia?.join(", ") ?? (language === "lt" ? "Nežinoma" : "Unknown")}</span></DetailItem>
                <DetailItem label={language === "lt" ? "Patvirtinta per" : "Corroborated by"}><span>{data.signal.corroboratedBy?.join(", ") || (language === "lt" ? "Nepatvirtinta kitais šaltiniais" : "Not corroborated")}</span></DetailItem>
              </dl>
            </section>

            {comparison ? (
              <section className="profile-section" aria-labelledby="comparison-title">
                <p className="eyebrow"><GitCompareArrows aria-hidden="true" /> 02 / {text.comparison}</p>
                <h2 id="comparison-title">{text.comparison}</h2>
                <div className="domain-comparison">
                  <div><span>{language === "lt" ? "Oficialus · A-label" : "Official · A-label"}</span><code>{defangDomain(comparison.officialDomain)}</code></div>
                  <div><span>{language === "lt" ? "Stebėtas · A-label" : "Observed · A-label"}</span><code>{defangDomain(comparison.observedDomain)}</code></div>
                  <div><span>{language === "lt" ? "Oficialus · Unicode" : "Official · Unicode"}</span><code>{defangDomain(comparison.officialUnicode)}</code></div>
                  <div><span>{language === "lt" ? "Stebėtas · Unicode" : "Observed · Unicode"}</span><code><span className="sr-only">{defangDomain(comparison.observedUnicode)}</span><span aria-hidden="true">{comparison.operations.map((operation, index) => <mark className={operation.kind} key={`${operation.kind}-${index}`}>{operation.observed ? defangDomain(operation.observed) : "∅"}</mark>)}</span></code></div>
                </div>
                {unicodeCharacters.length ? <p className="unicode-codepoints">{language === "lt" ? "Ne ASCII ženklai:" : "Non-ASCII characters:"} {unicodeCharacters.map((character) => <span key={character}><code>{character} U+{character.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}</code> · {scriptLabel(character, language)};{" "}</span>)}</p> : null}
                <ul className="comparison-notes">{comparison.observations.map((observation) => <li key={observation}>{observation}</li>)}</ul>
                <p className="boundary-note">{language === "lt" ? `Unicode kodų taškų Levenšteino atstumas ${comparison.distance}. Oficialus palyginimo domenas parinktas pagal tą patį matą. Tai vaizdinis palyginimas, ne aptikimo balas ar ketinimo bei nuosavybės įrodymas.` : `Unicode code-point Levenshtein distance ${comparison.distance}. The official comparison domain is selected using the same metric. This visual comparison is not the detection score or proof of intent or ownership.`}</p>
                <p className="boundary-note">{language === "lt"
                  ? "Naršyklės adresų juostos ir el. pašto rodomos formos priklauso nuo programos bei jos versijos. Unicode forma, galiojantis TLS sertifikatas ar perspėjimo nebuvimas saugumo nepatvirtina."
                  : "Address-bar and email display depend on the application and its version. Unicode display, a valid TLS certificate, or absence of a warning does not establish safety."}</p>
              </section>
            ) : null}

            <section className="profile-section" aria-labelledby="timeline-title">
              <p className="eyebrow"><History aria-hidden="true" /> 03 / {text.timeline}</p>
              <h2 id="timeline-title">{text.timeline}</h2>
              <ol className="signal-timeline">
                <li><time dateTime={data.signal.firstSeen}>{formatDateTime(data.signal.firstSeen)} UTC</time><strong>{language === "lt" ? "Pirmą kartą stebėta" : "First observed"}</strong></li>
                {data.history?.statusTransitions.map((transition) => <li key={transition.eventId}><time dateTime={transition.observedAt}>{formatDateTime(transition.observedAt)} UTC</time><strong>{language === "lt" ? statusLt[transition.status] : sentenceCase(transition.status)}</strong><span>{transition.reasonCodes.join(", ")}</span></li>)}
                <li><time dateTime={data.signal.lastSeen}>{formatDateTime(data.signal.lastSeen)} UTC</time><strong>{language === "lt" ? "Paskutinį kartą stebėta" : "Last observed"}</strong></li>
              </ol>
              {data.history ? <p className="boundary-note">{language === "lt" ? `Viešoje istorijoje išsaugota ribotų stebėjimo įvykių: ${data.history.observationCount}.` : `${data.history.observationCount} bounded observation events retained in public history.`}</p> : null}
            </section>

            <section className="profile-section" aria-labelledby="context-title">
              <p className="eyebrow"><Network aria-hidden="true" /> 04 / {text.context}</p>
              <h2 id="context-title">{text.context}</h2>
              {data.detail ? <div className="detail-observations"><h3 className="sr-only">{language === "lt" ? "Stebėjimų kontekstas" : "Observation context"}</h3>{data.detail.observations.map((observation) => <ObservationDetail observation={observation} key={observation.source} language={language} />)}{data.detail.domainContext ? <DomainContext context={data.detail.domainContext} language={language} /> : null}{data.detail.contextChanges?.length ? <ContextChanges changes={data.detail.contextChanges} language={language} /> : null}</div> : <p>{text.none}</p>}
            </section>

            <section className="profile-section" aria-labelledby="related-title">
              <p className="eyebrow"><Network aria-hidden="true" /> 05 / {text.related}</p>
              <h2 id="related-title">{text.related}</h2>
              {connected.length ? <ul className="association-cards">{connected.map(({ edge, other }) => <li key={edge.id}><a href={signalPath(other!.signalId, language)}>{other!.domain}</a><span>{edge.strength.replaceAll("-", " ")}</span><small>{edge.evidence.map((evidence) => evidence.type).join(", ")}</small></li>)}</ul> : <p>{text.noRelated}</p>}
              <p className="boundary-note">{language === "lt" ? "Bendra infrastruktūra ar artefaktai rodo sąsajas, o ne priskyrimą kampanijai ar veikėjui." : "Shared infrastructure or artifacts are associations, not campaign or actor attribution."}</p>
            </section>
            <ResearchBrief data={data} />
          </div>

          <aside className="profile-aside" aria-label={language === "lt" ? "Signalo įrašo veiksmai" : "Signal record controls"}>
            <div className="aside-panel"><span>{language === "lt" ? "Suvestinė" : "Snapshot"}</span><strong>{formatDateTime(data.generatedAt)} UTC</strong>{data.detail ? <a href={`/data/signals/${data.signal.id.slice(0, 2)}/${data.signal.id}.json`}>{language === "lt" ? "Signalo JSON" : "Signal JSON"} <Link2 aria-hidden="true" /></a> : <span>{language === "lt" ? "Šaltinio informacija nepasiekiama" : "Source detail unavailable"}</span>}</div>
            {data.signal.screenshotUrl ? <div className="aside-panel screenshot-preview"><span>{language === "lt" ? "Archyvinė ekrano kopija" : "Archived capture"}</span>{showImage ? <><img src={data.signal.screenshotUrl} alt={language === "lt" ? `Archyvinė ${data.signal.domain} ekrano kopija` : `Archived screenshot for ${data.signal.domain}`} referrerPolicy="no-referrer" /><a href={data.signal.screenshotUrl} target="_blank" rel="noreferrer noopener">{language === "lt" ? "Atverti vaizdą" : "Open image"} <ExternalLink aria-hidden="true" /></a></> : <><p>{language === "lt" ? "Įkeliant vaizdą bus prisijungta prie URLScan, kuris matys jūsų IP adresą ir prašomą archyvinį vaizdą." : "Loading contacts URLScan, which receives your IP address and the requested archived image."}</p><button className="button" type="button" onClick={() => setShowImage(true)}>{language === "lt" ? "Įkelti archyvinį vaizdą iš URLScan" : "Load archived image from URLScan"}</button></>}</div> : null}
            <div className="aside-panel"><span>{language === "lt" ? "Pataisymai" : "Corrections"}</span><p>{language === "lt" ? "Praneškite apie klaidingą aptikimą, pasikeitusią būseną ar faktinę klaidą, nurodydami stabilų signalo ID." : "Report a false positive, changed state, or factual error with the stable signal ID."}</p><a href={correctionHref}>{language === "lt" ? "Pranešti apie klaidą" : "Request correction"} <Flag aria-hidden="true" /></a></div>
          </aside>
        </div>
      </main>
      <SiteFooter language={language} />
    </div>
  );
}
