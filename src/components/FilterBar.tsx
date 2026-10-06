import { Check, RotateCcw, Search, Share2, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { controlledFilterSearch, DEFAULT_FILTERS, sourceNames, uniqueValues } from "../lib/dashboard.ts";
import { statusLt } from "../lt/formatLt.ts";
import type { Filters, RadarSignal, SignalStatus } from "../types.ts";
import type { SiteLanguage } from "./SiteHeader.tsx";

const timeFilters: Array<{ value: Filters["timeRange"]; en: string; lt: string }> = [
  { value: "24h", en: "24 hours", lt: "24 val." },
  { value: "3d", en: "3 days", lt: "3 d." },
  { value: "7d", en: "7 days", lt: "7 d." },
  { value: "all", en: "All retained", lt: "Visas laikotarpis" },
];

const englishStatuses: Record<SignalStatus, string> = {
  active: "Active",
  suspected: "Suspected",
  offline: "Offline",
  mitigated: "Mitigated",
  unknown: "Unknown",
};

export function FilterBar({
  signals,
  filters,
  onChange,
  language = "en",
}: {
  signals: RadarSignal[];
  filters: Filters;
  onChange: (filters: Filters) => void;
  language?: SiteLanguage;
}) {
  const lt = language === "lt";
  const searchRef = useRef<HTMLInputElement>(null);
  const [copiedView, setCopiedView] = useState(false);
  const [copyFailureUrl, setCopyFailureUrl] = useState<string | null>(null);
  const brands = uniqueValues(signals, "brand");
  const countries = uniqueValues(signals, "country");
  const sources = sourceNames(signals);
  const hasFilters = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);

  const update = <Key extends keyof Filters>(key: Key, value: Filters[Key]) => onChange({ ...filters, [key]: value });

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.key === "/" && !target?.matches("input, textarea, select")) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    document.addEventListener("keydown", focusSearch);
    return () => document.removeEventListener("keydown", focusSearch);
  }, []);

  const copyControlledView = async () => {
    const query = controlledFilterSearch(filters);
    const url = `${window.location.origin}${window.location.pathname}${query ? `?${query}` : ""}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopyFailureUrl(null);
      setCopiedView(true);
      window.setTimeout(() => setCopiedView(false), 1800);
    } catch {
      setCopiedView(false);
      setCopyFailureUrl(url);
    }
  };

  return (
    <div className="filter-shell">
      <div className="quick-filter-row">
        <span>{lt ? "Paskutinis stebėjimas" : "Last seen"}</span>
        <div aria-label={lt ? "Paskutinio stebėjimo laikotarpis" : "Last-seen time window"}>
          {timeFilters.map((item) => (
            <button
              key={item.value}
              type="button"
              className={filters.timeRange === item.value ? "active" : undefined}
              aria-pressed={filters.timeRange === item.value}
              onClick={() => update("timeRange", item.value)}
            >
              {lt ? item.lt : item.en}
            </button>
          ))}
        </div>
      </div>
      <div className="search-field">
        <Search aria-hidden="true" />
        <label className="sr-only" htmlFor="signal-search">{lt ? "Ieškoti kandidatų" : "Search candidates"}</label>
        <input
          ref={searchRef}
          id="signal-search"
          type="search"
          placeholder={lt ? "Ieškoti neutralizuoto URL, domeno, prekių ženklo ar prieglobos..." : "Search defanged URL, domain, brand or host..."}
          value={filters.query}
          onChange={(event) => update("query", event.target.value)}
        />
        <kbd>/</kbd>
      </div>
      <details className="advanced-filter-shell" open={hasFilters || undefined}>
        <summary><SlidersHorizontal aria-hidden="true" /> {lt ? "Išplėstiniai filtrai" : "Advanced filters"} {hasFilters ? <span>{lt ? "Aktyvūs" : "Active"}</span> : null}</summary>
        <div className="select-group" aria-label={lt ? "Kandidatų filtrai" : "Candidate filters"}>
          <label>
            <span>{lt ? "Šaltinio nurodyta būsena" : "Source-reported status"}</span>
            <select aria-label={lt ? "Šaltinio nurodyta būsena" : "Source-reported status"} value={filters.status} onChange={(event) => update("status", event.target.value as SignalStatus | "all")}>
              <option value="all">{lt ? "Visos būsenos" : "All statuses"}</option>
              {(Object.keys(englishStatuses) as SignalStatus[]).map((status) => <option key={status} value={status}>{lt ? statusLt[status] : englishStatuses[status]}</option>)}
            </select>
          </label>
          <label>
            <span>{lt ? "Šaltinis" : "Source"}</span>
            <select aria-label={lt ? "Šaltinis" : "Source"} value={filters.source} onChange={(event) => update("source", event.target.value)}>
              <option value="all">{lt ? "Visi šaltiniai" : "All sources"}</option>
              {sources.map((source) => <option key={source} value={source}>{source}</option>)}
            </select>
          </label>
          <label>
            <span>{lt ? "Galimas prekių ženklo atitikmuo" : "Potential brand match"}</span>
            <select aria-label={lt ? "Galimas prekių ženklo atitikmuo" : "Potential brand match"} value={filters.brand} onChange={(event) => update("brand", event.target.value)}>
              <option value="all">{lt ? "Visi galimi prekių ženklai" : "All brand matches"}</option>
              {brands.map((brand) => <option key={brand} value={brand}>{brand}</option>)}
            </select>
          </label>
          <label>
            <span>{lt ? "Stebėta prieglobos šalis" : "Hosting country observed"}</span>
            <select aria-label={lt ? "Stebėta prieglobos šalis" : "Hosting country observed"} value={filters.country} onChange={(event) => update("country", event.target.value)}>
              <option value="all">{lt ? "Visos prieglobos šalys" : "All hosting countries"}</option>
              {countries.map((country) => <option key={country} value={country}>{country}</option>)}
            </select>
          </label>
          <label>
            <span>{lt ? "Mažiausias atitikties balas" : "Minimum match score"}</span>
            <select
              aria-label={lt ? "Mažiausias atitikties balas" : "Minimum match score"}
              value={filters.minimumMatchScore}
              onChange={(event) => update("minimumMatchScore", Number(event.target.value))}
            >
              <option value="0">{lt ? "Bet koks atitikties balas" : "Any match score"}</option>
              {[50, 75, 90].map((score) => <option key={score} value={score}>{lt ? `Atitikties balas ${score}+` : `Match score ${score}+`}</option>)}
            </select>
          </label>
          <label>
            <span>{lt ? "Įrodymai" : "Evidence"}</span>
            <select aria-label={lt ? "Įrodymai" : "Evidence"} value={filters.evidence} onChange={(event) => update("evidence", event.target.value as Filters["evidence"])}>
              <option value="all">{lt ? "Visi įrodymų lygiai" : "All evidence"}</option>
              <option value="name-only">{lt ? "Tik stebėta" : "Observed only"}</option>
              <option value="corroborated">{lt ? "Patvirtinta papildomu šaltiniu" : "Corroborated"}</option>
              <option value="reviewed">{lt ? "Peržiūrėta analitiko" : "Analyst reviewed"}</option>
              <option value="screenshot">{lt ? "Yra ekrano kopija" : "Has screenshot"}</option>
              <option value="urlscan">{lt ? "Yra URLScan kontekstas" : "Has URLScan context"}</option>
              <option value="hashes">{lt ? "Yra atsako kontrolinių sumų" : "Has response hashes"}</option>
              <option value="certstream-only">{lt ? "Tik CertStream" : "CertStream only"}</option>
            </select>
          </label>
          <label>
            <span>{lt ? "Rikiuoti kandidatus" : "Sort candidates"}</span>
            <select aria-label={lt ? "Rikiuoti kandidatus" : "Sort candidates"} value={filters.sort} onChange={(event) => update("sort", event.target.value as Filters["sort"])}>
              <option value="last-seen-desc">{lt ? "Naujausias stebėjimas" : "Newest observation"}</option>
              <option value="first-seen-desc">{lt ? "Naujausias aptikimas" : "Newest discovery"}</option>
              <option value="match-score-desc">{lt ? "Didžiausias atitikties balas" : "Highest match score"}</option>
              <option value="brand-asc">{lt ? "Prekių ženklas A–Ž" : "Brand A-Z"}</option>
            </select>
          </label>
          <button className="share-filter-button" type="button" onClick={() => void copyControlledView()}>
            {copiedView ? <Check aria-hidden="true" /> : <Share2 aria-hidden="true" />}
            {copiedView ? (lt ? "Nuoroda nukopijuota" : "View copied") : (lt ? "Kopijuoti filtruotos peržiūros nuorodą" : "Copy filtered view")}
          </button>
          {hasFilters && (
            <button className="reset-button" type="button" onClick={() => onChange(DEFAULT_FILTERS)}>
              <RotateCcw aria-hidden="true" /> {lt ? "Išvalyti filtrus" : "Reset"}
            </button>
          )}
        </div>
      </details>
      <p className="filter-privacy-note">{lt ? "Paieškos tekstas lieka šioje naršyklėje ir nėra pridedamas prie bendrinamo URL." : "Free-text search stays in this browser and is never added to the shared URL."}</p>
      {copyFailureUrl ? <div className="filter-copy-fallback" role="status">
        <label htmlFor="filtered-view-url">{lt ? "Kopijuoti nepavyko. Pažymėkite ir nukopijuokite nuorodą rankiniu būdu." : "Copy failed. Select and copy this filtered-view link manually."}</label>
        <input id="filtered-view-url" readOnly value={copyFailureUrl} onFocus={(event) => event.currentTarget.select()} />
      </div> : null}
    </div>
  );
}
