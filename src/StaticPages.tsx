import { Activity, Archive, CalendarClock, Database, Download, ExternalLink, FileCheck2, GitCompareArrows, RadioTower, Rss, ShieldCheck, Waypoints } from "lucide-react";
import { useEffect, useState } from "react";

import { AssociationExplorer } from "./components/AssociationExplorer.tsx";
import { BrowserIocChecker } from "./components/BrowserIocChecker.tsx";
import { SiteFooter } from "./components/SiteFooter.tsx";
import { SiteHeader } from "./components/SiteHeader.tsx";
import { formatDateTime } from "./lib/format.ts";
import { signalPath } from "./lib/signalRoutes.ts";
import type { DailyTrendRow, StaticPageData, StaticPageKind } from "./lib/staticPageBootstrap.ts";
import { trendDayState, trendFreshness } from "./lib/trendFreshness.ts";

export type StaticPageLanguage = "en" | "lt";

const staticRoutes: Record<StaticPageKind, Record<StaticPageLanguage, string>> = {
  changes: { en: "/changes/", lt: "/lt/pokyciai/" },
  trends: { en: "/trends/", lt: "/lt/tendencijos/" },
  associations: { en: "/associations/", lt: "/lt/sasajos/" },
  tools: { en: "/tools/", lt: "/lt/irankiai/" },
  dataset: { en: "/dataset/", lt: "/lt/duomenys/" },
};

function PageShell({ currentPage, language, children }: { currentPage: StaticPageKind; language: StaticPageLanguage; children: React.ReactNode }) {
  const alternateLanguage = language === "lt" ? "en" : "lt";
  return <div className="site-shell"><SiteHeader currentPage={currentPage} language={language} alternateHref={staticRoutes[currentPage][alternateLanguage]} /><main className="content-page intelligence-page" id="main-content">{children}</main><SiteFooter language={language} /></div>;
}

function ArtifactHero({ eyebrow, title, description, icon: Icon }: { eyebrow: string; title: string; description: string; icon: typeof Activity }) {
  return <header className="artifact-hero"><div><p className="eyebrow"><Icon aria-hidden="true" /> {eyebrow}</p><h1>{title}</h1></div><p>{description}</p></header>;
}

function formatEventDateTime(value: string, language: StaticPageLanguage): string {
  if (language === "en") return formatDateTime(value);
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "Laikas nežinomas";
  return new Intl.DateTimeFormat("lt-LT", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(timestamp);
}

export function ChangesPage({ data, language = "en" }: { data: StaticPageData; language?: StaticPageLanguage }) {
  const lt = language === "lt";
  const [type, setType] = useState("all");
  const [brand, setBrand] = useState("all");
  const [since, setSince] = useState("");
  const [page, setPage] = useState(1);
  const filtered = data.events.events.filter((event) => (type === "all" || event.type === type) && (brand === "all" || event.brand === brand) && (!since || event.occurredAt >= `${since}T00:00:00.000Z`));
  const pages = Math.max(1, Math.ceil(filtered.length / 25));
  const visible = filtered.slice((page - 1) * 25, page * 25);
  const brands = [...new Set(data.events.events.map((event) => event.brand))].sort();
  const typeLabels = lt
    ? { "first-publication": "Pirma publikacija", reobservation: "Pastebėta pakartotinai", "status-change": "Būsena pakeista", retraction: "Vertinimas atšauktas" } as const
    : { "first-publication": "First publication", reobservation: "Reobserved", "status-change": "Status changed", retraction: "Assessment retracted" } as const;
  return <PageShell currentPage="changes" language={language}>
    <ArtifactHero
      icon={CalendarClock}
      eyebrow={lt ? "30 dienų įvykių žurnalas" : "30-day event record"}
      title={lt ? "Kas pasikeitė" : "What changed"}
      description={lt
        ? "Patvarus įvykių lygmens naujų publikacijų, vėlesnių stebėjimų, būsenos pokyčių ir aiškių analitiko atšaukimų vaizdas. Tai publikavimo veikla, o ne phishing paplitimo matas."
        : "A durable event-level view of new publications, later observations, status changes, and explicit analyst retractions. This is publication activity, not a measure of phishing prevalence."}
    />
    <section className="feed-strip" aria-label={lt ? "Pokyčių srautai" : "Change feeds"}><div><Rss aria-hidden="true" /><span>{lt ? "Prenumeruoti neatsisiunčiant visos suvestinės" : "Subscribe without polling the full snapshot"}</span></div><a href="/data/events.atom.xml">Atom</a><a href="/data/events.rss.xml">RSS</a><a href="/data/events.feed.json">{lt ? "JSON srautas" : "JSON Feed"}</a><a href="/data/events.json">{lt ? "Įvykių JSON" : "Event JSON"}</a></section>
    <section className="event-section" aria-labelledby="events-title"><div className="section-heading"><div><p className="eyebrow">{lt ? "Publikavimo žurnalas" : "Publication log"}</p><h2 id="events-title">{lt ? "Naujausi įvykiai" : "Recent events"}</h2></div><p><strong>{data.events.events.length}</strong> {lt ? `įkelta · ${data.events.window.days} dienų langas` : `loaded · ${data.events.window.days}-day window`}</p></div>
      <div className="filter-shell"><label>{lt ? "Įvykio tipas" : "Event type"}<select value={type} onChange={(event) => { setType(event.target.value); setPage(1); }}><option value="all">{lt ? "Visi tipai" : "All types"}</option>{Object.entries(typeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>{lt ? "Prekės ženklas" : "Brand"}<select value={brand} onChange={(event) => { setBrand(event.target.value); setPage(1); }}><option value="all">{lt ? "Visi prekių ženklai" : "All brands"}</option>{brands.map((value) => <option key={value}>{value}</option>)}</select></label><label>{lt ? "Nuo datos (UTC)" : "Since date (UTC)"}<input type="date" value={since} onChange={(event) => { setSince(event.target.value); setPage(1); }} /></label></div>
      <p role="status">{lt ? `Atitinka ${filtered.length}; rodoma ${visible.length}. Įkelta ${data.events.events.length} iš ${data.events.totalAvailable}.` : `${filtered.length} matching; ${visible.length} shown. Loaded ${data.events.events.length} of ${data.events.totalAvailable}.`} {lt ? "Duomenų riba" : "Artifact cutoff"}: {formatEventDateTime(data.events.generatedAt, language)} UTC. {data.events.truncated ? (lt ? "Šaltinio sąrašas sutrumpintas; filtrai taikomi tik įkeltiems įvykiams." : "The upstream list is truncated; filters apply only to loaded events.") : null}</p>
      <ol className="event-list">{visible.map((event) => <li key={event.id}><time dateTime={event.occurredAt}>{formatEventDateTime(event.occurredAt, language)} UTC</time><span className={`event-type ${event.type}`}>{typeLabels[event.type]}</span><div><a href={signalPath(event.signalId, language)}>{event.domain}</a><span>{event.brand} · {event.sources.join(", ")}</span></div>{event.type === "status-change" ? <small>{event.previousStatus} → {event.status}</small> : null}</li>)}</ol>
      <div className="pagination"><button type="button" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>{lt ? "Ankstesnis" : "Previous"}</button><span>{lt ? "Puslapis" : "Page"} {page} / {pages}</span><button type="button" disabled={page === pages} onClick={() => setPage((value) => value + 1)}>{lt ? "Kitas" : "Next"}</button></div>
      {!data.events.events.length ? <p className="empty-copy">{lt ? "Dabartiniame viešame lange įvykių nėra." : "No event falls inside the current public window."}</p> : null}
    </section>
    <section className="related-route-card"><div><p className="eyebrow"><Archive aria-hidden="true" /> {lt ? "Išsaugotas archyvas" : "Retained archive"}</p><h2>{lt ? "Reikia visos kandidato laiko juostos?" : "Need the full candidate timeline?"}</h2><p>{lt ? "Istorijos vaizde saugomas ribotas pirmo ir paskutinio stebėjimo laikas, stebėjimų skaičius ir būsenos perėjimai už šio srauto lango ribų." : "The history view preserves bounded first-seen, last-seen, observation counts and status transitions beyond this feed window."}</p></div><a href={lt ? "/lt/istorija/" : "/history/"}>{lt ? "Atverti kandidatų istoriją" : "Open candidate history"} →</a></section>
  </PageShell>;
}

function formatTrendNumber(value: number, language: StaticPageLanguage): string {
  return new Intl.NumberFormat(language === "lt" ? "lt-LT" : "en-GB", { maximumFractionDigits: 2 }).format(value);
}

function CoverageBar({ row, maximum, language, now }: { row: DailyTrendRow; maximum: number; language: StaticPageLanguage; now: number }) {
  const lt = language === "lt";
  const dayState = trendDayState(row, now);
  const partialLabel = dayState === "partial"
    ? (lt ? "Nepilna UTC diena" : "Partial UTC day")
    : (lt ? "Nepilna suvestinės diena" : "Incomplete at cutoff");
  const schedule = row.collectorCoverage.recordedSchedulePercent;
  const listening = row.collectorCoverage.listeningCoveragePercent;
  const ceiling = row.collectorCoverage.scheduledListeningCeilingPercent;
  const completedSchedule = schedule === null ? null : Math.min(100, schedule);
  const additionalAttempts = Math.max(
    0,
    row.collectorCoverage.recordedAttempts - row.collectorCoverage.scheduledSlots,
  );
  const signals = formatTrendNumber(row.discovery.uniqueSignals, language);
  const attemptRatio = lt
    ? `bandymai: ${formatTrendNumber(row.collectorCoverage.recordedAttempts, language)} / ${formatTrendNumber(row.collectorCoverage.scheduledSlots, language)}`
    : `${formatTrendNumber(row.collectorCoverage.recordedAttempts, language)} / ${formatTrendNumber(row.collectorCoverage.scheduledSlots, language)} attempts`;
  const scheduleLabel = completedSchedule === null
    ? (lt ? `Suplanuoti intervalai: nėra duomenų · ${attemptRatio}` : `Scheduled slots: unavailable · ${attemptRatio}`)
    : (lt ? `${formatTrendNumber(completedSchedule, language)}% suplanuotų intervalų · ${attemptRatio}` : `${formatTrendNumber(completedSchedule, language)}% scheduled slots · ${attemptRatio}`);
  const listeningLabel = listening === null
    ? (lt ? "Faktinis klausymosi laikas: nėra duomenų" : "Wall-clock listening: unavailable")
    : (lt ? `Faktinis klausymosi laikas: ${formatTrendNumber(listening, language)}%` : `Wall-clock listening: ${formatTrendNumber(listening, language)}%`);
  const ceilingLabel = ceiling === null
    ? (lt ? "Planinė riba: nėra duomenų" : "Planned ceiling: unavailable")
    : (lt ? `planinė riba: ${formatTrendNumber(ceiling, language)}%` : `planned ceiling: ${formatTrendNumber(ceiling, language)}%`);

  return <article className={`trend-row${row.partialDay ? " trend-row--partial" : ""}`} data-day-state={dayState}>
    <div className="trend-date"><time dateTime={row.date}>{row.date}</time>{row.partialDay ? <> <span>{partialLabel}</span></> : null}</div>{" "}
    <div className="trend-bars" aria-hidden="true"><progress className="discovery" max={Math.max(1, maximum)} value={row.discovery.uniqueSignals} /><progress className="schedule" max={100} value={completedSchedule ?? 0} /></div>{" "}
    <strong className="trend-signal-count">{lt ? `Unikalūs signalai: ${signals}` : `${signals} unique signals`}</strong>{" "}
    <div className="trend-metrics"><span>{scheduleLabel}</span>{additionalAttempts > 0 ? <> <em>{lt ? `Papildomi bandymai: ${formatTrendNumber(additionalAttempts, language)}` : `Additional attempts: ${formatTrendNumber(additionalAttempts, language)}`}</em></> : null} <small>{listeningLabel} / {ceilingLabel}</small></div>
  </article>;
}

function Counts({ values, empty = "No values in the public sample" }: { values: Record<string, number>; empty?: string }) {
  const entries = Object.entries(values);
  return entries.length ? <ul className="facet-counts">{entries.slice(0, 12).map(([label, value]) => <li key={label}><span>{label}</span><strong>{value}</strong></li>)}</ul> : <p className="empty-copy">{empty}</p>;
}

export function TrendsPage({ data, language = "en" }: { data: StaticPageData; language?: StaticPageLanguage }) {
  const lt = language === "lt";
  const [now, setNow] = useState(data.renderedAt);
  useEffect(() => {
    const updateClock = () => setNow(Date.now());
    updateClock();
    const interval = window.setInterval(updateClock, 60_000);
    return () => window.clearInterval(interval);
  }, []);
  const freshness = trendFreshness(data.trends, now);
  const maximum = Math.max(0, ...data.trends.series.map((row) => row.discovery.uniqueSignals));
  const current = data.trends.series.at(-1);
  const intervalMinutes = data.trends.collectorSchedule.expectedIntervalSeconds / 60;
  const listeningMinutes = data.trends.collectorSchedule.expectedListeningSeconds / 60;
  return <PageShell currentPage="trends" language={language}>
    <ArtifactHero icon={Activity} eyebrow={lt ? "Aprėptį nurodantys matavimai" : "Coverage-aware measurements"} title={lt ? "Aptikimo tendencijos ir peržiūros kokybė" : "Discovery trends and review quality"} description={lt ? "Radaras skelbia savo veiklos rodiklius kartu su rinktuvų aprėptimi. Grafikai aprašo tik tai, ką ši atrankinė sistema pastebėjo ir paskelbė. Jie nevertina viso phishing masto Lietuvoje." : "Radar publishes its own activity beside collector coverage. The charts describe what this sampled pipeline saw and published. They do not estimate all Lithuanian phishing."} />
    <section className="trend-boundary"><RadioTower aria-hidden="true" /><div><strong>{lt ? "Kiekvienas skaičius pateikiamas su aprėptimi" : "Coverage travels with every count"}</strong><p>{lt ? "Rodikliai apima tik užfiksuotus rinkimo bandymus ir paskelbtus signalus; jie nėra viso interneto ar visų Lietuvos phishing atvejų matas." : data.trends.semantics}</p></div></section>
    <section className="trend-section">
      <div className="section-heading"><div><p className="eyebrow">{lt ? "Reta UTC seka" : "Sparse UTC series"}</p><h2>{lt ? "Kasdienis aptikimas" : "Daily discovery"}</h2></div><a href="/data/daily-trends.json">{lt ? "Atsisiųsti JSON" : "Download JSON"}</a></div>
      <div className={`trend-cutoff trend-cutoff--${freshness}`} role="status">
        <strong>{lt ? "Duomenys iki" : "Data through"} <time dateTime={data.trends.generatedAt}>{formatEventDateTime(data.trends.generatedAt, language)} UTC</time></strong>
        {freshness === "delayed" ? <p>{lt ? "Atnaujinimas vėluoja. Vėlesnė veikla neįtraukta." : "Update delayed. Later activity is not included."}</p> : null}
        {freshness === "unknown" ? <p>{lt ? "Duomenų aktualumo nustatyti nepavyko." : "Data freshness could not be determined."}</p> : null}
        {data.trends.series.some((row) => row.partialDay) ? <p>{lt ? "Nepilnos dienos rodikliai apima tik laiką iki šios ribos, net jei ta UTC diena jau pasibaigė." : "Partial-day totals cover only the time before this cutoff, even after that UTC day ends."}</p> : null}
      </div>
      <div className="trend-legend"><span><i className="discovery" /> {lt ? "unikalūs signalai" : "unique signals"}</span><span><i className="schedule" /> {lt ? "užfiksuoti suplanuoti intervalai" : "scheduled slots recorded"}</span></div>
      <p className="trend-method-note">{lt ? `Grafiko įvykdymas lygina užfiksuotus bandymus su numatytais intervalais. Faktinis klausymosi laikas rodomas greta kiekvienos dienos planinės ribos. Rinktuvas numato ${formatTrendNumber(listeningMinutes, language)} min. klausymąsi kas ${formatTrendNumber(intervalMinutes, language)} min.` : `Schedule completion compares recorded attempts with expected slots. Wall-clock listening is shown beside each day's planned ceiling. The collector plans ${formatTrendNumber(listeningMinutes, language)} listening minutes in every ${formatTrendNumber(intervalMinutes, language)}-minute interval.`}</p>
      <div className="trend-chart">{data.trends.series.map((row) => <CoverageBar key={row.date} row={row} maximum={maximum} language={language} now={now} />)}</div>
      <p className="boundary-note">{lt ? `Rodomos dienos, kuriomis užfiksuota rinkimo arba publikavimo veikla. Suvestinės intervale praleista dienų be įrašų: ${data.trends.omittedZeroDays}. Datos po duomenų ribos yra nežinomos, o ne nulinės.` : `Dates with recorded collection or publication activity are shown. ${data.trends.omittedZeroDays} dates with neither are omitted within the saved range. Dates after the data cutoff are unknown, not zero.`}</p>
    </section>
    <section className="quality-grid"><article><p className="eyebrow">{lt ? "Naujausia užfiksuota diena" : "Latest recorded day"}</p><h2>{current?.date ?? data.trends.to}</h2><dl><div><dt>{lt ? "Unikalūs signalai" : "Unique signals"}</dt><dd>{current?.discovery.uniqueSignals ?? 0}</dd></div><div><dt>{lt ? "Pirmosios publikacijos" : "First publications"}</dt><dd>{current?.discovery.firstPublications ?? 0}</dd></div><div><dt>{lt ? "Pakartotiniai stebėjimai" : "Reobservations"}</dt><dd>{current?.discovery.reobservations ?? 0}</dd></div><div><dt>{lt ? "Sėkmingi bandymai" : "Healthy attempts"}</dt><dd>{current?.collectorCoverage.healthyAttempts ?? 0}</dd></div></dl></article><article><p className="eyebrow">{lt ? "Analitiko imtis" : "Analyst sample"}</p><h2>{lt ? "Peržiūros aprėptis" : "Review coverage"}</h2><dl><div><dt>{lt ? "Tinkami signalai" : "Eligible signals"}</dt><dd>{data.quality.reviewCoverage.eligiblePublishedSignals}</dd></div><div><dt>{lt ? "Įvertinta" : "Assessed"}</dt><dd>{data.quality.reviewCoverage.assessedSignals}</dd></div><div><dt>{lt ? "Aprėptis" : "Coverage"}</dt><dd>{data.quality.reviewCoverage.percent ?? (lt ? "Nėra duomenų" : "Unavailable")}{data.quality.reviewCoverage.percent !== null ? "%" : ""}</dd></div><div><dt>{lt ? "Medianinis vėlavimas" : "Median latency"}</dt><dd>{data.quality.reviewLatencyHours.median ?? (lt ? "Nėra duomenų" : "Unavailable")}{data.quality.reviewLatencyHours.median !== null ? (lt ? " val." : "h") : ""}</dd></div></dl></article><article className="quality-warning"><p className="eyebrow">{lt ? "Tikslumas" : "Precision"}</p><h2>{lt ? "Kol kas patikimai neapskaičiuojamas" : "Not supportable yet"}</h2><p>{lt ? "Nėra pagrįsto atrankos plano ar visos populiacijos vertinimo, todėl populiacijos tikslumo patikimai įvertinti negalima." : data.quality.precision.reason}</p></article></section>
    <section className="quality-facets"><article><h3>{lt ? "Peržiūros rezultatai" : "Review outcomes"}</h3><Counts values={data.quality.reviewSample.outcomes} empty={lt ? "Viešoje imtyje reikšmių nėra" : "No values in the public sample"} /></article><article><h3>{lt ? "Peržiūrėtos imties įrodymai" : "Evidence in reviewed sample"}</h3><Counts values={data.quality.reviewSample.byEvidence} empty={lt ? "Viešoje imtyje reikšmių nėra" : "No values in the public sample"} /></article><article><h3>{lt ? "Dabartinės išimtys" : "Current exclusions"}</h3><Counts values={data.quality.currentExclusions.byReason} empty={lt ? "Viešoje imtyje reikšmių nėra" : "No values in the public sample"} /></article></section>
  </PageShell>;
}

export function AssociationsPage({ data, language = "en" }: { data: StaticPageData; language?: StaticPageLanguage }) {
  const lt = language === "lt";
  return <PageShell currentPage="associations" language={language}><ArtifactHero icon={Waypoints} eyebrow={lt ? "Įrodymų grafas" : "Evidence graph"} title={lt ? "Paskelbtos sąsajos" : "Published associations"} description={lt ? "Peržiūrėkite ribotus ryšius, kuriuos Radaras gali pagrįsti bendromis maišos reikšmėmis, sertifikatais, peradresavimais, tinklo kontekstu ir DNS. Sąsaja niekada nereiškia priskyrimo." : "Inspect every bounded relationship Radar can support from shared hashes, certificates, redirects, network context, and DNS. Association never means attribution."} /><AssociationExplorer signals={data.snapshot.signals} artifact={data.related} language={language} signalHref={(signalId) => language === "lt" ? `/lt/signalai/${signalId}/` : `/signals/${signalId}/`} /></PageShell>;
}

export function ToolsPage({ data, language = "en" }: { data: StaticPageData; language?: StaticPageLanguage }) {
  const lt = language === "lt";
  return <PageShell currentPage="tools" language={language}><ArtifactHero icon={ShieldCheck} eyebrow={lt ? "Tik naršyklėje veikiantis gynybinis įrankis" : "Browser-only defensive utility"} title={lt ? "Patikrinkite indikatorius vietoje" : "Check your indicators locally"} description={lt ? "Palyginkite domenus, URL ir maišos reikšmes su dabartiniais bei išsaugotais viešais Radaro įrašais. Palyginimas vyksta naršyklės atmintyje; pateiktos reikšmės HECAVEX nesiunčiamos." : "Compare domains, URLs, and hashes with Radar's current and retained public records. The comparison happens in browser memory; submitted values are never sent to HECAVEX."} /><BrowserIocChecker signals={data.snapshot.signals} history={data.history} historyTotal={data.historyTotal} language={language} signalHref={(signalId) => language === "lt" ? `/lt/signalai/${signalId}/` : `/signals/${signalId}/`} /></PageShell>;
}

const downloads = [
  ["Current defanged snapshot", "/data/radar.json", "JSON"],
  ["Current snapshot index", "/data/radar.index.json", "JSON"],
  ["Observation bundle", "/data/radar.stix.json", "STIX 2.1"],
  ["Reviewed indicators and sightings", "/data/radar-reviewed.stix.json", "STIX 2.1"],
  ["Event record", "/data/events.json", "JSON"],
  ["Daily coverage-aware trends", "/data/daily-trends.json", "JSON"],
  ["Public review quality", "/data/quality-metrics.json", "JSON"],
  ["Association graph", "/data/related-observations.json", "JSON"],
  ["Reviewed MISP manifest", "/data/misp/manifest.json", "MISP JSON"],
  ["Official-domain warning list", "/data/misp-warninglists/hecavex-official-domains/list.json", "MISP JSON"],
  ["Release manifest", "/data/feed-manifest.json", "JSON"],
] as const;

export function DatasetPage({ data, language = "en" }: { data: StaticPageData; language?: StaticPageLanguage }) {
  const lt = language === "lt";
  return <PageShell currentPage="dataset" language={language}><ArtifactHero icon={Database} eyebrow={lt ? "Viešas duomenų katalogas" : "Public data catalogue"} title={lt ? "Radaro duomenų rinkiniai" : "Radar dataset distributions"} description={lt ? "Mašininiu būdu skaitomi, riboti gynybinio tyrimo duomenys su schemomis, kontrolinėmis sumomis, saugojimo semantika ir aiškiomis saugumo ribomis." : "Machine-readable, bounded defensive research artifacts with schemas, checksums, retention semantics, and explicit safety limits."} />
    <section className="dataset-summary"><div><span>{lt ? "Suvestinė sugeneruota" : "Snapshot generated"}</span><strong>{formatDateTime(data.snapshot.generatedAt)} UTC</strong></div><div><span>{lt ? "Dabartiniai signalai" : "Current signals"}</span><strong>{data.snapshot.signals.length}</strong></div><div><span>{lt ? "Istorijos įrašai" : "History records"}</span><strong>{data.historyTotal ?? data.history.signals.length}</strong></div><div><span>{lt ? "Įvykių langas" : "Event window"}</span><strong>{data.events.window.days} {lt ? "dienų" : "days"}</strong></div></section>
    <section className="download-grid" aria-label={lt ? "Duomenų rinkinių atsisiuntimai" : "Dataset downloads"}>{downloads.map(([title, href, format]) => <a href={href} key={href}><FileCheck2 aria-hidden="true" /><span><strong>{lt ? ({"Current defanged snapshot":"Dabartinė neutralizuota suvestinė","Current snapshot index":"Dabartinės suvestinės indeksas","Observation bundle":"Stebėjimų rinkinys","Reviewed indicators and sightings":"Peržiūrėti indikatoriai ir stebėjimai","Event record":"Įvykių žurnalas","Daily coverage-aware trends":"Kasdienės tendencijos su aprėptimi","Public review quality":"Viešos peržiūros kokybė","Association graph":"Sąsajų grafas","Reviewed MISP manifest":"Peržiūrėto MISP manifestas","Official-domain warning list":"Oficialių domenų warning list","Release manifest":"Laidos manifestas"} as Record<string, string>)[title] : title}</strong><small>{format}</small></span><Download aria-hidden="true" /></a>)}</section>
    <section className="dataset-explanation">
      <article><p className="eyebrow">{lt ? "Vientisumas" : "Integrity"}</p><h2>{lt ? "Patikrinkite prieš naudodami" : "Verify before use"}</h2><p>{lt ? "Kiekvienas kanoninis duomenų failas turi SHA-256 kontrolinę sumą ir yra įtrauktas į laidos manifestą. Tik sėkmingas savaitinis workflow paskelbia archyvą, SPDX 2.3 priklausomybių aprašą, kontrolines sumas ir GitHub atestacijas; vien grafikas nereiškia, kad laida jau egzistuoja." : "Every canonical artifact has a SHA-256 sidecar and appears in the release manifest. Only a successful weekly workflow publishes the archive, SPDX 2.3 dependency inventory, checksums, and GitHub attestations; the schedule alone does not mean a release exists."}</p><a href="https://github.com/Hecavex/radar.hecavex.com/releases" target="_blank" rel="noreferrer noopener">{lt ? "Patikrinti paskelbtas laidas" : "Check published releases"} <ExternalLink aria-hidden="true" /></a></article>
      <article><p className="eyebrow"><GitCompareArrows aria-hidden="true" /> {lt ? "Semantika" : "Semantics"}</p><h2>{lt ? "Signalai, ne nuosprendžiai" : "Signals, not verdicts"}</h2><p>{lt ? "Neutralizuotos skydelio eilutės yra tyrimo kryptys. Tik peržiūrėtame STIX rinkinyje ar įjungtame MISP feed gali būti galiojančių analitiko patvirtintų indikatorių. Trūkstami įrašai, papildomas kontekstas ar peržiūra lieka nežinomi." : "Defanged dashboard rows are discovery leads. Only the reviewed STIX distribution or enabled reviewed MISP feed can contain active analyst-confirmed indicators. Missing rows, enrichment, or review are unknown."}</p><a href={lt ? "/lt/dokumentacija/#duomenu-sutartis" : "/docs/#data-contract"}>{lt ? "Skaityti duomenų sutartį" : "Read the data contract"} →</a></article>
      <article><p className="eyebrow">{lt ? "Ataskaitos ruošimas" : "Reporting preparation"}</p><h2>{lt ? "Vietinis, nieko nesiunčiantis įrankis" : "Local, non-sending utility"}</h2><p>{lt ? "Įrankis veikia tik su galiojančiu viešu analitiko patvirtinimu, patikrina viešus Radaro failus ir gali suskaičiuoti pasirinktų vietinių failų maišas. Turinys ir originalūs failų vardai neišsaugomi, o ataskaita automatiškai niekur nesiunčiama." : "The utility works only with an active public analyst confirmation, validates Radar's public artifacts, and can hash selected local files. Contents and original filenames are not retained, and no report is sent automatically."}</p><a href="/reporting/">{lt ? "Išplėstinis prižiūrėtojo įrankis (anglų k.)" : "Advanced maintainer utility (English only)"} →</a></article>
    </section>
  </PageShell>;
}

export function StaticPage({ kind, data, language = "en" }: { kind: StaticPageKind; data: StaticPageData; language?: StaticPageLanguage }) {
  if (kind === "changes") return <ChangesPage data={data} language={language} />;
  if (kind === "trends") return <TrendsPage data={data} language={language} />;
  if (kind === "associations") return <AssociationsPage data={data} language={language} />;
  if (kind === "tools") return <ToolsPage data={data} language={language} />;
  return <DatasetPage data={data} language={language} />;
}
