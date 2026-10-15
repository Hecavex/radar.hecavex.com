import { useEffect, useMemo, useState } from "react";
import { downloadText } from "../lib/export.ts";
import { foldSearchText } from "../lib/searchText.ts";
import { domainToUnicode } from "../lib/signalComparison.ts";
import { signalPath } from "../lib/signalRoutes.ts";
import { loadPeriodOverview, observedHostnamesAsCsv, observedHostnamesAsJson, periodTotals, selectPeriodRecords, type ObservedHostnameRecord, type PeriodOverviewData, type PeriodWindow } from "../lib/periodMetrics.ts";
import type { SiteLanguage } from "./SiteHeader.tsx";

const PAGE_SIZE = 25;
const PRESETS = ["30d", "90d", "365d", "all"];

function HostnameEvidence({ row, language }: { row: ObservedHostnameRecord; language: SiteLanguage }) {
  const lt = language === "lt";
  const t = (en: string, translated: string) => lt ? translated : en;
  const unavailable = t("Unavailable", "Nepasiekiama");
  const unicode = domainToUnicode(row.domain).replaceAll(".", "[.]");
  const assessment = row.assessment;
  const verdicts = { malicious: "kenkėjiškas", suspicious: "įtartinas", benign: "nekenksmingas", inconclusive: "nepakanka duomenų" };
  return <details className="history-provenance">
    <summary>{t("Observation details", "Stebėjimo duomenys")}</summary>
    {unicode !== row.domain && <p>{t("Decoded Unicode hostname", "Iškoduotas Unicode domeno vardas")}: <bdi dir="ltr"><code>{unicode}</code></bdi></p>}
    <p>{t("Domain group", "Domenų grupė")}: <code>{row.domainGroup}</code></p>
    <p>{t("Observed UTC days", "Stebėtos UTC dienos")}: {row.observedDays.join(", ")}</p>
    <p>{t("Recorded name-match score", "Išsaugotas vardo atitikties balas")}: {row.match.score === null ? unavailable : `${row.match.score}/100`}; {row.match.reasonCodes.join(", ") || t("no recorded reasons", "priežastys neišsaugotos")}</p>
    <p>{t("Recorded matching policy", "Išsaugota atitikties politika")}: <code>{row.match.policyVersion}</code></p>
    <p>{t("Explicit assessment", "Aiškus vertinimas")}: {assessment ? (lt ? verdicts[assessment.verdict] : assessment.verdict) : t("No published assessment", "Viešo vertinimo nėra")}{assessment && <> · <time dateTime={assessment.assessedAt}>{assessment.assessedAt}</time></>}</p>
    {assessment && <>
      <p>{t("Analyst confidence in this assessment", "Analitiko pasitikėjimas šiuo vertinimu")}: {assessment.analystConfidence === null ? unavailable : `${assessment.analystConfidence}/100`}</p>
      <p>{t("Decision", "Sprendimas")}: <code>{assessment.decisionId}</code></p>
      <p>{t("Recorded evidence references", "Išsaugotos įrodymų nuorodos")}: {assessment.evidenceReferences.map((reference, index) => <span key={reference}>{index > 0 && "; "}<code>{reference}</code></span>)}</p>
    </>}
    <p>{t("Radar first recorded", "Pirmas įrašas Radare")}: {row.firstRecordedAt ?? unavailable}<br />{t("First verified publication receipt", "Pirmas patikrinto paskelbimo įrašas")}: {row.firstPublishedAt ?? unavailable}</p>
    {!row.recordAvailable && <p>{t("A separate detail page is unavailable for this retained hostname.", "Atskiras šio išsaugoto domeno vardo duomenų puslapis nepasiekiamas.")}</p>}
  </details>;
}

export function PeriodOverview({ initialData, language = "en" }: { initialData?: PeriodOverviewData; language?: SiteLanguage }) {
  const lt = language === "lt";
  const t = (en: string, translation: string) => lt ? translation : en;
  const number = (value: number) => value.toLocaleString(lt ? "lt-LT" : "en-GB");
  const [data, setData] = useState(initialData);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState("30d");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [fromDate, setFromDate] = useState("");
  const [throughDate, setThroughDate] = useState("");
  const [custom, setCustom] = useState<PeriodWindow | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    void loadPeriodOverview({ signal: controller.signal }).then(setData).catch(() => {
      if (!controller.signal.aborted) setError(true);
    });
    return () => controller.abort();
  }, [retry]);

  const window = useMemo(() => {
    if (selected === "custom" && custom && data?.complete) {
      const totals = periodTotals(data.records, custom);
      const clocks = (key: "firstRecordedAt" | "firstPublishedAt", complete: boolean, activation: string | null) => complete || (activation !== null && custom.startInclusive! >= activation)
        ? data.records.filter((row) => row[key] !== null && row[key]! >= custom.startInclusive! && row[key]! < custom.endExclusive).length : null;
      return { ...custom, ...totals,
        firstRecordedHostnames: clocks("firstRecordedAt", data.metrics.coverage.historicalRecordingTimesComplete, data.metrics.coverage.recordedFrom),
        firstPublishedHostnames: clocks("firstPublishedAt", data.metrics.coverage.historicalPublicationTimesComplete, data.metrics.coverage.publicationRecordedFrom) };
    }
    return data?.metrics.windows.find((entry) => entry.key === selected) ?? data?.metrics.windows.find((entry) => entry.key === "30d");
  }, [custom, data, selected]);
  const periodRows = useMemo(() => !data || !window || (!data.complete && window.key !== "30d") ? [] : selectPeriodRecords(data.records, window), [data, window]);
  const filtered = useMemo(() => {
    const needle = foldSearchText(query.trim().replaceAll("[.]", "."));
    return periodRows.filter((row) => !needle || foldSearchText(`${row.domain.replaceAll("[.]", ".")} ${domainToUnicode(row.domain)} ${row.domainGroup.replaceAll("[.]", ".")} ${row.brand} ${row.sources.join(" ")}`).includes(needle));
  }, [periodRows, query]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice((Math.min(page, pages) - 1) * PAGE_SIZE, Math.min(page, pages) * PAGE_SIZE);
  useEffect(() => setPage(1), [selected, query, data]);
  useEffect(() => {
    if (data && selected !== "custom" && !data.metrics.windows.some((entry) => entry.key === selected)) setSelected("30d");
  }, [data, selected]);

  const periodLabel = (key: string) => key === "all" ? t("All recorded", "Visa išsaugota istorija") : key === "custom" ? t("Selected UTC dates", "Pasirinktos UTC datos") : key.startsWith("month:") ? key.slice(6) : key.startsWith("year:") ? key.slice(5) : t(`${key.slice(0, -1)} days`, `${key.slice(0, -1)} dienų`);
  const unavailable = t("Unavailable", "Nepasiekiama");
  const exportRows = (kind: "json" | "csv") => {
    if (!data?.complete || !window) return;
    const contents = kind === "json" ? observedHostnamesAsJson(filtered, data, window) : observedHostnamesAsCsv(filtered, data, window);
    downloadText(`hecavex-observed-hostnames-${data.metrics.asOf.slice(0, 10)}.${kind}`, contents, kind === "json" ? "application/json;charset=utf-8" : "text/csv;charset=utf-8");
  };
  const applyCustom = () => {
    if (!data?.complete || !/^\d{4}-\d{2}-\d{2}$/.test(fromDate) || !/^\d{4}-\d{2}-\d{2}$/.test(throughDate) || fromDate > throughDate) return;
    const start = `${fromDate}T00:00:00.000Z`;
    const end = new Date(`${throughDate}T00:00:00.000Z`);
    if (!Number.isFinite(end.getTime()) || !Number.isFinite(Date.parse(start))) return;
    end.setUTCDate(end.getUTCDate() + 1);
    setCustom({ key: "custom", startInclusive: start, endExclusive: end.toISOString(), uniqueHostnames: 0, domainGroups: 0, candidateDays: 0, firstRecordedHostnames: null, firstPublishedHostnames: null, exactWithinRecordedData: true, completeCollection: false });
    setSelected("custom");
  };

  return <section className="period-overview" id="observed-hostnames" aria-labelledby="observed-hostnames-title">
    <div className="period-heading">
      <div><p className="eyebrow">{t("Recorded observations", "Išsaugoti stebėjimai")}</p><h2 id="observed-hostnames-title">{t("Unique hostnames observed", "Stebėti unikalūs domenų vardai")}</h2><p>{t("Each canonical hostname counts once in the selected period. Subdomains count separately.", "Kiekvienas kanoninis domeno vardas pasirinktu laikotarpiu skaičiuojamas vieną kartą. Subdomenai skaičiuojami atskirai.")}</p></div>
      <div className="period-primary" aria-live="polite"><strong data-period-count={window?.uniqueHostnames ?? "unknown"}>{window ? number(window.uniqueHostnames) : "—"}</strong><span>{periodLabel(window?.key ?? selected)}</span></div>
    </div>
    <div className="period-controls" role="group" aria-label={t("Observation period", "Stebėjimo laikotarpis")}>
      {PRESETS.map((key) => <button type="button" key={key} aria-pressed={selected === key} disabled={!data} onClick={() => setSelected(key)}>{periodLabel(key)}</button>)}
      <label>{t("Calendar month (UTC)", "Kalendorinis mėnuo (UTC)")}<select value={selected.startsWith("month:") ? selected : ""} disabled={!data} onChange={(event) => { if (event.target.value) setSelected(event.target.value); }}><option value="">{t("Choose a month", "Pasirinkti mėnesį")}</option>{data?.metrics.windows.filter((entry) => entry.key.startsWith("month:")).map((entry) => <option key={entry.key} value={entry.key}>{periodLabel(entry.key)}</option>)}</select></label>
    </div>
    {!data && <noscript><p>{t("Recorded observation counts are unavailable in this build. No zero count is assumed.", "Šiame leidime išsaugotų stebėjimų skaičiai nepasiekiami. Tai nelaikoma nuliniu rezultatu.")}</p></noscript>}
    {!data ? <p role="status">{error ? t("Recorded observation counts are unavailable. No zero count is assumed.", "Išsaugotų stebėjimų skaičiai nepasiekiami. Tai nelaikoma nuliniu rezultatu.") : t("Loading recorded observation counts…", "Kraunami išsaugotų stebėjimų skaičiai…")}</p> : <>
      <p className="period-cutoff">{t("Source observation window", "Šaltinio stebėjimo intervalas")}: <code>{window?.startInclusive ?? t("all recorded history", "visa išsaugota istorija")}</code> ≤ {t("time", "laikas")} &lt; <code>{window?.endExclusive}</code>.<br />{t("Data cutoff", "Duomenų riba")}: <time dateTime={data.metrics.asOf}>{data.metrics.asOf}</time>. {t(data.metrics.coverage.collectionComplete ? "Exact within recorded public-eligible observations; declared collection coverage is complete." : "Exact within recorded public-eligible observations; collection is incomplete.", data.metrics.coverage.collectionComplete ? "Tikslu tarp išsaugotų viešai tinkamų stebėjimų; deklaruota rinkimo aprėptis pilna." : "Tikslu tarp išsaugotų viešai tinkamų stebėjimų; rinkimo aprėptis nepilna.")}</p>
      <dl className="period-secondary">
        <div><dt>{t("Private PSL domain groups", "Domenų grupės pagal privatų PSL")}</dt><dd>{number(window?.domainGroups ?? 0)}</dd></div>
        <div><dt>{t("Hostname-days observed", "Stebėto domeno vardo dienos")}</dt><dd>{number(window?.candidateDays ?? 0)}</dd></div>
        <div><dt>{t("First recorded by Radar", "Pirmą kartą įrašyta Radare")}</dt><dd>{window?.firstRecordedHostnames == null ? unavailable : number(window.firstRecordedHostnames)}</dd></div>
        <div><dt>{t("First verified publication receipts", "Pirmi patikrinto paskelbimo įrašai")}</dt><dd>{window?.firstPublishedHostnames == null ? unavailable : number(window.firstPublishedHostnames)}</dd></div>
      </dl>
      <details className="period-coverage"><summary>{t("Coverage and count definitions", "Aprėptis ir skaičių reikšmės")}</summary>
        <p>{t("Available source history begins", "Turima šaltinių istorija prasideda")}: <code>{data.metrics.coverage.availableFrom ?? unavailable}</code>. {t("All recorded is a retained inventory under the current public eligibility policy, not a complete lifetime census.", "Visa išsaugota istorija yra įrašų rinkinys pagal dabartinę viešinimo politiką, o ne pilna visų laikų apskaita.")}</p>
        <p>{t("Recovered days", "Atkurtos dienos")}: {number(data.metrics.coverage.recoveredDays.length)}; {t("declared missing days", "deklaruotos trūkstamos dienos")}: {number(data.metrics.coverage.missingDays.length)}. {t("Historical coverage", "Istorinė aprėptis")}: {data.metrics.coverage.historyComplete ? t("complete within declared archive", "pilna deklaruotame archyve") : t("partial", "dalinė")}. {data.metrics.coverage.partialCurrentDay ? t("The current UTC day is partial.", "Dabartinė UTC diena yra dalinė.") : null}</p>
        <p>{t("First/last seen are upstream source observation times. Radar recording and captured verified publication receipts are separate clocks; unavailable historical clocks remain unknown. Receipt counts cover newly tracked hostnames with known recording times only. Legacy hostnames with unknown recording time keep a null publication clock. Receipt time means the first successfully captured verified receipt since activation, not the earliest-ever public date. Clock metrics count first-clock events independently of source-observation membership.", "Pirmas ir paskutinis stebėjimas yra šaltinio stebėjimo laikas. Įrašymas Radare ir užfiksuoti patikrinto paskelbimo įrašai yra atskiri laikai; nežinomi istoriniai laikai lieka nežinomi. Paskelbimo įrašų skaičiai apima tik naujai sekamus domenų vardus, kurių įrašymo laikas žinomas. Ankstesnių domenų vardų, kurių įrašymo laikas nežinomas, paskelbimo laikas lieka null. Paskelbimo laikas reiškia pirmą sėkmingai užfiksuotą patikrintą įrašą nuo apskaitos pradžios, o ne pačią ankstyviausią viešą datą. Šių laikų rodikliai skaičiuoja pirmuosius įvykius nepriklausomai nuo šaltinio stebėjimų laikotarpio.")}</p>
        <p>{t("Grouping", "Grupavimas")}: {data.metrics.grouping.version}, {t("private suffixes included", "įtrauktos privačios priesagos")}; PSL SHA-256 <code>{data.metrics.grouping.pslSha256}</code>. {t("Matching policy", "Atitikties politika")}: <code>{data.metrics.policyVersions.matching}</code>.</p>
        {data.metrics.coverage.missingDays.length > 0 && <p>{t("Missing UTC days", "Trūkstamos UTC dienos")}: {data.metrics.coverage.missingDays.join(", ")}</p>}
      </details>
      <noscript><p>{t("JavaScript is required for complete local filtering and exports. The following counts are authoritative for the declared cutoff; the table is a bounded 30-day preview.", "Visiems vietiniams filtrams ir eksportui reikia JavaScript. Toliau pateikti skaičiai yra tikslūs deklaruotos duomenų ribos atžvilgiu; lentelė yra ribota 30 dienų peržiūra.")}</p><dl>{PRESETS.map((key) => <div key={key}><dt>{periodLabel(key)}</dt><dd>{number(data.metrics.windows.find((entry) => entry.key === key)!.uniqueHostnames)}</dd></div>)}</dl></noscript>
    </>}
    {error && <p className="period-load-notice" role="status">{t("Complete inventory could not be verified. Embedded counts and the 30-day preview remain available; complete filters and exports are disabled.", "Nepavyko patikrinti viso rinkinio. Įterpti skaičiai ir 30 dienų peržiūra lieka pasiekiami; visi filtrai ir eksportas išjungti.")} <button type="button" onClick={() => setRetry((value) => value + 1)}>{t("Retry", "Bandyti dar kartą")}</button></p>}
    <div className="period-list-heading"><h3>{t("Hostnames in this period", "Domenų vardai šiuo laikotarpiu")}</h3><div className="export-actions" aria-label={t("Export matching recorded hostnames", "Eksportuoti atitinkančius išsaugotus domenų vardus")}><button type="button" disabled={!data?.complete} onClick={() => exportRows("json")}>JSON</button><button type="button" disabled={!data?.complete} onClick={() => exportRows("csv")}>CSV</button></div></div>
    <div className="filter-shell"><label className="period-search">{t("Search locally", "Ieškoti vietoje")}<input type="search" value={query} disabled={!data?.complete} onChange={(event) => setQuery(event.target.value)} placeholder={t("Hostname, Unicode label, brand or source", "Domeno vardas, Unicode žyma, prekės ženklas ar šaltinis")} /></label><details className="period-custom"><summary>{t("Custom UTC dates", "Pasirinktos UTC datos")}</summary><label>{t("From (inclusive)", "Nuo (imtinai)")}<input type="date" value={fromDate} disabled={!data?.complete} max={data?.metrics.asOf.slice(0, 10)} onChange={(event) => setFromDate(event.target.value)} /></label><label>{t("Through (inclusive)", "Iki (imtinai)")}<input type="date" value={throughDate} disabled={!data?.complete} max={data?.metrics.asOf.slice(0, 10)} onChange={(event) => setThroughDate(event.target.value)} /></label><button type="button" disabled={!data?.complete || !fromDate || !throughDate || fromDate > throughDate || throughDate > data.metrics.asOf.slice(0, 10)} onClick={applyCustom}>{t("Apply dates", "Taikyti datas")}</button></details></div>
    <p className="period-list-status" role="status">
      {data?.complete ? <>{number(filtered.length)} {t("matching of", "atitinka iš")} {number(window?.uniqueHostnames ?? 0)} {t("unique hostnames in the period. Search and exports use this same matching set; your query stays in this browser.", "unikalių domenų vardų laikotarpiu. Paieška ir eksportas naudoja tą patį atitinkantį rinkinį; užklausa lieka šioje naršyklėje.")}</>
        : !window || window.key === "30d" ? <>{t("Bounded 30-day preview", "Ribota 30 dienų peržiūra")}: {number(periodRows.length)} {t("loaded rows. This preview is not the period total. Complete local filtering and exports await full verification.", "įkeltų eilučių. Ši peržiūra nėra viso laikotarpio skaičius. Visi vietiniai filtrai ir eksportas įjungiami patikrinus visą rinkinį.")}</>
          : t("Only a bounded 30-day preview is embedded. The complete list for this period awaits verification; filters and exports remain disabled.", "Įterpta tik ribota 30 dienų peržiūra. Šio laikotarpio visas sąrašas laukia patikrinimo; filtrai ir eksportas lieka išjungti.")}
    </p>
    {visible.length > 0 ? <div className="table-panel"><div className="table-scroll" role="region" aria-label={t("Recorded hostname observations", "Išsaugoti domenų vardų stebėjimai")} tabIndex={0}><table className="period-table"><thead><tr><th scope="col">{t("Defanged hostname", "Neutralizuotas domeno vardas")}</th><th scope="col">{t("Potential brand", "Galimas prekės ženklas")}</th><th scope="col">{t("Sources", "Šaltiniai")}</th><th scope="col">{t("Source first / last (all recorded, UTC)", "Šaltinio pirmas / paskutinis (visa istorija, UTC)")}</th><th scope="col">{t("Recorded evidence", "Išsaugoti įrodymai")}</th></tr></thead><tbody>{visible.map((row) => <tr key={row.id}><td className="indicator-cell" data-label={t("Hostname", "Domeno vardas")}>{row.recordAvailable ? <a href={signalPath(row.id, language)}><code>{row.domain}</code></a> : <code>{row.domain}</code>}</td><td data-label={t("Brand", "Prekės ženklas")}>{row.brand}</td><td data-label={t("Sources", "Šaltiniai")}>{row.sources.join(", ")}</td><td data-label={t("Observed (UTC)", "Stebėta (UTC)")}><span>{t("First", "Pirmas")}: <time dateTime={row.firstSeen}>{row.firstSeen}</time></span><br /><span>{t("Last", "Paskutinis")}: <time dateTime={row.lastSeen}>{row.lastSeen}</time></span></td><td data-label={t("Evidence", "Įrodymai")}><HostnameEvidence row={row} language={language} /></td></tr>)}</tbody></table></div><div className="pagination"><p>{t("Showing", "Rodoma")} <strong>{(Math.min(page, pages) - 1) * PAGE_SIZE + 1}–{Math.min(Math.min(page, pages) * PAGE_SIZE, filtered.length)}</strong> {t("of loaded", "iš įkeltų")} {number(filtered.length)}</p><div><button type="button" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>{t("Previous", "Ankstesnis")}</button><span>{t("Page", "Puslapis")} {Math.min(page, pages)} / {pages}</span><button type="button" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>{t("Next", "Kitas")}</button></div></div></div> : <p>{data?.complete ? t("No recorded hostnames match this period and search.", "Šį laikotarpį ir paiešką atitinkančių išsaugotų domenų vardų nėra.") : t("The complete period list will appear after verification.", "Visas laikotarpio sąrašas pasirodys patikrinus duomenis.")}</p>}
  </section>;
}
