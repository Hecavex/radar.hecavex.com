import { Activity, ArrowDown, ArrowRight, Clock3, Database, Radar, ShieldCheck, Waypoints } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { controlledFilterSearch, dashboardMetrics, DEFAULT_FILTERS, filterSignals, filtersFromSearch, sortSignals } from "../lib/dashboard.ts";
import { formatDateTime, formatNumber, formatRelativeTime } from "../lib/format.ts";
import { formatDateTimeLt, formatNumberLt, formatRelativeTimeLt } from "../lt/formatLt.ts";
import type { Filters, RadarSnapshot } from "../types.ts";
import { CollectionDisclosure } from "./CollectionDisclosure.tsx";
import { ExportActions } from "./ExportActions.tsx";
import { FilterBar } from "./FilterBar.tsx";
import { SignalTable } from "./SignalTable.tsx";
import type { SiteLanguage } from "./SiteHeader.tsx";

export function Dashboard({ snapshot, now = Date.now(), language = "en", refreshError = null }: {
  snapshot: RadarSnapshot;
  now?: number;
  language?: SiteLanguage;
  refreshError?: string | null;
}) {
  const lt = language === "lt";
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [urlStateReady, setUrlStateReady] = useState(false);
  const summary = useMemo(() => dashboardMetrics(snapshot), [snapshot]);
  const filteredSignals = useMemo(() => sortSignals(filterSignals(snapshot.signals, filters, now), filters.sort), [snapshot.signals, filters, now]);
  const syncAgeMs = now - Date.parse(snapshot.lastSuccessfulSyncAt);
  const invalidClock = !Number.isFinite(syncAgeMs) || syncAgeMs < -60_000;
  const isStale = refreshError !== null || invalidClock || syncAgeMs > 2 * 60 * 60 * 1000;
  const dayAgo = now - 86_400_000;
  const newToday = snapshot.signals.filter((signal) => Date.parse(signal.firstSeen) >= dayAgo).length;
  const reobservedToday = snapshot.signals.filter((signal) => Date.parse(signal.firstSeen) < dayAgo && Date.parse(signal.lastSeen) >= dayAgo).length;
  const number = lt ? formatNumberLt : formatNumber;
  const relativeTime = lt ? formatRelativeTimeLt : formatRelativeTime;
  const dateTime = lt ? formatDateTimeLt : formatDateTime;
  const signalsAnchor = lt ? "signalai" : "signals";

  useEffect(() => {
    const updateFromLocation = () => {
      setFilters((current) => ({ ...filtersFromSearch(window.location.search, snapshot.signals), query: current.query }));
      setUrlStateReady(true);
    };
    updateFromLocation();
    window.addEventListener("popstate", updateFromLocation);
    return () => window.removeEventListener("popstate", updateFromLocation);
  }, [snapshot.signals]);

  useEffect(() => {
    if (!urlStateReady) return;
    const query = controlledFilterSearch(filters);
    window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
  }, [filters, urlStateReady]);

  const updateFacet = (key: "brand" | "source" | "country", value: string) => setFilters((current) => ({ ...current, [key]: value }));

  return (
    <main id="main-content">
      <section className="hero radar-hero" aria-labelledby="radar-title">
        <div className="hero-grid" aria-hidden="true" />
        <div className="hero-copy">
          <p className="eyebrow"><Radar aria-hidden="true" /> {lt ? "Atviroji grėsmių žvalgyba · Lietuva" : "Open threat intelligence · Lithuania"}</p>
          <h1 id="radar-title">
            {lt ? <>Phishing signalai.<br /><span>Pastebėti, ne numanomi.</span></> : <>Phishing signals.<br /><span>Observed, not assumed.</span></>}
          </h1>
          <p className="hero-intro">
            {lt
              ? "Neutralizuoti galimi phishing ir apsimetimo domenai, aptikti atrankiniu būdu stebint Certificate Transparency, URLScan ir naudojant saugiai parengtus HECAVEX duomenis. Kiekviena eilutė yra tyrimo kryptis, o ne nuosprendis."
              : "Defanged potential phishing and impersonation domains discovered through sampled Certificate Transparency, URLScan, and sanitized HECAVEX inputs. Every row is a lead, never a verdict."}
          </p>
          <div className="hero-actions">
            <a className="hero-action-primary" href={`#${signalsAnchor}`}><ArrowDown aria-hidden="true" /> {lt ? `Peržiūrėti ${number(summary.total)} kandidatų` : `Browse ${number(summary.total)} candidates`}</a>
            <a href={lt ? "/lt/metodologija/" : "/methodology/"}>{lt ? "Kaip renkami duomenys" : "How collection works"}</a>
          </div>
        </div>
        <aside
          className={`freshness-card ${isStale ? "stale" : "fresh"}`}
          aria-label={lt ? "Suvestinės šviežumas" : "Snapshot freshness"}
          aria-live={refreshError ? "polite" : undefined}
        >
          <span className="live-dot" aria-hidden="true" />
          <div>
            <small>
              {refreshError
                ? (lt ? "Atnaujinimas nepasiekiamas · rodoma įterpta suvestinė" : "Refresh unavailable · showing embedded snapshot")
                : lt
                  ? (isStale ? "Suvestinės sinchronizavimas vėluoja" : "Suvestinė atnaujinta")
                  : (isStale ? "Snapshot sync delayed" : "Snapshot current")}
            </small>
            <strong>{invalidClock ? (lt ? "Nežinomas arba ateities laikas" : "Unknown or future timestamp") : relativeTime(snapshot.lastSuccessfulSyncAt, now)}</strong>
            <button type="button" className="button" onClick={() => window.location.reload()}>{lt ? "Atnaujinti suvestinę" : "Refresh snapshot"}</button>
            <span>{lt ? `Paskutinis sėkmingas sinchronizavimas ${dateTime(snapshot.lastSuccessfulSyncAt)} Lietuvos laiku` : `Last successful sync ${dateTime(snapshot.lastSuccessfulSyncAt)} UTC`}</span>
            <span>{lt ? `Duomenys pasikeitė ${relativeTime(snapshot.generatedAt, now)}` : `Data changed ${relativeTime(snapshot.generatedAt, now)}`}</span>
            {refreshError ? <span>{lt ? "Atnaujinimo įspėjimas" : "Refresh warning"}: {refreshError}</span> : null}
          </div>
        </aside>
      </section>

      <section className="activity-strip" aria-label={lt ? "Dabartinė Radaro veikla" : "Current Radar activity"}>
        <div><Database aria-hidden="true" /><span>{lt ? "Dabartiniai kandidatai" : "Current candidates"}</span><strong>{number(summary.total)}</strong></div>
        <div><Clock3 aria-hidden="true" /><span>{lt ? "Pirmos publikacijos per 24 val." : "First published 24h"}</span><strong>{number(newToday)}</strong></div>
        <div><Activity aria-hidden="true" /><span>{lt ? "Pakartotinai stebėti per 24 val." : "Reobserved 24h"}</span><strong>{number(reobservedToday)}</strong></div>
        <div><ShieldCheck aria-hidden="true" /><span>{lt ? "Galimi prekių ženklai" : "Potential brands"}</span><strong>{number(summary.brands)}</strong></div>
        <a href={lt ? "/lt/pokyciai/" : "/changes/"}><span>{lt ? "Visas įvykių žurnalas" : "Full event record"}</span><strong>{lt ? "Pokyčiai" : "Changes"} <ArrowRight aria-hidden="true" /></strong></a>
      </section>

      <section className="signal-section" id={signalsAnchor} aria-labelledby="signals-title">
        <div className="section-heading">
          <div><p className="eyebrow">{lt ? "Dabartinis signalų langas" : "Current signal window"}</p><h2 id="signals-title">{lt ? "Neseniai pastebėti kandidatai" : "Recently observed candidates"}</h2></div>
          <div className="signal-heading-actions"><p>{lt ? <><strong>{number(filteredSignals.length)}</strong> atitinka iš {number(snapshot.signals.length)}</> : <><strong>{number(filteredSignals.length)}</strong> matching {number(snapshot.signals.length)}</>}</p><ExportActions signals={filteredSignals} snapshotGeneratedAt={snapshot.generatedAt} language={language} /></div>
        </div>
        <FilterBar signals={snapshot.signals} filters={filters} onChange={setFilters} language={language} />
        <SignalTable signals={filteredSignals} now={now} snapshotGeneratedAt={snapshot.generatedAt} onFacet={updateFacet} language={language} />
      </section>

      <section className="radar-route-grid" aria-label={lt ? "Naršyti Radarą" : "Explore Radar"}>
        <a href={lt ? "/lt/pokyciai/" : "/changes/"}><Clock3 aria-hidden="true" /><span><strong>{lt ? "Pokyčiai" : "Changes"}</strong><small>{lt ? "Nauji, pakartotinai stebėti, pakeisti arba atšaukti" : "New, reobserved, changed, or retracted"}</small></span><ArrowRight aria-hidden="true" /></a>
        <a href={lt ? "/lt/tendencijos/" : "/trends/"}><Activity aria-hidden="true" /><span><strong>{lt ? "Tendencijos ir kokybė" : "Trends and quality"}</strong><small>{lt ? "Skaičiai pateikiami kartu su rinktuvų aprėptimi" : "Counts shown beside collector coverage"}</small></span><ArrowRight aria-hidden="true" /></a>
        <a href={lt ? "/lt/sasajos/" : "/associations/"}><Waypoints aria-hidden="true" /><span><strong>{lt ? "Sąsajos" : "Associations"}</strong><small>{lt ? "Tirti ribotus bendrus įrodymus" : "Inspect bounded shared evidence"}</small></span><ArrowRight aria-hidden="true" /></a>
        <a href={lt ? "/lt/irankiai/" : "/tools/"}><ShieldCheck aria-hidden="true" /><span><strong>{lt ? "Vietinė IOC patikra" : "Local IOC check"}</strong><small>{lt ? "Palyginti reikšmes jų neįkeliant" : "Compare values without uploading them"}</small></span><ArrowRight aria-hidden="true" /></a>
      </section>

      <CollectionDisclosure language={language} />
    </main>
  );
}
