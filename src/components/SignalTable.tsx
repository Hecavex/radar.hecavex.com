import { Check, ChevronLeft, ChevronRight, Copy, FileSearch, Link2, SearchX } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { brandPath } from "../lib/brandRegistry.ts";
import { evidenceTierLabel, signalEvidenceTier, signalMatchScore } from "../lib/dashboard.ts";
import { formatDateTime, formatRelativeTime, sentenceCase } from "../lib/format.ts";
import { signalPath } from "../lib/signalRoutes.ts";
import { formatDateTimeLt, formatRelativeTimeLt, statusLt } from "../lt/formatLt.ts";
import type { RadarSignal } from "../types.ts";
import { ScreenshotModal } from "./ScreenshotModal.tsx";
import type { SiteLanguage } from "./SiteHeader.tsx";

const PAGE_SIZE = 12;

interface DetailState {
  signal: RadarSignal;
  trigger: HTMLButtonElement;
}

function MatchScore({ signal, language }: { signal: RadarSignal; language: SiteLanguage }) {
  const value = signalMatchScore(signal);
  const level = value >= 80 ? "high" : value >= 50 ? "medium" : "low";
  const lt = language === "lt";
  return <span className={`confidence ${level}`} aria-label={lt ? `${value} atitikties balų iš 100` : `${value} match score out of 100`}><span>{value}</span><small>{lt ? "/100 atitiktis" : "/100 match"}</small></span>;
}

export function SignalTable({ signals, now = Date.now(), snapshotGeneratedAt, onFacet, language = "en" }: {
  signals: RadarSignal[];
  now?: number;
  snapshotGeneratedAt: string;
  onFacet: (key: "brand" | "source" | "country", value: string) => void;
  language?: SiteLanguage;
}) {
  const lt = language === "lt";
  const [page, setPage] = useState(1);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [copyFailure, setCopyFailure] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailState | null>(null);
  const pages = Math.max(1, Math.ceil(signals.length / PAGE_SIZE));
  const relativeTime = lt ? formatRelativeTimeLt : formatRelativeTime;
  const dateTime = lt ? formatDateTimeLt : formatDateTime;

  useEffect(() => setPage((current) => Math.min(current, pages)), [pages]);
  const pageSignals = useMemo(() => signals.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), [signals, page]);

  const copy = async (signal: RadarSignal) => {
    try {
      await navigator.clipboard.writeText(signal.url);
      setCopyFailure(null);
      setCopiedId(signal.id);
      window.setTimeout(() => setCopiedId(null), 1400);
    } catch {
      setCopiedId(null);
      setCopyFailure(signal.url);
    }
  };
  const closeDetail = useCallback(() => setDetail(null), []);

  if (!signals.length) return <div className="empty-state"><SearchX aria-hidden="true" /><h3>{lt ? "Atitinkančių kandidatų nėra" : "No matching candidates"}</h3><p>{lt ? "Pakeiskite paiešką arba filtrus, kad būtų rodoma daugiau rezultatų." : "Adjust the local search or controlled filters to widen the view."}</p></div>;

  return <div className="table-panel">
    {copyFailure && <div role="status"><label>{lt ? "Kopijuoti nepavyko. Pažymėkite ir nukopijuokite rankiniu būdu." : "Copy failed. Select and copy this value manually."}<input readOnly value={copyFailure} onFocus={(event) => event.currentTarget.select()} /></label></div>}
    <div className="table-scroll" role="region" aria-label={lt ? "Galimi phishing kandidatai" : "Potential phishing candidates"} tabIndex={0}>
      <table className="signal-table">
        <colgroup><col className="candidate-column" /><col className="brand-column" /><col className="evidence-column" /><col className="hosting-column" /><col className="timeline-column" /></colgroup>
        <thead><tr><th scope="col">{lt ? "Kandidatas" : "Candidate"}</th><th scope="col">{lt ? "Galimas prekių ženklas" : "Potential brand"}</th><th scope="col">{lt ? "Įrodymai" : "Evidence"}</th><th scope="col">{lt ? "Stebėta priegloba" : "Hosting observed"}</th><th scope="col">{lt ? "Laiko juosta" : "Timeline"}</th></tr></thead>
        <tbody>{pageSignals.map((signal) => {
          const tier = signalEvidenceTier(signal);
          return <tr key={signal.id} id={`signal-${signal.id}`}>
            <td className="indicator-cell" data-label={lt ? "Kandidatas" : "Candidate"}><div><button className="candidate-link" type="button" aria-haspopup="dialog" onClick={(event) => setDetail({ signal, trigger: event.currentTarget })}><code title={signal.url}>{signal.url}</code></button><button type="button" onClick={() => void copy(signal)} aria-label={lt ? `Kopijuoti neutralizuotą URL ${signal.url}` : `Copy defanged URL ${signal.url}`}>{copiedId === signal.id ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}</button><a className="signal-deep-link" href={signalPath(signal, language)} aria-label={lt ? `Atverti nuolatinį ${signal.domain} įrašą` : `Open permanent record for ${signal.domain}`}><Link2 aria-hidden="true" /></a></div><span>{signal.domain}</span></td>
            <td data-label={lt ? "Galimas prekių ženklas" : "Potential brand"}>{signal.brand ? <a className="brand-target" href={brandPath(signal.brand, language)}>{signal.brand}</a> : <span className="unknown">{lt ? "Nepriskirta" : "Unclassified"}</span>}<div className="source-chips">{signal.sources.map((source) => <button type="button" key={source} onClick={() => onFacet("source", source)}>{source}</button>)}</div></td>
            <td data-label={lt ? "Įrodymai" : "Evidence"}><span className={`status-pill ${signal.status}`}><i aria-hidden="true" />{lt ? statusLt[signal.status] : sentenceCase(signal.status)}</span><MatchScore signal={signal} language={language} /><span className={`evidence-tier ${tier}`}>{evidenceTierLabel(tier, language)}</span></td>
            <td data-label={lt ? "Stebėta priegloba" : "Hosting observed"}>{!signal.host && !signal.country ? <span className="hosting-unknown unknown">{lt ? "Priegloba ir šalis nežinomos" : "Hosting and country unknown"}</span> : <><strong className="host-name" title={signal.host ?? undefined}>{signal.host ?? (lt ? "Nežinoma priegloba" : "Unknown host")}</strong>{signal.country ? <button className="facet-button country" type="button" onClick={() => onFacet("country", signal.country!)}>{signal.country}</button> : <span className="country">{lt ? "Šalis nežinoma" : "Unknown country"}</span>}</>}</td>
            <td data-label={lt ? "Laiko juosta" : "Timeline"}><time dateTime={signal.lastSeen} title={lt ? `${dateTime(signal.lastSeen)} Lietuvos laiku` : `${dateTime(signal.lastSeen)} UTC`}>{lt ? `Paskutinį kartą ${relativeTime(signal.lastSeen, now)}` : `Last ${relativeTime(signal.lastSeen, now)}`}</time><span className="first-seen" title={lt ? `${dateTime(signal.firstSeen)} Lietuvos laiku` : `${dateTime(signal.firstSeen)} UTC`}>{lt ? `Pirmą kartą ${relativeTime(signal.firstSeen, now)}` : `First ${relativeTime(signal.firstSeen, now)}`}</span><button className="record-link" type="button" aria-haspopup="dialog" onClick={(event) => setDetail({ signal, trigger: event.currentTarget })}>{lt ? "Peržiūrėti informaciją" : "View details"} <FileSearch aria-hidden="true" /></button></td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <div className="pagination"><p>{lt ? "Rodoma" : "Showing"} <strong>{(page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, signals.length)}</strong> {lt ? "iš" : "of"} {signals.length}</p><div><button type="button" disabled={page === 1} onClick={() => setPage((value) => value - 1)}><ChevronLeft aria-hidden="true" /> {lt ? "Ankstesnis" : "Previous"}</button><span>{lt ? "Puslapis" : "Page"} <strong>{page}</strong> {lt ? "iš" : "of"} {pages}</span><button type="button" disabled={page === pages} onClick={() => setPage((value) => value + 1)}>{lt ? "Kitas" : "Next"} <ChevronRight aria-hidden="true" /></button></div></div>
    {detail ? <ScreenshotModal signal={detail.signal} snapshotGeneratedAt={snapshotGeneratedAt} returnFocus={detail.trigger} onClose={closeDetail} language={language} /> : null}
  </div>;
}
