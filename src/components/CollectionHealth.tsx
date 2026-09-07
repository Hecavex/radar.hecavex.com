import { useEffect, useState } from "react";
import { IndexedCtHealth } from "./IndexedCtHealth.tsx";

import { formatRelativeTime } from "../lib/format.ts";
import { formatRelativeTimeLt } from "../lt/formatLt.ts";
import {
  loadCollectionHealth,
  type CollectionAttempt,
  type CollectionHealth as CollectionHealthArtifact,
  type CollectionOutcome,
} from "../lib/collectionHealth.ts";
import type { SiteLanguage } from "./SiteHeader.tsx";

const outcomeLabels: Record<CollectionOutcome, string> = {
  "healthy-empty": "Healthy empty",
  "healthy-matches": "Healthy with matches",
  "no-input": "No input",
  partial: "Partial",
  failed: "Failed",
};

const outcomeLabelsLt: Record<CollectionOutcome, string> = {
  "healthy-empty": "Sėkmingas, atitikmenų nėra",
  "healthy-matches": "Sėkmingas, rasta atitikmenų",
  "no-input": "Negauta įvesties",
  partial: "Dalinis",
  failed: "Nepavyko",
};

const outcomeSummariesLt: Record<CollectionOutcome, string> = {
  "healthy-empty": "Įvestis sėkmingai apdorota, tačiau nė vienas kandidatas neatitiko publikavimo kriterijų.",
  "healthy-matches": "Įvestis sėkmingai apdorota ir rastas bent vienas kriterijus atitinkantis kandidatas.",
  "no-input": "Ryšys su šaltiniu užmegztas, tačiau negauta sertifikatų DNS vardų.",
  partial: "Rinktuvas apdorojo tik dalį numatyto klausymosi lango.",
  failed: "Rinktuvui nepavyko užmegzti arba užbaigti tinkamo klausymosi lango.",
};

function duration(value: number, language: SiteLanguage): string {
  if (value < 60) {
    const formatted = new Intl.NumberFormat(language === "lt" ? "lt-LT" : "en-GB", {
      minimumFractionDigits: value < 10 ? 1 : 0,
      maximumFractionDigits: value < 10 ? 1 : 0,
    }).format(value);
    return language === "lt" ? `${formatted} sek.` : `${formatted} seconds`;
  }
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  if (language === "lt") return seconds ? `${minutes} min. ${seconds} sek.` : `${minutes} min.`;
  return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function exactNumber(value: number, language: SiteLanguage): string {
  return new Intl.NumberFormat(language === "lt" ? "lt-LT" : "en-GB").format(value);
}

function exactTimestamp(value: string, language: SiteLanguage): string {
  const lt = language === "lt";
  return `${new Intl.DateTimeFormat(lt ? "lt-LT" : "en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: lt ? "Europe/Vilnius" : "UTC",
  }).format(Date.parse(value))} ${lt ? "Lietuvos laiku" : "UTC"}`;
}

function listeningSeconds(value: number, language: SiteLanguage): string {
  const locale = language === "lt" ? "lt-LT" : "en-GB";
  const suffix = language === "lt" ? " sek." : "s";
  return `${new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 3 }).format(value)}${suffix}`;
}

function scheduleLabel(attempt: CollectionAttempt, language: SiteLanguage): string {
  const lt = language === "lt";
  if (attempt.scheduleStatus === "manual") return lt ? "Rankinis paleidimas" : "Manual run";
  if (attempt.scheduleStatus === "relayed") return lt ? "Tvarkaraščio tęsinys" : "Cadence relay";
  if (attempt.scheduleStatus === "unknown") return lt ? "Tvarkaraštis nežinomas" : "Schedule unknown";
  if (attempt.scheduleStatus === "delayed") {
    return lt
      ? `Numanomo paleidimo vėlavimas · ${duration(attempt.delaySeconds ?? 0, language)}`
      : `Inferred slot delay · ${duration(attempt.delaySeconds ?? 0, language)}`;
  }
  return lt
    ? `Suplanuota · ${duration(attempt.delaySeconds ?? 0, language)} po numanomo laiko`
    : `Scheduled · ${duration(attempt.delaySeconds ?? 0, language)} after inferred slot`;
}

export function CollectionHealth({ now = Date.now(), language = "en" }: { now?: number; language?: SiteLanguage }) {
  const lt = language === "lt";
  const [health, setHealth] = useState<CollectionHealthArtifact | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    loadCollectionHealth(controller.signal)
      .then((value) => setHealth(value))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) setUnavailable(true);
      });
    return () => controller.abort();
  }, []);

  if (!health) {
    return (
      <section className="collection-health" aria-labelledby="collection-health-title">
        <div>
          <p className="eyebrow">{lt ? "Rinkimo būsena" : "Collection health"}</p>
          <h3 id="collection-health-title">{lt ? "Naujausias CertStream bandymas" : "Latest CertStream attempt"}</h3>
        </div>
        <p role="status">
          {unavailable
            ? lt
              ? "Vieši rinkimo būsenos metaduomenys laikinai nepasiekiami."
              : "Public collection-health metadata is temporarily unavailable."
            : lt
              ? "Kraunama vieša bandymo telemetrija…"
              : "Loading public attempt telemetry…"}
        </p>
        <noscript>
          <p>
            <a href="/data/collection-health.json">
              {lt ? "Atverti viešą rinkimo būsenos JSON" : "View the public collection-health JSON"}
            </a>.
          </p>
        </noscript>
      </section>
    );
  }

  if (health.latestAttempt === null) {
    return (
      <section className="collection-health" aria-labelledby="collection-health-title">
        <div className="collection-health-heading">
          <div>
            <p className="eyebrow">{lt ? "Rinkimo būsena" : "Collection health"}</p>
            <h3 id="collection-health-title">{lt ? "Naujausias CertStream bandymas" : "Latest CertStream attempt"}</h3>
          </div>
          <span className="health-badge">
            {lt ? "Laukiama pirmojo išmatuoto bandymo" : "Awaiting first measured attempt"}
          </span>
        </div>
        {lt ? (
          <p className="collection-health-summary">
            Rinkimo būsenos matavimas parengtas. Pirmoji užbaigta suplanuota arba rankinė darbo eiga pakeis šį pradinį
            dokumentą faktiniais laikais ir suvestiniais skaičiais.
          </p>
        ) : (
          <p className="collection-health-summary">
            Collection-health instrumentation is ready. The first completed scheduled or manual workflow will replace
            this bootstrap document with actual timing and aggregate counts.
          </p>
        )}
        {lt ? (
          <p className="collection-health-note">
            Ankstesnė klausymosi trukmė nėra numanoma pagal sukonfigūruotą langą. <a href="/data/collection-health.json">
            Atverti viešą JSON</a>.
          </p>
        ) : (
          <p className="collection-health-note">
            No legacy listening duration is inferred from a configured window. <a href="/data/collection-health.json">
            View the public JSON</a>.
          </p>
        )}
      </section>
    );
  }

  const attempt = health.latestAttempt;
  const lastSuccessAge = health.lastSuccessAt === null ? null : Math.max(0, now - Date.parse(health.lastSuccessAt));
  const isFresh = lastSuccessAge !== null && lastSuccessAge <= health.staleAfterSeconds * 1000;
  const freshnessLabel = lastSuccessAge === null
    ? lt ? "Sėkmingo lango neužfiksuota" : "No successful window recorded"
    : isFresh
      ? lt ? "Dabartinis" : "Current"
      : lt ? "Pasenęs" : "Stale";

  return (
    <section className="collection-health" aria-labelledby="collection-health-title">
      <div className="collection-health-heading">
        <div>
          <p className="eyebrow">{lt ? "Rinkimo būsena" : "Collection health"}</p>
          <h3 id="collection-health-title">{lt ? "Naujausias CertStream bandymas" : "Latest CertStream attempt"}</h3>
        </div>
        <div className="collection-health-statuses" aria-label={lt ? "Naujausio rinkimo būsenos" : "Latest collection statuses"}>
          <span className={`health-badge outcome-${attempt.outcome}`}>
            {(lt ? outcomeLabelsLt : outcomeLabels)[attempt.outcome]}
          </span>
          <span className={`health-badge schedule-${attempt.scheduleStatus}`}>{scheduleLabel(attempt, language)}</span>
          <span className={`health-badge freshness-${isFresh ? "current" : "stale"}`}>{freshnessLabel}</span>
        </div>
      </div>
      <p className="collection-health-summary">{lt ? outcomeSummariesLt[attempt.outcome] : attempt.summary}</p>
      <IndexedCtHealth language={language} />
      <dl className="collection-health-grid">
        <div>
          <dt>{lt ? "Faktinis bandymas" : "Actual attempt"}</dt>
          <dd>
            <time dateTime={attempt.startedAt}>{exactTimestamp(attempt.startedAt, language)}</time>
            <span>
              {lt ? "baigtas " : "ended "}
              <time dateTime={attempt.endedAt}>{exactTimestamp(attempt.endedAt, language)}</time>
            </span>
          </dd>
        </div>
        <div>
          <dt>{lt ? "Klausymasis" : "Listening"}</dt>
          <dd>
            {listeningSeconds(attempt.listeningSeconds, language)}
            <span>
              {lt
                ? `iš numatytų ${exactNumber(attempt.expectedListeningSeconds, language)} sek.`
                : `of ${exactNumber(attempt.expectedListeningSeconds, language)}s expected`}
            </span>
          </dd>
        </div>
        <div>
          <dt>{lt ? "Pranešimai" : "Messages"}</dt>
          <dd>{exactNumber(attempt.messages, language)}</dd>
        </div>
        <div>
          <dt>{lt ? "DNS vardai" : "DNS names"}</dt>
          <dd>{exactNumber(attempt.dnsNames, language)}</dd>
        </div>
        <div>
          <dt>{lt ? "Atitikmenys" : "Matches"}</dt>
          <dd>
            {exactNumber(attempt.matches, language)}
            <span>
              {lt
                ? `${exactNumber(attempt.newRecords, language)} naujų archyvo įrašų`
                : `${exactNumber(attempt.newRecords, language)} new archive records`}
            </span>
          </dd>
        </div>
        <div>
          <dt>{lt ? "Paskutinis sėkmingas bandymas" : "Last success"}</dt>
          <dd>
            {health.lastSuccessAt
              ? lt ? formatRelativeTimeLt(health.lastSuccessAt, now) : formatRelativeTime(health.lastSuccessAt, now)
              : lt ? "Neužfiksuota" : "Not recorded"}
            <span>
              {health.lastSuccessAt
                ? exactTimestamp(health.lastSuccessAt, language)
                : lt ? "Laukiama sėkmingo lango" : "Awaiting a healthy window"}
            </span>
          </dd>
        </div>
      </dl>
      {lt ? (
        <p className="collection-health-note">
          Skaičiai apibūdina tik šį ribotą bandymą. Juose nėra sertifikatų vardų ar nepaskelbtų kandidatų. Pavėluota
          pradžia pateikiama atskirai nuo to, ar klausymosi langas apdorojo tinkamą įvestį.
        </p>
      ) : (
        <p className="collection-health-note">
          Counts describe this bounded attempt only. They contain no certificate names or unpublished candidates. A
          delayed start is reported separately from whether the listening window processed usable input.
        </p>
      )}
    </section>
  );
}
