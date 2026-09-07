import { Archive, Database, Filter, History, RotateCcw, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { formatDateTime, formatNumber, formatRelativeTime, sentenceCase } from "../lib/format.ts";
import { formatRelativeTimeLt, statusLt } from "../lt/formatLt.ts";
import { foldSearchText } from "../lib/searchText.ts";
import { signalPath } from "../lib/signalRoutes.ts";
import { trendFreshness } from "../lib/trendFreshness.ts";
import type { SiteLanguage } from "./SiteHeader.tsx";
import { SIGNAL_STATUSES, type RadarHistory, type SignalStatus } from "../types.ts";

const PAGE_SIZE = 25;

const reasonLabel = (value: string) => value.replaceAll("-", " ");

export function HistoryDashboard({ history, now = Date.now(), totalSignals = history.signals.length, language = "en" }: { history: RadarHistory; now?: number; totalSignals?: number; language?: SiteLanguage }) {
  const lt = language === "lt";
  const t = (en: string, translated: string) => lt ? translated : en;
  const relativeTime = lt ? formatRelativeTimeLt : formatRelativeTime;
  const statusLabel = (status: SignalStatus) => lt ? statusLt[status] : sentenceCase(status);
  const partial = totalSignals > history.signals.length;
  const [query, setQuery] = useState("");
  const [brand, setBrand] = useState("all");
  const [status, setStatus] = useState<SignalStatus | "all">("all");
  const [page, setPage] = useState(1);
  const brands = useMemo(
    () => [...new Set(history.signals.map((signal) => signal.brand))].sort((left, right) => left.localeCompare(right)),
    [history.signals],
  );
  const filtered = useMemo(() => {
    const needle = foldSearchText(query.trim());
    return history.signals.filter(
      (signal) =>
        (brand === "all" || signal.brand === brand) &&
        (status === "all" || signal.latestStatus === status) &&
        (!needle || foldSearchText(`${signal.domain} ${signal.brand} ${signal.sources.join(" ")}`).includes(needle)),
    );
  }, [brand, history.signals, query, status]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const observations = history.signals.reduce((total, signal) => total + signal.observationCount, 0);
  const transitions = history.signals.reduce((total, signal) => total + signal.statusTransitions.length, 0);

  useEffect(() => setPage(1), [brand, query, status]);
  useEffect(() => setPage((current) => Math.min(current, pages)), [pages]);

  return (
    <main id="main-content">
      <section className="hero history-hero" aria-labelledby="history-title">
        <div className="hero-grid" aria-hidden="true" />
        <div className="hero-copy">
          <p className="eyebrow"><History aria-hidden="true" /> {t("Reproducible provenance", "Atkuriama kilmė")}</p>
          <h1 id="history-title">{t("Candidate history.", "Kandidatų istorija.")}<br /><span>{t("Not a verdict log.", "Tai ne verdiktų žurnalas.")}</span></h1>
          <p className="hero-intro">{t("A bounded record of defanged candidate observations and explicit source-supplied status changes. Disappearance from the recent dashboard never means offline, benign, or mitigated.", "Ribotas neutralizuotų kandidatų stebėjimų ir aiškių šaltinių pateiktų būsenos pokyčių įrašas. Dingimas iš naujausios suvestinės nereiškia, kad svetainė neveikia, yra nekenksminga ar grėsmė pašalinta.")}</p>
          <div className="hero-actions">
            <a className="hero-action-primary" href="#history-records">{t("Browse history", "Naršyti istoriją")}</a>
            <a href={lt ? "/lt/metodologija/#istorija" : "/methodology/#history"}>{t("Read retention rules", "Duomenų saugojimo taisyklės")}</a>
          </div>
        </div>
        <div className={`freshness-card ${trendFreshness(history, now) === "current" ? "fresh" : "stale"}`}>
          <span className="live-dot" aria-hidden="true" />
          <div>
            <small>{t("History generated", "Istorija atnaujinta")}</small>
            <strong>{relativeTime(history.generatedAt, now)}</strong>
            <time dateTime={history.generatedAt}>{history.generatedAt}</time>
            <span>{history.detailRetentionDays} {t("days detail", "dienų detalūs duomenys")} · {history.summaryRetentionDays} {t("days summary", "dienų suvestinė")}</span>
          </div>
        </div>
      </section>

      <section className="metric-grid history-metrics" aria-label={t("History summary", "Istorijos suvestinė")}>
        <article className="metric-card"><Database aria-hidden="true" /><span>{t("Historical candidates", "Istoriniai kandidatai")}</span><strong>{formatNumber(history.signals.length)}</strong></article>
        <article className="metric-card"><Archive aria-hidden="true" /><span>{t("Observations retained", "Išsaugoti stebėjimai")}</span><strong>{formatNumber(observations)}</strong></article>
        <article className="metric-card"><ShieldCheck aria-hidden="true" /><span>{t("Explicit transitions", "Aiškūs būsenos perėjimai")}</span><strong>{formatNumber(transitions)}</strong></article>
      </section>

      {partial && <p role="status">{t(`Showing a bounded preview of ${history.signals.length} of ${totalSignals} retained records. Counts and filters describe only the loaded preview.`, `Rodoma ribota ${history.signals.length} įrašų peržiūra iš ${totalSignals}. Skaičiai ir filtrai taikomi tik įkeltai peržiūrai.`)} <a href="/data/history.json">{t("Complete history index", "Visa istorijos rodyklė")}</a>.</p>}

      <section className="signal-section" id="history-records" aria-labelledby="history-records-title">
        <div className="section-heading">
          <div><p className="eyebrow">{t("Historical index", "Istorijos rodyklė")}</p><h2 id="history-records-title">{t("Retained candidate trail", "Išsaugota kandidato eiga")}</h2></div>
          <p><strong>{formatNumber(filtered.length)}</strong> {t("matching", "atitinka")} / {formatNumber(history.signals.length)} {t("retained", "išsaugota")}</p>
        </div>
        <div className="filter-shell">
          <div className="search-field">
            <Search aria-hidden="true" />
            <label className="sr-only" htmlFor="history-search">{t("Search historical candidates", "Ieškoti istorinių kandidatų")}</label>
            <input id="history-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search domain, brand, or source", "Ieškoti domeno, prekės ženklo ar šaltinio")} />
          </div>
          <div className="select-group">
            <Filter aria-hidden="true" />
            <label className="sr-only" htmlFor="history-brand">{t("Filter by brand", "Filtruoti pagal prekės ženklą")}</label>
            <select id="history-brand" value={brand} onChange={(event) => setBrand(event.target.value)}>
              <option value="all">{t("All brands", "Visi prekių ženklai")}</option>
              {brands.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <label className="sr-only" htmlFor="history-status">{t("Filter by latest status", "Filtruoti pagal naujausią būseną")}</label>
            <select id="history-status" value={status} onChange={(event) => setStatus(event.target.value as SignalStatus | "all")}>
              <option value="all">{t("All latest statuses", "Visos naujausios būsenos")}</option>
              {SIGNAL_STATUSES.map((value) => <option key={value} value={value}>{statusLabel(value)}</option>)}
            </select>
            <button className="reset-button" type="button" onClick={() => { setQuery(""); setBrand("all"); setStatus("all"); }}>
              <RotateCcw aria-hidden="true" /> Reset
            </button>
          </div>
        </div>

        {visible.length === 0 ? (
          <div className="empty-state"><h3>{t("No matching history", "Atitinkančių istorinių įrašų nėra")}</h3><p>{t("Adjust the filters to widen the retained record set.", "Pakeiskite filtrus, kad būtų rodoma daugiau išsaugotų įrašų.")}</p></div>
        ) : (
          <div className="table-panel">
            <div className="table-scroll" role="region" aria-label={t("Historical candidate observations", "Istoriniai kandidatų stebėjimai")} tabIndex={0}>
              <table className="history-table">
                <thead><tr><th scope="col">{t("Indicator", "Indikatorius")}</th><th scope="col">{t("Target", "Prekės ženklas")}</th><th scope="col">{t("Sources", "Šaltiniai")}</th><th scope="col">{t("Latest status", "Naujausia būsena")}</th><th scope="col">{t("Observed", "Stebėta")}</th><th scope="col">{t("Provenance", "Kilmė")}</th></tr></thead>
                <tbody>
                  {visible.map((signal) => (
                    <tr key={signal.id}>
                      <td className="indicator-cell" data-label={t("Indicator", "Indikatorius")}><a href={signalPath(signal.id, language)}><code>{signal.domain}</code></a><span>ID {signal.id}</span></td>
                      <td data-label={t("Target", "Prekės ženklas")}><strong className="brand-target">{signal.brand}</strong></td>
                      <td data-label={t("Sources", "Šaltiniai")}><div className="source-chips">{signal.sources.map((source) => <span key={source}>{source}</span>)}</div></td>
                      <td data-label={t("Latest status", "Naujausia būsena")}><span className={`status-pill ${signal.latestStatus}`}><i aria-hidden="true" />{statusLabel(signal.latestStatus)}</span></td>
                      <td data-label={t("Observed", "Stebėta")}><time dateTime={signal.lastSeen} title={formatDateTime(signal.lastSeen)}>{relativeTime(signal.lastSeen, now)}</time><span className="first-seen">{t("First", "Pirmą kartą")} {relativeTime(signal.firstSeen, now)} · {signal.observationCount} {t("observations", "stebėjimų")}</span></td>
                      <td data-label={t("Provenance", "Kilmė")}>
                        <details className="history-provenance">
                          <summary>{signal.reasonCodes.length} {t("reasons", "priežasčių")} · {signal.statusTransitions.length} {t("transitions", "perėjimų")}</summary>
                          <ul>{signal.reasonCodes.map((reason) => <li key={reason}>{reasonLabel(reason)}</li>)}</ul>
                          {signal.statusTransitions.map((transition) => (
                            <p key={transition.eventId}><time dateTime={transition.observedAt}>{formatDateTime(transition.observedAt)}</time>: {transition.previousStatus ? statusLabel(transition.previousStatus) : t("First publication", "Pirma publikacija")} → {statusLabel(transition.status)}</p>
                          ))}
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              <p>{t("Showing", "Rodoma")} <strong>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)}</strong> {t("of", "iš")} {filtered.length}</p>
              <div><button type="button" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>{t("Previous", "Ankstesnis")}</button><span>{t("Page", "Puslapis")} <strong>{page}</strong> {t("of", "iš")} {pages}</span><button type="button" disabled={page === pages} onClick={() => setPage((value) => value + 1)}>{t("Next", "Kitas")}</button></div>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
