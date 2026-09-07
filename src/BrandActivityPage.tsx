import { ExternalLink, Rss, ShieldCheck } from "lucide-react";

import { SiteFooter } from "./components/SiteFooter.tsx";
import { SiteHeader } from "./components/SiteHeader.tsx";
import { brandPath, brandSlug, defangDomain } from "./lib/brandRegistry.ts";
import { signalMatchScore } from "./lib/dashboard.ts";
import { statusLt } from "./lt/formatLt.ts";
import { formatDateTime } from "./lib/format.ts";
import type { BrandPageData } from "./lib/pageBootstrap.ts";
import { signalPath } from "./lib/signalRoutes.ts";

export function BrandActivityPage({ data }: { data: BrandPageData }) {
  const lt = data.language === "lt";
  const slug = brandSlug(data.brand.brand);
  const alternatePath = brandPath(data.brand.brand, lt ? "en" : "lt");
  const dayAgo = Date.parse(data.generatedAt) - 86_400_000;
  const weekAgo = Date.parse(data.generatedAt) - 7 * 86_400_000;
  const last24h = data.signals.filter((signal) => Date.parse(signal.lastSeen) >= dayAgo).length;
  const last7d = data.signals.filter((signal) => Date.parse(signal.lastSeen) >= weekAgo).length;
  const feedRoot = `/data/brands/${slug}`;

  return (
    <div className="site-shell">
      <SiteHeader currentPage="brand" language={data.language} alternateHref={alternatePath} />
      <main className="permanent-page brand-activity-page" id="main-content">
        <nav className="breadcrumb" aria-label={lt ? "Naršymo kelias" : "Breadcrumb"}><a href={lt ? "/lt/prekes-zenklai/" : "/brands/"}>← {lt ? "Prekių ženklų registras" : "Brand registry"}</a><span>/</span><span>{data.brand.brand}</span></nav>
        <header className="profile-hero brand-profile-hero">
          <div><p className="eyebrow"><ShieldCheck aria-hidden="true" /> {lt ? "Aptikimo apimties centras" : "Detection scope hub"}</p><h1>{data.brand.brand}</h1><p>{lt ? "Viešas veiklos vaizdas pagal peržiūrėtą oficialių domenų ir pavadinimų apimtį." : "Public activity scoped to a reviewed set of official properties and names."}</p></div>
          <dl className="profile-summary"><div><dt>{lt ? "Kategorija" : "Category"}</dt><dd>{data.brand.category}</dd></div><div><dt>{lt ? "Dabartiniai kandidatai" : "Current candidates"}</dt><dd>{data.signals.length}</dd></div><div><dt>24h / 7d</dt><dd>{last24h} / {last7d}</dd></div><div><dt>{lt ? "Istoriniai įrašai" : "Historical records"}</dt><dd>{data.historyTotal ?? data.history.length}</dd></div></dl>
        </header>

        <section className="brand-hub-grid">
          <article className="profile-section">
            <p className="eyebrow">01 / {lt ? "Peržiūrėta apimtis" : "Reviewed scope"}</p><h2>{lt ? "Oficialios sritys" : "Official properties"}</h2>
            <div className="registry-values">{data.brand.officialDomains.map((domain) => <code key={domain}>{defangDomain(domain)}</code>)}</div>
            <h3>{lt ? "Aptikimo pavadinimai" : "Detection names"}</h3><div className="registry-values">{[...data.brand.aliases, ...(data.brand.fuzzyAliases ?? [])].map((alias) => <code key={alias}>{alias}</code>)}</div>
            <p className="boundary-note">{lt ? "Oficiali sritis slopinama prieš vertinimą. Įtraukimas į registrą nereiškia, kad prekės ženklas buvo atakuotas." : "Official properties are suppressed before scoring. Registry inclusion does not mean this brand was attacked."}</p>
          </article>
          <article className="profile-section feed-directory"><p className="eyebrow"><Rss aria-hidden="true" /> 02 / {lt ? "Srautai" : "Feeds"}</p><h2>{lt ? "Sekti šio prekės ženklo pokyčius" : "Follow this brand"}</h2><a href={`${feedRoot}/events.atom.xml`}>Atom</a><a href={`${feedRoot}/events.rss.xml`}>RSS 2.0</a><a href={`${feedRoot}/events.feed.json`}>JSON Feed</a><p>{lt ? "Srautuose pateikiami tik vieši, defanguoti, paskutinių 30 dienų įvykiai." : "Feeds contain bounded, defanged public events from the latest 30 days."}</p></article>
        </section>

        <section className="profile-section brand-candidates" aria-labelledby="brand-candidates-title"><div className="section-heading"><div><p className="eyebrow">03 / {lt ? "Signalai" : "Signals"}</p><h2 id="brand-candidates-title">{lt ? "Naujausi kandidatai" : "Recently observed candidates"}</h2></div><p>{data.signals.length} {lt ? "dabartiniai" : "current"}</p></div>
          {data.signals.length ? <div className="compact-signal-list">{data.signals.map((signal) => <article key={signal.id}><div><a href={signalPath(signal, data.language)}>{signal.domain}</a><span>{signal.sources.join(", ")} · {lt ? statusLt[signal.status] : signal.status}</span></div><strong>{signalMatchScore(signal)}/100</strong><time dateTime={signal.lastSeen}>{formatDateTime(signal.lastSeen)} UTC</time></article>)}</div> : <p className="empty-copy">{lt ? "Dabartiniame viešame lange kandidatų nėra." : "No candidates are present in the current public window."}</p>}
        </section>

        {(data.historyTotal ?? data.history.length) > data.history.length && <p className="boundary-note">{lt ? `Čia pateikiami ${data.history.length} naujausių įrašų iš ${data.historyTotal}. Visą išsaugotą istoriją rasite archyve.` : `Showing ${data.history.length} recent records of ${data.historyTotal}. The complete retained record remains in the history archive.`} <a href={lt ? "/lt/istorija/" : "/history/"}>{lt ? "Visa istorija" : "Complete history"} →</a></p>}
        <section className="profile-section brand-history" aria-labelledby="brand-history-title"><p className="eyebrow">04 / {lt ? "Istorija" : "History"}</p><h2 id="brand-history-title">{lt ? "Išsaugota veikla" : "Retained activity"}</h2>{data.history.length ? <ol className="signal-timeline">{data.history.map((record) => <li key={record.id}><time dateTime={record.lastSeen}>{formatDateTime(record.lastSeen)} UTC</time><a href={signalPath(record.id, data.language)}>{record.domain}</a><span>{record.observationCount} {lt ? "stebėjimų" : "observations"} · {lt ? statusLt[record.latestStatus] : record.latestStatus}</span></li>)}</ol> : <p>{lt ? "Viešoje istorijoje įrašų nėra." : "No records are present in public history."}</p>}</section>

        <section className="profile-section brand-sources"><p className="eyebrow">05 / {lt ? "Šaltiniai" : "Registry sources"}</p><h2>{lt ? "Tapatybės nuorodos" : "Identity references"}</h2><div className="source-link-list">{data.brand.sources.map((source) => <a href={source} target="_blank" rel="noreferrer noopener" key={source}>{new URL(source).hostname} <ExternalLink aria-hidden="true" /></a>)}</div><p className="boundary-note">{lt ? "Šaltiniai pagrindžia viešą prekės ženklo tapatybę ir oficialių domenų apimtį. Jie nėra įrodymai prieš kandidatą." : "Sources establish public brand identity and official-domain coverage. They are not evidence against a candidate."}</p></section>
      </main>
      <SiteFooter language={data.language} />
    </div>
  );
}
