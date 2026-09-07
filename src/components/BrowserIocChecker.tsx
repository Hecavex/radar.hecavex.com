import {
  CheckCircle2,
  FileLock2,
  SearchCheck,
  ShieldQuestion,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";
import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  MAXIMUM_IOC_FILE_BYTES,
  MAXIMUM_IOC_LINES,
  checkIocs,
  parseIocInput,
  type IocCheckResult,
} from "../lib/iocCheck.ts";
import { formatDateTime } from "../lib/format.ts";
import { loadHistory } from "../lib/historyData.ts";
import { formatDateTimeLt } from "../lt/formatLt.ts";
import type { RadarHistory, RadarSignal } from "../types.ts";

type ResultFilter = "all" | "matched" | "unknown" | "invalid";

const PAGE_SIZE = 50;

const kindLabels: Record<"en" | "lt", Record<NonNullable<IocCheckResult["kind"]>, string>> = {
  en: { domain: "Domain", url: "URL", md5: "MD5", sha1: "SHA-1", sha256: "SHA-256" },
  lt: { domain: "Domenas", url: "URL", md5: "MD5", sha1: "SHA-1", sha256: "SHA-256" },
};

function resultState(result: IocCheckResult): Exclude<ResultFilter, "all"> {
  if (result.error) return "invalid";
  return result.matches.length > 0 ? "matched" : "unknown";
}

function localizeError(error: string, language: "en" | "lt"): string {
  if (language === "en") return error;
  const messages: Record<string, string> = {
    "Empty line": "Tuščia eilutė",
    "Indicator exceeds 2,048 characters": "Indikatorius viršija 2 048 simbolius",
    "Unsupported or malformed HTTP(S) URL": "Nepalaikomas arba netaisyklingas HTTP(S) URL",
    "Not a supported domain, HTTP(S) URL, MD5, SHA-1, or SHA-256 value": "Tai nėra palaikomas domenas, HTTP(S) URL, MD5, SHA-1 ar SHA-256 reikšmė",
  };
  return messages[error] ?? error;
}

export type BrowserIocCheckerProps = {
  signals: readonly RadarSignal[];
  history: RadarHistory | null;
  historyTotal?: number;
  signalHref?: (signalId: string) => string;
  language?: "en" | "lt";
};

export function BrowserIocChecker({
  signals,
  history: initialHistory,
  historyTotal = initialHistory?.signals.length ?? 0,
  signalHref = (signalId) => `/signals/${signalId}/`,
  language = "en",
}: BrowserIocCheckerProps) {
  const lt = language === "lt";
  const incomplete = historyTotal > (initialHistory?.signals.length ?? 0);
  const [history, setHistory] = useState(incomplete ? null : initialHistory);
  const [historyError, setHistoryError] = useState(false);
  useEffect(() => {
    if (!incomplete) return;
    const controller = new AbortController();
    void loadHistory(controller.signal).then(setHistory).catch(() => {
      if (!controller.signal.aborted) setHistoryError(true);
    });
    return () => controller.abort();
  }, [incomplete]);
  const historyReady = !incomplete || history !== null;
  const [input, setInput] = useState("");
  const [submitted, setSubmitted] = useState<ReturnType<typeof parseIocInput> | null>(null);
  const [fileMessage, setFileMessage] = useState<string | null>(null);
  const [filter, setFilter] = useState<ResultFilter>("all");
  const [page, setPage] = useState(1);
  const fileInput = useRef<HTMLInputElement>(null);

  const results = useMemo(
    () => submitted ? checkIocs(submitted.indicators, signals, history) : [],
    [history, signals, submitted],
  );
  const counts = useMemo(() => ({
    matched: results.filter((result) => resultState(result) === "matched").length,
    unknown: results.filter((result) => resultState(result) === "unknown").length,
    invalid: results.filter((result) => resultState(result) === "invalid").length,
  }), [results]);
  const filteredResults = useMemo(
    () => filter === "all" ? results : results.filter((result) => resultState(result) === filter),
    [filter, results],
  );
  const pageCount = Math.max(1, Math.ceil(filteredResults.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const visibleResults = filteredResults.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const runCheck = () => {
    if (!historyReady) return;
    const bytes = new TextEncoder().encode(input).byteLength;
    if (bytes > MAXIMUM_IOC_FILE_BYTES) {
      setFileMessage(lt ? `Įvestis viršija ${MAXIMUM_IOC_FILE_BYTES / 1024} KiB.` : `Input is larger than ${MAXIMUM_IOC_FILE_BYTES / 1024} KiB.`);
      setSubmitted(null);
      return;
    }
    setSubmitted(parseIocInput(input));
    setFileMessage(null);
    setFilter("all");
    setPage(1);
  };

  const clear = () => {
    setInput("");
    setSubmitted(null);
    setFileMessage(null);
    setFilter("all");
    setPage(1);
    if (fileInput.current) fileInput.current.value = "";
  };

  const readFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > MAXIMUM_IOC_FILE_BYTES) {
      setFileMessage(lt ? `${file.name} viršija ${MAXIMUM_IOC_FILE_BYTES / 1024} KiB vietinio failo ribą.` : `${file.name} exceeds the ${MAXIMUM_IOC_FILE_BYTES / 1024} KiB local file limit.`);
      return;
    }
    try {
      const contents = await file.text();
      setInput(contents);
      setSubmitted(null);
      setFileMessage(lt ? `${file.name} perskaitytas vietoje. Failas nebuvo įkeltas.` : `${file.name} was read locally. It has not been uploaded.`);
    } catch {
      setFileMessage(lt ? `Naršyklei nepavyko perskaityti ${file.name}.` : `The browser could not read ${file.name}.`);
    }
  };

  return (
    <section className="radar-tool radar-ioc-checker" aria-labelledby="ioc-checker-title">
      <header className="radar-tool-heading">
        <div>
          <p className="eyebrow"><SearchCheck aria-hidden="true" /> {lt ? "Vietinė IOC paieška" : "Local IOC lookup"}</p>
          <h2 id="ioc-checker-title">{lt ? "Patikrinkite indikatorius Radaro duomenyse" : "Check indicators against Radar"}</h2>
        </div>
        <p>
          {lt
            ? "Tiksliai palyginkite domenus, URL ir maišos reikšmes su dabartine suvestine ir išsaugota vieša istorija. Normalizavimas ir palyginimas vyksta tik šioje naršyklėje."
            : "Exact-match domains, URLs, and hashes against the current snapshot and retained public history. Normalisation and matching happen only in this browser."}
        </p>
      </header>

      <div className="radar-tool-notice radar-tool-notice--privacy">
        <FileLock2 aria-hidden="true" />
        <div>
          <strong>{lt ? "Jūsų indikatoriai neperduodami" : "Your indicators are not transmitted"}</strong>
          <p>
            {lt
              ? "Šis įrankis nesiunčia paieškos užklausų ir nesaugo pateiktų reikšmių. Įklijuotas tekstas ir pasirinkti failai lieka puslapio atmintyje, kol juos išvalote, atnaujinate puslapį arba užveriate kortelę."
              : "This tool makes no lookup request and stores no submitted value. Pasted text and selected files remain in page memory until you clear them, refresh, or close the tab."}
          </p>
        </div>
      </div>

      <div className="radar-ioc-input">
        {!historyReady && <p role="status">{historyError
          ? (lt ? "Visa istorija nepasiekiama. Paieška išjungta, kad nepilni duomenys nebūtų palaikyti sutapimų nebuvimu." : "Complete history is unavailable. Lookup is disabled so incomplete data cannot be mistaken for no match.")
          : (lt ? "Įkeliama ir tikrinama visa vieša istorija prieš paiešką." : "Loading and verifying complete public history before lookup.")}</p>}
        <label htmlFor="radar-ioc-values">{lt ? "Vienas indikatorius eilutėje" : "One indicator per line"}</label>
        <textarea
          id="radar-ioc-values"
          value={input}
          onChange={(event) => {
            setInput(event.target.value);
            setSubmitted(null);
            setFileMessage(null);
          }}
          rows={10}
          spellCheck="false"
          autoCapitalize="none"
          autoComplete="off"
          aria-describedby="radar-ioc-help"
          placeholder={'example[.]lt\nhxxps://example[.]lt/login\n0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'}
        />
        <p id="radar-ioc-help">
          {lt ? "Iki" : "Up to"} {MAXIMUM_IOC_LINES.toLocaleString(lt ? "lt-LT" : "en-GB")} {lt ? "eilučių arba" : "lines or"} {MAXIMUM_IOC_FILE_BYTES / 1024} KiB.
          {" "}{lt ? "Priimami HTTP(S), hxxp(s), įprasti neutralizuoti taškai, MD5, SHA-1 ir SHA-256. Tuščios eilutės ir komentarai, prasidedantys #, nepaisomi." : "HTTP(S), hxxp(s), common dot defangs, MD5, SHA-1 and SHA-256 are accepted. Blank and # comment lines are ignored."}
        </p>
        <div className="radar-ioc-actions">
          <button type="button" className="radar-tool-button radar-tool-button--primary" onClick={runCheck} disabled={!input.trim() || !historyReady}>
            <SearchCheck aria-hidden="true" /> {lt ? "Tikrinti vietoje" : "Check locally"}
          </button>
          <label className="radar-tool-button radar-tool-file-button">
            <Upload aria-hidden="true" /> {lt ? "Skaityti tekstinį failą" : "Read text file"}
            <input ref={fileInput} type="file" accept=".txt,text/plain" onChange={(event) => void readFile(event)} />
          </label>
          <button type="button" className="radar-tool-button" onClick={clear} disabled={!input && !submitted && !fileMessage}>
            <Trash2 aria-hidden="true" /> {lt ? "Išvalyti iš atminties" : "Clear from memory"}
          </button>
        </div>
        {fileMessage ? <p className="radar-tool-message" role="status">{fileMessage}</p> : null}
      </div>

      {submitted ? (
        <div className="radar-ioc-results">
          <p className="sr-only" role="status">
            {lt ? "Patikrinta" : "Checked"} {results.length} {lt ? "unikalių indikatorių" : "unique indicators"}: {counts.matched} {lt ? "tikslūs atitikmenys" : "exact matches"}, {counts.unknown} {lt ? "nežinomi" : "unknown"}, {counts.invalid} {lt ? "nepalaikomi" : "unsupported"}.
          </p>
          <div className="radar-tool-notice radar-tool-notice--warning">
            <ShieldQuestion aria-hidden="true" />
            <div>
              <strong>{lt ? "Atitikmens nebuvimas reiškia nežinomybę, o ne saugumą" : "No match means unknown, not safe"}</strong>
              <p>
                {lt
                  ? "Radaras yra ribotas stebėjimų duomenų rinkinys, o ne leidžiamų objektų sąrašas. Įrašo nebuvimas nepatvirtina reputacijos, ketinimų ar saugumo, o tikslus atitikmuo savaime neįrodo kenkėjiškumo."
                  : "Radar is a bounded observation dataset, not an allow-list. Absence does not establish reputation, intent, or safety, and an exact match is not by itself proof of maliciousness."}
              </p>
            </div>
          </div>

          <div className="radar-tool-summary" aria-label={lt ? "IOC patikros suvestinė" : "IOC check summary"}>
            <button type="button" className={filter === "all" ? "active" : ""} onClick={() => { setFilter("all"); setPage(1); }}>
              <span>{lt ? "Patikrinta" : "Checked"}</span><strong>{results.length}</strong>
            </button>
            <button type="button" className={filter === "matched" ? "active" : ""} onClick={() => { setFilter("matched"); setPage(1); }}>
              <span>{lt ? "Tikslūs atitikmenys" : "Exact matches"}</span><strong>{counts.matched}</strong>
            </button>
            <button type="button" className={filter === "unknown" ? "active" : ""} onClick={() => { setFilter("unknown"); setPage(1); }}>
              <span>{lt ? "Nežinoma" : "Unknown"}</span><strong>{counts.unknown}</strong>
            </button>
            <button type="button" className={filter === "invalid" ? "active" : ""} onClick={() => { setFilter("invalid"); setPage(1); }}>
              <span>{lt ? "Nepalaikoma" : "Unsupported"}</span><strong>{counts.invalid}</strong>
            </button>
          </div>

          {submitted.truncated || submitted.duplicateCount > 0 || submitted.ignoredCount > 0 ? (
            <p className="radar-tool-message" role="status">
              {submitted.truncated ? (lt ? `Patikrintos tik pirmos ${MAXIMUM_IOC_LINES.toLocaleString("lt-LT")} eilutės. ` : `Only the first ${MAXIMUM_IOC_LINES.toLocaleString("en-GB")} lines were checked. `) : ""}
              {submitted.duplicateCount > 0 ? (lt ? `${submitted.duplicateCount} pasikartojančios eilutės sujungtos. ` : `${submitted.duplicateCount} duplicate line(s) were collapsed. `) : ""}
              {submitted.ignoredCount > 0 ? (lt ? `${submitted.ignoredCount} tuščių arba komentaro eilučių nepaisyta.` : `${submitted.ignoredCount} blank or comment line(s) were ignored.`) : ""}
            </p>
          ) : null}

          {visibleResults.length === 0 ? (
            <div className="radar-tool-empty">{lt ? "Šiame vaizde rezultatų nėra." : "No results are present in this view."}</div>
          ) : (
            <div className="radar-tool-table-scroll">
              <table className="radar-tool-table">
                <thead>
                  <tr>
                    <th>{lt ? "Pateiktas indikatorius" : "Submitted indicator"}</th>
                    <th>{lt ? "Vietinis rezultatas" : "Local result"}</th>
                    <th>{lt ? "Tikslus Radaro įrašas" : "Exact Radar record"}</th>
                    <th>{lt ? "Stebėjimo laikas" : "Observed timeline"}</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleResults.map((result) => {
                    const state = resultState(result);
                    return (
                      <tr key={`${result.kind ?? "invalid"}:${result.normalized ?? result.raw}`}>
                        <td>
                          <span className="radar-tool-kicker">{result.kind ? kindLabels[language][result.kind] : (lt ? "Nepalaikoma" : "Unsupported")}</span>
                          <code>{result.normalized ?? result.raw}</code>
                        </td>
                        <td>
                          <span className={`radar-ioc-state radar-ioc-state--${state}`}>
                            {state === "matched" ? <CheckCircle2 aria-hidden="true" /> : state === "unknown" ? <ShieldQuestion aria-hidden="true" /> : <XCircle aria-hidden="true" />}
                            {state === "matched" ? (lt ? "Tikslus atitikmuo" : "Exact match") : state === "unknown" ? (lt ? "Nepastebėta" : "Not observed") : (lt ? "Nepatikrinta" : "Not checked")}
                          </span>
                          {result.error ? <small>{localizeError(result.error, language)}</small> : null}
                        </td>
                        <td>
                          {result.matches.length === 0 ? <span className="radar-tool-muted">{lt ? "Įrašo nėra" : "No record"}</span> : (
                            <ul className="radar-ioc-matches">
                              {result.matches.map((match) => (
                                <li key={`${match.signalId}:${match.matchedField}`}>
                                  <a href={signalHref(match.signalId)}>{match.domain}</a>
                                  <span>{match.brand ?? (lt ? "Prekių ženklas nepriskirtas" : "Unassigned brand")} · {match.datasets.join(" + ")}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </td>
                        <td>
                          {result.matches.length === 0 ? <span className="radar-tool-muted">{lt ? "Nežinoma" : "Unknown"}</span> : (
                            <span className="radar-ioc-timeline">
                              {lt ? "Pirmą kartą" : "First"} {lt ? `${formatDateTimeLt(result.matches[0].firstSeen)} Lietuvos laiku` : `${formatDateTime(result.matches[0].firstSeen)} UTC`}<br />
                              {lt ? "Paskutinį kartą" : "Last"} {lt ? `${formatDateTimeLt(result.matches[0].lastSeen)} Lietuvos laiku` : `${formatDateTime(result.matches[0].lastSeen)} UTC`}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {pageCount > 1 ? (
            <nav className="radar-tool-pagination" aria-label={lt ? "IOC rezultatų puslapiai" : "IOC result pages"}>
              <button type="button" onClick={() => setPage(Math.max(1, safePage - 1))} disabled={safePage === 1}>{lt ? "Ankstesnis" : "Previous"}</button>
              <span>{lt ? "Puslapis" : "Page"} {safePage} {lt ? "iš" : "of"} {pageCount}</span>
              <button type="button" onClick={() => setPage(Math.min(pageCount, safePage + 1))} disabled={safePage === pageCount}>{lt ? "Kitas" : "Next"}</button>
            </nav>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
