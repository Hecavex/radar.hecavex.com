import { Archive, CalendarClock, Rss } from "lucide-react";
import { useState } from "react";
import { ArtifactHero, PageShell, type StaticPageLanguage } from "../components/ArtifactPageShell.tsx";
import { formatEventDateTime } from "../lib/staticPageFormat.ts";
import { signalPath } from "../lib/signalRoutes.ts";
import type { StaticPageData } from "../lib/staticPageBootstrap.ts";

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
      <div className="filter-shell event-filters">
        <label>
          <span>{lt ? "Įvykio tipas" : "Event type"}</span>
          <select value={type} onChange={(event) => { setType(event.target.value); setPage(1); }}>
            <option value="all">{lt ? "Visi tipai" : "All types"}</option>
            {Object.entries(typeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          <span>{lt ? "Prekės ženklas" : "Brand"}</span>
          <select value={brand} onChange={(event) => { setBrand(event.target.value); setPage(1); }}>
            <option value="all">{lt ? "Visi prekių ženklai" : "All brands"}</option>
            {brands.map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label>
          <span>{lt ? "Nuo datos (UTC)" : "Since date (UTC)"}</span>
          <input type="date" value={since} onChange={(event) => { setSince(event.target.value); setPage(1); }} />
        </label>
      </div>
      <p role="status">{lt ? `Atitinka ${filtered.length}; rodoma ${visible.length}. Įkelta ${data.events.events.length} iš ${data.events.totalAvailable}.` : `${filtered.length} matching; ${visible.length} shown. Loaded ${data.events.events.length} of ${data.events.totalAvailable}.`} {lt ? "Duomenų riba" : "Artifact cutoff"}: {formatEventDateTime(data.events.generatedAt, language)} UTC. {data.events.truncated ? (lt ? "Šaltinio sąrašas sutrumpintas; filtrai taikomi tik įkeltiems įvykiams." : "The upstream list is truncated; filters apply only to loaded events.") : null}</p>
      <ol className="event-list">{visible.map((event) => <li key={event.id}><time dateTime={event.occurredAt}>{formatEventDateTime(event.occurredAt, language)} UTC</time><span className={`event-type ${event.type}`}>{typeLabels[event.type]}</span><div><a href={signalPath(event.signalId, language)}>{event.domain}</a><span>{event.brand} · {event.sources.join(", ")}</span></div>{event.type === "status-change" ? <small>{event.previousStatus} → {event.status}</small> : null}</li>)}</ol>
      <div className="pagination"><button type="button" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>{lt ? "Ankstesnis" : "Previous"}</button><span>{lt ? "Puslapis" : "Page"} {page} / {pages}</span><button type="button" disabled={page === pages} onClick={() => setPage((value) => value + 1)}>{lt ? "Kitas" : "Next"}</button></div>
      {!filtered.length ? <div className="empty-copy" role="status">
        <p>{!data.events.events.length
          ? (lt ? "Dabartiniame viešame lange įvykių nėra." : "No event falls inside the current public window.")
          : (lt ? "Pasirinktus filtrus atitinkančių įvykių nėra. Pakeiskite filtrus arba juos išvalykite." : "No events match these filters. Broaden your selection or clear the filters.")}</p>
        {data.events.events.length > 0 ? <button className="button" type="button" onClick={() => { setType("all"); setBrand("all"); setSince(""); setPage(1); }}>{lt ? "Išvalyti filtrus" : "Clear filters"}</button> : null}
      </div> : null}
    </section>
    <section className="related-route-card"><div><p className="eyebrow"><Archive aria-hidden="true" /> {lt ? "Išsaugotas archyvas" : "Retained archive"}</p><h2>{lt ? "Reikia visos kandidato laiko juostos?" : "Need the full candidate timeline?"}</h2><p>{lt ? "Istorijos vaizde saugomas ribotas pirmo ir paskutinio stebėjimo laikas, stebėjimų skaičius ir būsenos perėjimai už šio srauto lango ribų." : "The history view preserves bounded first-seen, last-seen, observation counts and status transitions beyond this feed window."}</p></div><a href={lt ? "/lt/istorija/" : "/history/"}>{lt ? "Atverti kandidatų istoriją" : "Open candidate history"} →</a></section>
  </PageShell>;
}
