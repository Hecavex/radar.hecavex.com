import { Archive, Database, Filter, History, RotateCcw, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { formatDateTime, formatNumber, formatRelativeTime, sentenceCase } from "../lib/format.ts";
import { foldSearchText } from "../lib/searchText.ts";
import { SIGNAL_STATUSES, type RadarHistory, type SignalStatus } from "../types.ts";

const PAGE_SIZE = 25;

const reasonLabel = (value: string) => value.replaceAll("-", " ");

export function HistoryDashboard({ history, now = Date.now(), totalSignals = history.signals.length }: { history: RadarHistory; now?: number; totalSignals?: number }) {
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
          <p className="eyebrow"><History aria-hidden="true" /> Reproducible provenance</p>
          <h1 id="history-title">Candidate history.<br /><span>Not a verdict log.</span></h1>
          <p className="hero-intro">
            A bounded record of defanged candidate observations and explicit source-supplied status changes. Disappearance
            from the recent dashboard never means offline, benign, or mitigated.
          </p>
          <div className="hero-actions">
            <a className="hero-action-primary" href="#history-records">Browse history</a>
            <a href="/methodology/#history">Read retention rules</a>
          </div>
        </div>
        <div className="freshness-card fresh">
          <span className="live-dot" aria-hidden="true" />
          <div>
            <small>History generated</small>
            <strong>{formatRelativeTime(history.generatedAt, now)}</strong>
            <span>{history.detailRetentionDays} days detail · {history.summaryRetentionDays} days summary</span>
          </div>
        </div>
      </section>

      <section className="metric-grid history-metrics" aria-label="History summary">
        <article className="metric-card"><Database aria-hidden="true" /><span>Historical candidates</span><strong>{formatNumber(history.signals.length)}</strong></article>
        <article className="metric-card"><Archive aria-hidden="true" /><span>Observations retained</span><strong>{formatNumber(observations)}</strong></article>
        <article className="metric-card"><ShieldCheck aria-hidden="true" /><span>Explicit transitions</span><strong>{formatNumber(transitions)}</strong></article>
      </section>

      {partial && <p role="status">Showing a bounded preview of {history.signals.length} of {totalSignals} retained records. Counts and filters above describe the loaded preview. The complete verified history loads in this browser. <a href="/data/history.json">Download the complete history index</a>.</p>}

      <section className="signal-section" id="history-records" aria-labelledby="history-records-title">
        <div className="section-heading">
          <div><p className="eyebrow">Historical index</p><h2 id="history-records-title">Retained candidate trail</h2></div>
          <p><strong>{formatNumber(filtered.length)}</strong> matching {formatNumber(history.signals.length)} retained</p>
        </div>
        <div className="filter-shell">
          <div className="search-field">
            <Search aria-hidden="true" />
            <label className="sr-only" htmlFor="history-search">Search historical candidates</label>
            <input id="history-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search domain, brand, or source" />
          </div>
          <div className="select-group">
            <Filter aria-hidden="true" />
            <label className="sr-only" htmlFor="history-brand">Filter by brand</label>
            <select id="history-brand" value={brand} onChange={(event) => setBrand(event.target.value)}>
              <option value="all">All brands</option>
              {brands.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <label className="sr-only" htmlFor="history-status">Filter by latest status</label>
            <select id="history-status" value={status} onChange={(event) => setStatus(event.target.value as SignalStatus | "all")}>
              <option value="all">All latest statuses</option>
              {SIGNAL_STATUSES.map((value) => <option key={value} value={value}>{sentenceCase(value)}</option>)}
            </select>
            <button className="reset-button" type="button" onClick={() => { setQuery(""); setBrand("all"); setStatus("all"); }}>
              <RotateCcw aria-hidden="true" /> Reset
            </button>
          </div>
        </div>

        {visible.length === 0 ? (
          <div className="empty-state"><h3>No matching history</h3><p>Adjust the filters to widen the retained record set.</p></div>
        ) : (
          <div className="table-panel">
            <div className="table-scroll" role="region" aria-label="Historical candidate observations" tabIndex={0}>
              <table className="history-table">
                <thead><tr><th scope="col">Indicator</th><th scope="col">Target</th><th scope="col">Sources</th><th scope="col">Latest status</th><th scope="col">Observed</th><th scope="col">Provenance</th></tr></thead>
                <tbody>
                  {visible.map((signal) => (
                    <tr key={signal.id}>
                      <td className="indicator-cell" data-label="Indicator"><code>{signal.domain}</code><span>ID {signal.id}</span></td>
                      <td data-label="Target"><strong className="brand-target">{signal.brand}</strong></td>
                      <td data-label="Sources"><div className="source-chips">{signal.sources.map((source) => <span key={source}>{source}</span>)}</div></td>
                      <td data-label="Latest status"><span className={`status-pill ${signal.latestStatus}`}><i aria-hidden="true" />{sentenceCase(signal.latestStatus)}</span></td>
                      <td data-label="Observed"><time dateTime={signal.lastSeen} title={formatDateTime(signal.lastSeen)}>{formatRelativeTime(signal.lastSeen, now)}</time><span className="first-seen">First {formatRelativeTime(signal.firstSeen, now)} · {signal.observationCount} observation{signal.observationCount === 1 ? "" : "s"}</span></td>
                      <td data-label="Provenance">
                        <details className="history-provenance">
                          <summary>{signal.reasonCodes.length} reason{signal.reasonCodes.length === 1 ? "" : "s"} · {signal.statusTransitions.length} transition{signal.statusTransitions.length === 1 ? "" : "s"}</summary>
                          <ul>{signal.reasonCodes.map((reason) => <li key={reason}>{reasonLabel(reason)}</li>)}</ul>
                          {signal.statusTransitions.map((transition) => (
                            <p key={transition.eventId}><time dateTime={transition.observedAt}>{formatDateTime(transition.observedAt)}</time>: {transition.previousStatus ? sentenceCase(transition.previousStatus) : "First publication"} → {sentenceCase(transition.status)}</p>
                          ))}
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              <p>Showing <strong>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)}</strong> of {filtered.length}</p>
              <div><button type="button" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>Page <strong>{page}</strong> of {pages}</span><button type="button" disabled={page === pages} onClick={() => setPage((value) => value + 1)}>Next</button></div>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
