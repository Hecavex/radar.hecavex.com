import { useEffect, useState } from "react";
import { readBoundedJson } from "../lib/boundedJson.ts";
import type { SiteLanguage } from "./SiteHeader.tsx";

type State = {
  outcome: "completed" | "partial" | "failed" | "deferred-backoff";
  lastAttemptAt: string | null;
  lastSuccessAt: string | null;
  nextAttemptAt: string | null;
  consecutiveFailures: number;
};

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const timestamp = (value: unknown): value is string | null => value === null ||
  (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value).toISOString() === value);

export function IndexedCtHealth({ language }: { language: SiteLanguage }) {
  const lt = language === "lt";
  const [state, setState] = useState<State | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/data/pipeline-health.json", {
      signal: controller.signal, credentials: "omit", referrerPolicy: "no-referrer", cache: "no-store",
    }).then(async (response) => {
      if (!response.ok) return;
      const value = await readBoundedJson(response, 256 * 1024);
      if (!record(value) || !record(value.current) || !record(value.current.ctSearch)) return;
      const ct = value.current.ctSearch;
      if (!record(ct.latestRun) || !record(ct.providerHealth)) return;
      const health = ct.providerHealth;
      if (typeof ct.latestRun.outcome !== "string" ||
        !["completed", "partial", "failed", "deferred-backoff"].includes(ct.latestRun.outcome) ||
        !timestamp(health.lastAttemptAt) || !timestamp(health.lastSuccessAt) || !timestamp(health.nextAttemptAt) ||
        !Number.isInteger(health.consecutiveFailures) || (health.consecutiveFailures as number) < 0) return;
      setState({
        outcome: ct.latestRun.outcome as State["outcome"], lastAttemptAt: health.lastAttemptAt,
        lastSuccessAt: health.lastSuccessAt, nextAttemptAt: health.nextAttemptAt,
        consecutiveFailures: health.consecutiveFailures as number,
      });
    }).catch(() => { /* Optional public telemetry never changes candidate judgments. */ });
    return () => controller.abort();
  }, []);
  if (!state) return null;
  const labels = lt
    ? { completed: "Užbaigta", partial: "Dalinė pažanga", failed: "Tiekėjo užklausa nepavyko", "deferred-backoff": "Atidėta iki pakartotinio bandymo" }
    : { completed: "Completed", partial: "Partial progress", failed: "Provider request failed", "deferred-backoff": "Deferred during backoff" };
  const date = (value: string | null) => value
    ? <time dateTime={value}>{value.replace("T", " ").replace(".000Z", " UTC")}</time>
    : lt ? "Neužfiksuota" : "Not recorded";
  return <details className="indexed-ct-health">
    <summary>{lt ? "Indeksuota CT paieška" : "Indexed CT search"}: {labels[state.outcome]}</summary>
    {state.outcome === "deferred-backoff" && <p>{lt
      ? "Šiuo paleidimu tinklo užklausa neatlikta. Ankstesnė tiekėjo klaida nėra naujas nepavykęs bandymas."
      : "No network request was made in this run. The previous provider error is not a new failed attempt."}</p>}
    <dl className="collection-health-grid">
      <div><dt>{lt ? "Paskutinė faktinė užklausa" : "Last actual request"}</dt><dd>{date(state.lastAttemptAt)}</dd></div>
      <div><dt>{lt ? "Paskutinė sėkmė" : "Last success"}</dt><dd>{date(state.lastSuccessAt)}</dd></div>
      <div><dt>{lt ? "Kitas bandymas leidžiamas nuo" : "Next attempt allowed from"}</dt><dd>{date(state.nextAttemptAt)}</dd></div>
      <div><dt>{lt ? "Iš eilės nepavykusių faktinių užklausų" : "Consecutive actual failures"}</dt><dd>{state.consecutiveFailures}</dd></div>
    </dl>
    <p>{lt ? "Laukimo pabaiga negarantuoja tikslaus paleidimo laiko." : "Cooldown expiry is not a promised execution time."} <a href="/data/pipeline-health.json">JSON</a></p>
  </details>;
}
