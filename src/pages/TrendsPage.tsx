import { Activity, RadioTower } from "lucide-react";
import { useEffect, useState } from "react";
import { ArtifactHero, PageShell, type StaticPageLanguage } from "../components/ArtifactPageShell.tsx";
import { formatEventDateTime } from "../lib/staticPageFormat.ts";
import type { DailyTrendRow, TrendsPageData } from "../lib/staticPageBootstrap.ts";
import { trendCollectionState, trendDayState, trendFreshness } from "../lib/trendFreshness.ts";

function formatTrendNumber(value: number, language: StaticPageLanguage): string {
  return new Intl.NumberFormat(language === "lt" ? "lt-LT" : "en-GB", { maximumFractionDigits: 2 }).format(value);
}

function CoverageBar({ row, maximum, language, now }: { row: DailyTrendRow; maximum: number; language: StaticPageLanguage; now: number }) {
  const lt = language === "lt";
  const dayState = trendDayState(row, now);
  const collectionState = trendCollectionState(row.collectorCoverage);
  const partialLabel = dayState === "partial"
    ? (lt ? "Nepilna UTC diena" : "Partial UTC day")
    : (lt ? "Nepilna suvestinės diena" : "Incomplete at cutoff");
  const schedule = row.collectorCoverage.recordedSchedulePercent;
  const listening = row.collectorCoverage.listeningCoveragePercent;
  const ceiling = row.collectorCoverage.scheduledListeningCeilingPercent;
  const bounds = row.collectorCoverage.coverageBounds;
  const upper = bounds && row.collectorCoverage.windowSeconds > 0
    ? Math.min(100, 100 * bounds.upperSeconds / row.collectorCoverage.windowSeconds) : null;
  const completedSchedule = schedule === null ? null : Math.min(100, schedule);
  const additionalAttempts = Math.max(
    0,
    row.collectorCoverage.recordedAttempts - row.collectorCoverage.scheduledSlots,
  );
  const signals = formatTrendNumber(row.discovery.uniqueSignals, language);
  const attemptRatio = lt
    ? `bandymai: ${formatTrendNumber(row.collectorCoverage.recordedAttempts, language)} / ${formatTrendNumber(row.collectorCoverage.scheduledSlots, language)}`
    : `${formatTrendNumber(row.collectorCoverage.recordedAttempts, language)} / ${formatTrendNumber(row.collectorCoverage.scheduledSlots, language)} attempts`;
  const scheduleLabel = completedSchedule === null
    ? (lt ? `Suplanuoti intervalai: nėra duomenų · ${attemptRatio}` : `Scheduled slots: unavailable · ${attemptRatio}`)
    : (lt ? `${formatTrendNumber(completedSchedule, language)}% suplanuotų intervalų · ${attemptRatio}` : `${formatTrendNumber(completedSchedule, language)}% scheduled slots · ${attemptRatio}`);
  const listeningLabel = listening === null
    ? (lt ? "Faktinis klausymosi laikas: nėra duomenų" : "Wall-clock listening: unavailable")
    : bounds && upper !== null
      ? (lt ? `Klausymosi aprėpties ribos: ${formatTrendNumber(listening, language)}–${formatTrendNumber(upper, language)}%`
        : `Wall-clock listening bounds: ${formatTrendNumber(listening, language)}–${formatTrendNumber(upper, language)}%`)
      : (lt ? `Ankstesnis klausymosi įvertis: ${formatTrendNumber(listening, language)}%` : `Legacy listening estimate: ${formatTrendNumber(listening, language)}%`);
  const ceilingLabel = ceiling === null
    ? (lt ? "Planinė riba: nėra duomenų" : "Planned ceiling: unavailable")
    : (lt ? `planinė riba: ${formatTrendNumber(ceiling, language)}%` : `planned ceiling: ${formatTrendNumber(ceiling, language)}%`);

  return <article className={`trend-row${row.partialDay ? " trend-row--partial" : ""}`} data-day-state={dayState} data-collection-state={collectionState}>
    <div className="trend-date"><time dateTime={row.date}>{row.date}</time>{row.partialDay ? <> <span>{partialLabel}</span></> : null}</div>{" "}
    <div className="trend-bars" aria-hidden="true"><progress className="discovery" max={Math.max(1, maximum)} value={row.discovery.uniqueSignals} /><progress className="schedule" max={100} value={completedSchedule ?? 0} /></div>{" "}
    <strong className="trend-signal-count">{lt ? `Unikalūs signalai: ${signals}` : `${signals} unique signals`}</strong>{" "}
    <div className="trend-metrics"><span>{scheduleLabel}</span>{additionalAttempts > 0 ? <> <em>{lt ? `Papildomi bandymai: ${formatTrendNumber(additionalAttempts, language)}` : `Additional attempts: ${formatTrendNumber(additionalAttempts, language)}`}</em></> : null} <small>{listeningLabel}</small>{" "}<small>{ceilingLabel}</small>
      {collectionState === "not-recorded" || collectionState === "limited" ? <span className="trend-collection-note">{collectionState === "not-recorded"
        ? (lt ? "Iki duomenų ribos rinkimo bandymų neužfiksuota" : "No collection attempts recorded through cutoff")
        : (lt ? "Užfiksuota mažiau nei pusė numatytų bandymų" : "Fewer than half of planned attempts recorded")}</span> : null}
    </div>
  </article>;
}

function Counts({ values, empty = "No values in the public sample" }: { values: Record<string, number>; empty?: string }) {
  const entries = Object.entries(values);
  return entries.length ? <ul className="facet-counts">{entries.slice(0, 12).map(([label, value]) => <li key={label}><span>{label}</span><strong>{value}</strong></li>)}</ul> : <p className="empty-copy">{empty}</p>;
}

export function TrendsPage({ data, language = "en" }: { data: TrendsPageData; language?: StaticPageLanguage }) {
  const lt = language === "lt";
  const [now, setNow] = useState(data.renderedAt);
  useEffect(() => {
    const updateClock = () => setNow(Date.now());
    updateClock();
    const interval = window.setInterval(updateClock, 60_000);
    return () => window.clearInterval(interval);
  }, []);
  const freshness = trendFreshness(data.trends, now);
  const maximum = Math.max(0, ...data.trends.series.map((row) => row.discovery.uniqueSignals));
  const current = data.trends.series.at(-1);
  const latestCompleteDay = data.trends.series.findLast((row) => !row.partialDay);
  const latestCompleteState = latestCompleteDay ? trendCollectionState(latestCompleteDay.collectorCoverage) : "unavailable";
  const intervalMinutes = data.trends.collectorSchedule.expectedIntervalSeconds / 60;
  const listeningMinutes = data.trends.collectorSchedule.expectedListeningSeconds / 60;
  return <PageShell currentPage="trends" language={language}>
    <ArtifactHero icon={Activity} eyebrow={lt ? "Aprėptį nurodantys matavimai" : "Coverage-aware measurements"} title={lt ? "Aptikimo tendencijos ir peržiūros kokybė" : "Discovery trends and review quality"} description={lt ? "Radaras skelbia savo veiklos rodiklius kartu su rinktuvų aprėptimi. Grafikai aprašo tik tai, ką ši atrankinė sistema pastebėjo ir paskelbė. Jie nevertina viso phishing masto Lietuvoje." : "Radar publishes its own activity beside collector coverage. The charts describe what this sampled pipeline saw and published. They do not estimate all Lithuanian phishing."} />
    <section className="trend-boundary"><RadioTower aria-hidden="true" /><div><strong>{lt ? "Kiekvienas skaičius pateikiamas su aprėptimi" : "Coverage travels with every count"}</strong><p>{lt ? "Rodikliai apima tik užfiksuotus rinkimo bandymus ir paskelbtus signalus; jie nėra viso interneto ar visų Lietuvos phishing atvejų matas." : data.trends.semantics}</p></div></section>
    <section className="trend-section">
      <div className="section-heading"><div><p className="eyebrow">{lt ? "Reta UTC seka" : "Sparse UTC series"}</p><h2>{lt ? "Kasdienis aptikimas" : "Daily discovery"}</h2></div><a href="/data/daily-trends.json">{lt ? "Atsisiųsti JSON" : "Download JSON"}</a></div>
      <div className={`trend-cutoff trend-cutoff--${freshness}`} role="status">
        <strong>{lt ? "Duomenys iki" : "Data through"} <time dateTime={data.trends.generatedAt}>{formatEventDateTime(data.trends.generatedAt, language)} UTC</time></strong>
        {freshness === "delayed" ? <p>{lt ? "Atnaujinimas vėluoja. Vėlesnė veikla neįtraukta." : "Update delayed. Later activity is not included."}</p> : null}
        {freshness === "unknown" ? <p>{lt ? "Duomenų aktualumo nustatyti nepavyko." : "Data freshness could not be determined."}</p> : null}
        {data.trends.series.some((row) => row.partialDay) ? <p>{lt ? "Nepilnos dienos rodikliai apima tik laiką iki šios ribos, net jei ta UTC diena jau pasibaigė." : "Partial-day totals cover only the time before this cutoff, even after that UTC day ends."}</p> : null}
      </div>
      {latestCompleteDay && (latestCompleteState === "limited" || latestCompleteState === "not-recorded") ? <aside className="trend-collection-warning" aria-label={lt ? "Rinkimo aprėpties ribotumas" : "Collection coverage limitation"}>
        <strong>{lt ? "Rinkimo spragos riboja palyginimą" : "Collection gaps limit comparisons"}</strong>
        <p>{lt
          ? `${latestCompleteDay.date}, naujausią pilną dieną šiuose duomenyse, užfiksuota ${latestCompleteDay.collectorCoverage.recordedAttempts} rinkimo bandymų iš ${latestCompleteDay.collectorCoverage.scheduledSlots} numatytų. Mažiau signalų nebūtinai reiškia mažiau grėsmių. Praleistas klausymosi laikas negali būti atkurtas atgaline data.`
          : `${latestCompleteDay.date}, the latest complete day in this data, has ${latestCompleteDay.collectorCoverage.recordedAttempts} recorded collection attempts against ${latestCompleteDay.collectorCoverage.scheduledSlots} planned. Fewer signals do not necessarily mean fewer threats. Missed listening time cannot be recovered retrospectively.`}</p>
        <a href="/data/pipeline-health.json">{lt ? "Rinkimo būklės duomenys (JSON)" : "Collection health data (JSON)"}</a>
      </aside> : null}
      <div className="trend-legend"><span><i className="discovery" /> {lt ? "unikalūs signalai" : "unique signals"}</span><span><i className="schedule" /> {lt ? "užfiksuoti suplanuoti intervalai" : "scheduled slots recorded"}</span></div>
      <p className="trend-method-note">{lt ? `Grafiko įvykdymas lygina užfiksuotus bandymus su numatytais intervalais. Faktinis klausymosi laikas rodomas greta kiekvienos dienos planinės ribos. Rinktuvas numato ${formatTrendNumber(listeningMinutes, language)} min. klausymąsi kas ${formatTrendNumber(intervalMinutes, language)} min.` : `Schedule completion compares recorded attempts with expected slots. Wall-clock listening is shown beside each day's planned ceiling. The collector plans ${formatTrendNumber(listeningMinutes, language)} listening minutes in every ${formatTrendNumber(intervalMinutes, language)}-minute interval.`}</p>
      <div className="trend-chart">{data.trends.series.map((row) => <CoverageBar key={row.date} row={row} maximum={maximum} language={language} now={now} />)}</div>
      <p className="boundary-note">{lt ? `Rodomos dienos, kuriomis užfiksuota rinkimo arba publikavimo veikla. Suvestinės intervale praleista dienų be įrašų: ${data.trends.omittedZeroDays}. Datos po duomenų ribos yra nežinomos, o ne nulinės.` : `Dates with recorded collection or publication activity are shown. ${data.trends.omittedZeroDays} dates with neither are omitted within the saved range. Dates after the data cutoff are unknown, not zero.`}</p>
    </section>
    <section className="quality-grid"><article><p className="eyebrow">{lt ? "Naujausia užfiksuota diena" : "Latest recorded day"}</p><h2>{current?.date ?? data.trends.to}</h2><dl><div><dt>{lt ? "Unikalūs signalai" : "Unique signals"}</dt><dd>{current?.discovery.uniqueSignals ?? 0}</dd></div><div><dt>{lt ? "Pirmosios publikacijos" : "First publications"}</dt><dd>{current?.discovery.firstPublications ?? 0}</dd></div><div><dt>{lt ? "Pakartotiniai stebėjimai" : "Reobservations"}</dt><dd>{current?.discovery.reobservations ?? 0}</dd></div><div><dt>{lt ? "Sėkmingi bandymai" : "Healthy attempts"}</dt><dd>{current?.collectorCoverage.healthyAttempts ?? 0}</dd></div></dl></article><article><p className="eyebrow">{lt ? "Analitiko imtis" : "Analyst sample"}</p><h2>{lt ? "Peržiūros aprėptis" : "Review coverage"}</h2><dl><div><dt>{lt ? "Tinkami signalai" : "Eligible signals"}</dt><dd>{data.quality.reviewCoverage.eligiblePublishedSignals}</dd></div><div><dt>{lt ? "Įvertinta" : "Assessed"}</dt><dd>{data.quality.reviewCoverage.assessedSignals}</dd></div><div><dt>{lt ? "Aprėptis" : "Coverage"}</dt><dd>{data.quality.reviewCoverage.percent ?? (lt ? "Nėra duomenų" : "Unavailable")}{data.quality.reviewCoverage.percent !== null ? "%" : ""}</dd></div><div><dt>{lt ? "Medianinis vėlavimas" : "Median latency"}</dt><dd>{data.quality.reviewLatencyHours.median ?? (lt ? "Nėra duomenų" : "Unavailable")}{data.quality.reviewLatencyHours.median !== null ? (lt ? " val." : "h") : ""}</dd></div></dl></article><article className="quality-warning"><p className="eyebrow">{lt ? "Tikslumas" : "Precision"}</p><h2>{lt ? "Kol kas patikimai neapskaičiuojamas" : "Not supportable yet"}</h2><p>{lt ? "Nėra pagrįsto atrankos plano ar visos populiacijos vertinimo, todėl populiacijos tikslumo patikimai įvertinti negalima." : data.quality.precision.reason}</p></article></section>
    <section className="quality-facets"><article><h3>{lt ? "Peržiūros rezultatai" : "Review outcomes"}</h3><Counts values={data.quality.reviewSample.outcomes} empty={lt ? "Viešoje imtyje reikšmių nėra" : "No values in the public sample"} /></article><article><h3>{lt ? "Peržiūrėtos imties įrodymai" : "Evidence in reviewed sample"}</h3><Counts values={data.quality.reviewSample.byEvidence} empty={lt ? "Viešoje imtyje reikšmių nėra" : "No values in the public sample"} /></article><article><h3>{lt ? "Dabartinės išimtys" : "Current exclusions"}</h3><Counts values={data.quality.currentExclusions.byReason} empty={lt ? "Viešoje imtyje reikšmių nėra" : "No values in the public sample"} /></article></section>
  </PageShell>;
}
