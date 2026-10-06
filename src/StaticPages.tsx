import { Database, Download, ExternalLink, FileCheck2, GitCompareArrows, ShieldCheck, Waypoints } from "lucide-react";

import { AssociationExplorer } from "./components/AssociationExplorer.tsx";
import { BrowserIocChecker } from "./components/BrowserIocChecker.tsx";
import { ArtifactHero, PageShell, type StaticPageLanguage } from "./components/ArtifactPageShell.tsx";
import { formatDateTime } from "./lib/format.ts";
import type { StaticPageData, StaticPageKind } from "./lib/staticPageBootstrap.ts";
import { ChangesPage } from "./pages/ChangesPage.tsx";
import { TrendsPage } from "./pages/TrendsPage.tsx";

export type { StaticPageLanguage } from "./components/ArtifactPageShell.tsx";
export { ChangesPage } from "./pages/ChangesPage.tsx";
export { TrendsPage } from "./pages/TrendsPage.tsx";

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
