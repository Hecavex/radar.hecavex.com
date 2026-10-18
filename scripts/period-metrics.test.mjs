/* global Response, setTimeout */
import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { fileURLToPath, URL } from "node:url";
import { TextEncoder } from "node:util";
import { act, createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import ts from "typescript";
import { loadPeriodOverview, observedHostnamesAsCsv, observedHostnamesAsJson, parseObservedHostnameIndex, parseObservedHostnameRecords, parsePeriodMetrics, periodOverviewPreview, periodTotals, selectPeriodRecords } from "../src/lib/periodMetrics.ts";
import { decodeSnapshotBootstrap, encodeSnapshotBootstrap } from "../src/lib/snapshotBootstrap.ts";

registerHooks({ load(url, context, nextLoad) {
  if (url.startsWith("file:") && url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: ts.transpileModule(readFileSync(fileURLToPath(url), "utf8"), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2023 } }).outputText };
  return nextLoad(url, context);
} });
const { PeriodOverview } = await import("../src/components/PeriodOverview.tsx");
const { renderPrerenderedPage, renderLithuanianPage } = await import("../src/prerender.ts");
const { Documentation } = await import("../src/components/Documentation.tsx");
const { LtDocumentation } = await import("../src/lt/LtDocumentation.tsx");
const { Methodology } = await import("../src/components/Methodology.tsx");

const asOf = "2026-10-15T11:02:36.097Z";
function record(id, times) {
  const sorted = [...times].sort();
  const days = Object.fromEntries(sorted.map((time) => [time.slice(0, 10), time]));
  return {
    id: id.repeat(20), domain: `${id}[.]example`, domainGroup: `${id}[.]example`, brand: "Example",
    firstSeen: sorted[0], lastSeen: sorted.at(-1), firstRecordedAt: null, firstPublishedAt: null,
    observedDays: Object.keys(days).sort(), observedDayLastSeen: days, sources: ["CertStream"],
    match: { score: null, reasonCodes: [], policyVersion: "legacy-unknown" }, assessment: null, recordAvailable: false,
  };
}

test("trailing periods include the exact lower source boundary and deduplicate host identities", () => {
  const rows = [
    record("a", ["2026-08-01T00:00:00.000Z", asOf]),
    record("b", ["2026-09-15T11:02:36.097Z"]),
    record("c", ["2026-09-15T11:02:36.096Z"]),
  ];
  const window = { key: "30d", startInclusive: "2026-09-15T11:02:36.097Z", endExclusive: "2026-10-15T11:02:36.098Z" };
  assert.deepEqual(selectPeriodRecords(rows, window).map((row) => row.id), ["a".repeat(20), "b".repeat(20)]);
});

test("calendar membership does not interpolate unobserved days; partial lower days have exact candidate-day counts", () => {
  const rows = [record("a", ["2026-08-31T23:00:00.000Z", "2026-10-01T00:00:00.000Z"])];
  const september = { startInclusive: "2026-09-01T00:00:00.000Z", endExclusive: "2026-10-01T00:00:00.000Z" };
  assert.deepEqual(selectPeriodRecords(rows, september), []);
  const trailing = { startInclusive: "2026-09-15T11:02:36.097Z", endExclusive: "2026-10-15T11:02:36.098Z" };
  const daily = [record("b", ["2026-09-15T11:02:36.096Z", "2026-09-16T00:00:00.000Z", asOf])];
  assert.deepEqual(periodTotals(daily, trailing), { uniqueHostnames: 1, domainGroups: 1, candidateDays: 2 });
});

const bytes = (value) => new TextEncoder().encode(JSON.stringify(value));
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
function cohort(rows = [record("a", ["2026-09-16T00:00:00.000Z", asOf])], timeBasis = "source-observation-time") {
  rows.forEach((row) => { row.id = sha256(row.domain).slice(0, 20); });
  rows.sort((a, b) => a.id.localeCompare(b.id));
  const grouping = { method: "private-psl-registrable-domain", version: "tldextract-5.4.0", privateSuffixes: true, pslSha256: "a".repeat(64) };
  const policyVersions = { identity: "v1", matching: "v1", review: "v1", metrics: "v1", store: "v1" };
  const coverage = { availableFrom: rows.length ? rows.map((row) => row.firstSeen).sort()[0] : null, recordedFrom: null, publicationRecordedFrom: null, recoveredFrom: null, recoveredThrough: null, recoveredDays: [], missingDays: [], historyComplete: false, collectionComplete: false, historicalRecordingTimesComplete: false, historicalPublicationTimesComplete: false, basis: "recorded-and-recovered-observation-facts", partialCurrentDay: true };
  const partBytes = bytes(rows);
  const hash = sha256(partBytes);
  const index = { schemaVersion: 1, dataset: "radar-observed-hostnames", generatedAt: asOf, asOf, recordCount: rows.length, grouping, policyVersions, coverage, partitions: rows.length ? [{ path: `/data/observed-hostnames-parts/${hash}.json`, bytes: partBytes.length, sha256: hash, records: rows.length }] : [] };
  const indexBytes = bytes(index);
  const windows = [30, 90, 365].map((days) => ({ key: `${days}d`, startInclusive: new Date(Date.parse(asOf) - days * 86400000).toISOString(), endExclusive: new Date(Date.parse(asOf) + 1).toISOString(), firstRecordedHostnames: null, firstPublishedHostnames: null, exactWithinRecordedData: true, completeCollection: false }));
  windows.push({ ...windows[0], key: "all", startInclusive: null });
  windows.forEach((window) => Object.assign(window, periodTotals(rows, window)));
  const metrics = { schemaVersion: 1, dataset: "radar-period-metrics", generatedAt: asOf, asOf, timeBasis, identityUnit: "canonical-hostname", population: "public-eligible-recorded-hostnames", hostnamesSha256: sha256(indexBytes), grouping, policyVersions, coverage, windows };
  const files = new Map([["/data/period-metrics-v1.json", bytes(metrics)], ["/data/observed-hostnames-v1.json", indexBytes], ...(rows.length ? [[index.partitions[0].path, partBytes]] : [])]);
  return { rows, metrics, index, files, readBytes: async (path) => { assert(files.has(path), path); return files.get(path); } };
}

test("complete cohort loader binds exact bytes, count, identity and metrics before enabling exports", async () => {
  const fixture = cohort();
  const loaded = await loadPeriodOverview({ readBytes: fixture.readBytes });
  assert.equal(loaded.complete, true);
  assert.deepEqual(loaded.records, fixture.rows);
  assert.equal(parsePeriodMetrics(fixture.metrics), fixture.metrics);
  assert.equal(parseObservedHostnameIndex(fixture.index), fixture.index);
  fixture.files.set(fixture.index.partitions[0].path, bytes([{ ...fixture.rows[0], brand: "tampered" }]));
  await assert.rejects(loadPeriodOverview({ readBytes: fixture.readBytes }), /digest|bytes/i);
});

test("timing provenance is bounded and explicit while older records and metric time bases remain readable", async () => {
  const legacy = cohort();
  const old = await loadPeriodOverview({ readBytes: legacy.readBytes });
  assert.equal(old.metrics.timeBasis, "source-observation-time");
  assert.equal(Object.hasOwn(old.records[0], "sourceTimeProvenances"), false);
  const row = { ...record("b", [asOf]), sourceTimeProvenances: ["collector-time-fallback", "legacy-normalized-unknown", "provider-observation-time"] };
  const current = cohort([row]);
  current.metrics.timeBasis = "source-observation-or-explicit-collector-fallback";
  current.files.set("/data/period-metrics-v1.json", bytes(current.metrics));
  const full = await loadPeriodOverview({ readBytes: current.readBytes });
  assert.deepEqual(full.records[0].sourceTimeProvenances, row.sourceTimeProvenances);
  assert.equal(full.metrics.windows[0].uniqueHostnames, 1);
  assert.equal(full.records[0].firstRecordedAt, null);
  assert.equal(full.records[0].firstPublishedAt, null);
  for (const sourceTimeProvenances of [[], null, "provider-observation-time", ["unknown"], ["provider-observation-time", "provider-observation-time"], ["provider-observation-time", "collector-time-fallback"], ["collector-time-fallback", "legacy-normalized-unknown", "provider-observation-time", "unexpected"]]) {
    assert.throws(() => parseObservedHostnameRecords([{ ...row, sourceTimeProvenances }], asOf));
  }
  assert.throws(() => parsePeriodMetrics({ ...current.metrics, timeBasis: "collector-time" }));
});

test("EN/LT observation times disclose provider, fallback and incomplete legacy provenance without changing counts", async () => {
  const fixture = cohort([
    { ...record("a", [asOf]), sourceTimeProvenances: ["provider-observation-time"] },
    { ...record("b", [asOf]), sourceTimeProvenances: ["collector-time-fallback", "provider-observation-time"] },
    { ...record("c", [asOf]), sourceTimeProvenances: ["legacy-normalized-unknown"] },
    record("d", [asOf]),
  ], "source-observation-or-explicit-collector-fallback");
  const full = await loadPeriodOverview({ readBytes: fixture.readBytes });
  for (const language of ["en", "lt"]) {
    const html = renderToStaticMarkup(createElement(PeriodOverview, { initialData: full, language }));
    const dom = new JSDOM(html);
    try {
      assert.match(html, /data-period-count="4"/);
      assert.match(html, language === "en" ? /provider observation time or a declared collector fallback/i : /teikėjo stebėjimo laikas arba deklaruotas rinkiklio laikas/i);
      assert.doesNotMatch(html, /First\/last seen are upstream source observation times/);
      const rows = [...dom.window.document.querySelectorAll("tbody tr")];
      const byDomain = (domain) => rows.find((row) => row.querySelector(".indicator-cell code").textContent === domain);
      const fallback = dom.window.document.querySelectorAll(".period-time-fallback");
      assert.equal(fallback.length, 1);
      assert.match(fallback[0].textContent, language === "en" ? /Collector fallback used/ : /Naudotas rinkiklio laikas/);
      assert.match(byDomain("a[.]example").querySelector("details").textContent, language === "en" ? /Provider observation time/ : /Teikėjo stebėjimo laikas/);
      assert.match(byDomain("b[.]example").querySelector("details").textContent, language === "en" ? /Declared collector fallback/ : /Deklaruotas rinkiklio laikas/);
      for (const domain of ["c[.]example", "d[.]example"]) assert.match(byDomain(domain).querySelector("details").textContent, language === "en" ? /Legacy timing provenance incomplete/ : /Ankstesnių laikų kilmė neišsami/);
      assert.equal(dom.window.document.querySelectorAll('a[href^="https://a."], a[href^="https://b."]').length, 0);
    } finally { dom.window.close(); }
  }
});

test("matching exports retain declared timing provenance and leave absent legacy provenance unknown", async () => {
  const fixture = cohort([
    { ...record("a", [asOf]), sourceTimeProvenances: ["collector-time-fallback", "provider-observation-time"] },
    record("b", [asOf]),
  ], "source-observation-or-explicit-collector-fallback");
  const full = await loadPeriodOverview({ readBytes: fixture.readBytes });
  const json = JSON.parse(observedHostnamesAsJson(full.records, full, full.metrics.windows[0]));
  assert.deepEqual(json.records.find((row) => row.domain === "a[.]example").sourceTimeProvenances, ["collector-time-fallback", "provider-observation-time"]);
  assert.equal(Object.hasOwn(json.records.find((row) => row.domain === "b[.]example"), "sourceTimeProvenances"), false);
  assert.match(json.warning, /provider observation time or declared collector fallback/);
  const lines = observedHostnamesAsCsv(full.records, full, full.metrics.windows[0]).trimEnd().split("\r\n");
  assert.match(lines[0], /,"source_time_provenances"$/);
  assert.match(lines.find((line) => line.includes('"a[.]example"')), /,"collector-time-fallback;provider-observation-time"$/);
  assert.match(lines.find((line) => line.includes('"b[.]example"')), /,""$/);
});

test("complete cohorts cannot hide explicit collector fallback behind the older observation-only time basis", async () => {
  const fixture = cohort([{ ...record("a", [asOf]), sourceTimeProvenances: ["collector-time-fallback"] }], "source-observation-or-explicit-collector-fallback");
  assert.equal((await loadPeriodOverview({ readBytes: fixture.readBytes })).records.length, 1);
  fixture.metrics.timeBasis = "source-observation-time";
  fixture.files.set("/data/period-metrics-v1.json", bytes(fixture.metrics));
  await assert.rejects(loadPeriodOverview({ readBytes: fixture.readBytes }), /time basis|fallback/i);
  const legacy = cohort([record("b", [asOf])], "source-observation-or-explicit-collector-fallback");
  assert.equal((await loadPeriodOverview({ readBytes: legacy.readBytes })).complete, true);
});

test("every advertised part is required and duplicate canonical hostname rows cannot inflate totals", async () => {
  const fixture = cohort([record("a", [asOf]), record("b", [asOf])]);
  fixture.index.partitions = fixture.rows.map((row) => {
    const body = bytes([row]);
    const hash = sha256(body);
    const part = { path: `/data/observed-hostnames-parts/${hash}.json`, bytes: body.length, sha256: hash, records: 1 };
    fixture.files.set(part.path, body);
    return part;
  });
  const indexBytes = bytes(fixture.index);
  fixture.metrics.hostnamesSha256 = sha256(indexBytes);
  fixture.files.set("/data/observed-hostnames-v1.json", indexBytes);
  fixture.files.set("/data/period-metrics-v1.json", bytes(fixture.metrics));
  assert.equal((await loadPeriodOverview({ readBytes: fixture.readBytes })).records.length, 2);
  fixture.files.delete(fixture.index.partitions[1].path);
  await assert.rejects(loadPeriodOverview({ readBytes: fixture.readBytes }));
  const duplicate = cohort([record("a", [asOf]), record("a", [asOf])]);
  await assert.rejects(loadPeriodOverview({ readBytes: duplicate.readBytes }), /unique/);
});

test("new contracts reject unknown keys, stale cohorts and false numeric totals", async () => {
  const fixture = cohort();
  assert.throws(() => parsePeriodMetrics({ ...fixture.metrics, surprise: true }));
  assert.throws(() => parseObservedHostnameIndex({ ...fixture.index, records: [] }));
  assert.throws(() => parsePeriodMetrics({ ...fixture.metrics, windows: fixture.metrics.windows.map((window) => ({ ...window, firstPublishedHostnames: 0 })) }));
  fixture.metrics.windows[0].uniqueHostnames = 2;
  fixture.files.set("/data/period-metrics-v1.json", bytes(fixture.metrics));
  await assert.rejects(loadPeriodOverview({ readBytes: fixture.readBytes }), /totals/i);
  fixture.metrics.hostnamesSha256 = "b".repeat(64);
  fixture.files.set("/data/period-metrics-v1.json", bytes(fixture.metrics));
  await assert.rejects(loadPeriodOverview({ readBytes: fixture.readBytes }), /digest/i);
});

test("a verified empty recorded population is known zero, while unavailable data stays unknown", async () => {
  const fixture = cohort([]);
  const full = await loadPeriodOverview({ readBytes: fixture.readBytes });
  assert.equal(full.index.partitions.length, 0);
  assert.equal(full.metrics.windows[0].uniqueHostnames, 0);
  const known = renderToStaticMarkup(createElement(PeriodOverview, { initialData: periodOverviewPreview(full) }));
  assert.match(known, /data-period-count="0"/);
  const unavailable = renderToStaticMarkup(createElement(PeriodOverview));
  assert.match(unavailable, /data-period-count="unknown"/);
  assert.doesNotMatch(unavailable, /data-period-count="0"/);
});

test("SSR preserves authoritative EN/LT counts with a bounded preview, disabled exports and explicit unknown clocks", async () => {
  const fixture = cohort();
  const full = await loadPeriodOverview({ readBytes: fixture.readBytes });
  const preview = periodOverviewPreview(full, 2);
  assert.equal(preview.records.length, 0);
  const unknownAssessment = renderToStaticMarkup(createElement(PeriodOverview, { initialData: full }));
  assert(unknownAssessment.includes("No published assessment"));
  assert(!unknownAssessment.includes("not assessed"));
  for (const language of ["en", "lt"]) {
    const html = renderToStaticMarkup(createElement(PeriodOverview, { initialData: preview, language }));
    assert.match(html, /data-period-count="1"/);
    assert.match(html, /aria-pressed="true"/);
    assert.match(html, /<noscript>/);
    assert.match(html, language === "en" ? /Not tracked yet/ : /Dar neskaičiuojama/);
    assert.doesNotMatch(html, /period-clock-pending">(?:Unavailable|Nepasiekiama)/);
    assert.match(html, /disabled=""[^>]*>JSON/);
    assert.doesNotMatch(html, /href="https?:\/\/a\./);
  }
  assert.throws(() => observedHostnamesAsJson([], preview, fixture.metrics.windows[0]), /Complete/);
  const row = { ...full.records[0], brand: "=unsafe()" };
  assert.match(observedHostnamesAsCsv([row], full, fixture.metrics.windows[0]), /"'=unsafe\(\)"/);
  const exported = JSON.parse(observedHostnamesAsJson(full.records, full, fixture.metrics.windows[0]));
  assert.equal(exported.records[0].domain, "a[.]example");
  assert.equal(exported.records[0].firstPublishedAt, null);
  assert.equal(exported.hostnamesSha256, fixture.metrics.hostnamesSha256);
});

test("real overview SSR and bootstrap preserve period counts independently of current shortlist and preview size", async () => {
  const fixture = cohort();
  const preview = periodOverviewPreview(await loadPeriodOverview({ readBytes: fixture.readBytes }), 2);
  const snapshot = { schemaVersion: 2, dataset: "live", generatedAt: asOf, lastSuccessfulSyncAt: asOf, signals: [], sources: [
    { name: "CertStream", homepage: "https://certstream.dev/", fetchedAt: asOf, records: 0, state: "healthy", note: null },
    { name: "URLScan", homepage: "https://urlscan.io/", fetchedAt: asOf, records: 0, state: "healthy", note: null },
    { name: "HECAVEX", homepage: "https://hecavex.com/", fetchedAt: asOf, records: 0, state: "healthy", note: null },
  ] };
  const decoded = decodeSnapshotBootstrap(encodeSnapshotBootstrap(snapshot, Date.parse(asOf), preview));
  assert.equal(decoded.periodData.complete, false);
  assert.equal(decoded.periodData.metrics.windows[0].uniqueHostnames, 1);
  assert.equal(decoded.periodData.records.length, 0);
  const en = renderPrerenderedPage("radar", snapshot, Date.parse(asOf), undefined, "en", undefined, preview);
  const lt = renderLithuanianPage("radar", snapshot, Date.parse(asOf), preview);
  for (const html of [en, lt]) {
    assert.match(html, /data-period-count="1"/);
    // Shortlist first; the overview keeps only a compact summary that links to the complete inventory.
    assert(html.indexOf('id="signals-title"') < html.indexOf('id="observed-hostnames"'));
    assert.doesNotMatch(html, /period-table|period-controls|>JSON</);
  }
  assert.match(en, /href="\/history\/#observed-hostnames"/);
  assert.match(lt, /href="\/lt\/istorija\/#observed-hostnames"/);
  assert.match(en, /Last 30 days: <strong>1<\/strong> unique hostnames recorded/);
  assert.match(en, /Current shortlist<\/span><strong>0/);
  assert.match(en, /Observation first seen 24h/);
  assert.match(lt, /Pirmas stebėjimas per 24 val\./);
  assert.doesNotMatch(en, /Source first seen 24h/);
  assert.doesNotMatch(en, /First published 24h/);
});

test("strict records preserve an explicit suspicious analyst assessment separately from match score", () => {
  const fixture = cohort();
  const assessed = { ...fixture.rows[0], assessment: { verdict: "suspicious", assessedAt: asOf, decisionId: "a".repeat(24), analystConfidence: 88, evidenceReferences: ["review:second", "review:first"] } };
  assert.equal(parseObservedHostnameRecords([assessed], asOf)[0].match.score, null);
  assert.equal(parseObservedHostnameRecords([assessed], asOf)[0].assessment.verdict, "suspicious");
  for (const invalid of [{ ...assessed, extra: true }, { ...assessed, firstPublishedAt: asOf }, { ...assessed, observedDayLastSeen: {} }, { ...assessed, assessment: { ...assessed.assessment, analystConfidence: 101 } }, { ...assessed, assessment: { ...assessed.assessment, evidenceReferences: [] } }]) assert.throws(() => parseObservedHostnameRecords([invalid], asOf));
});

test("clock counts become available only for windows wholly after the corresponding activation", () => {
  const { metrics } = cohort();
  metrics.coverage.recordedFrom = "2026-09-01T00:00:00.000Z";
  metrics.windows[0].firstRecordedHostnames = 0;
  assert.equal(parsePeriodMetrics(metrics).windows[0].firstRecordedHostnames, 0);
  metrics.windows[1].firstRecordedHostnames = 0;
  assert.throws(() => parsePeriodMetrics(metrics));
});

test("EN/LT public documentation links the independent v1 schemas and distinguishes durable facts from legacy expiry", () => {
  for (const language of ["en", "lt"]) {
    const documentation = renderToStaticMarkup(createElement(language === "en" ? Documentation : LtDocumentation));
    const methodology = renderToStaticMarkup(createElement(Methodology, { language }));
    for (const path of ["/data/observed-hostnames-v1.json", "/data/period-metrics-v1.json", "/data/schemas/observed-hostnames-index-v1.schema.json", "/data/schemas/period-metrics-v1.schema.json"]) assert(documentation.includes(`href="${path}"`));
    assert(documentation.includes("OBSERVATIONS.md"));
    assert(documentation.includes("PERIOD-METRICS.md"));
    assert.match(methodology, language === "en" ? /subdomains count separately/ : /subdomenai skaičiuojami atskirai/);
    assert.match(methodology, language === "en" ? /does not expire durable observation facts/ : /neištrina ilgalaikių stebėjimo faktų/);
    assert.match(methodology, language === "en" ? /clocks remain null/ : /laikai lieka null/);
    assert.match(methodology, language === "en" ? /provider observation time or declared collector fallback/ : /teikėjo stebėjimo laikas arba deklaruotas rinkiklio laikas/);
    assert.match(methodology, language === "en" ? /historical timing provenance remains incomplete/i : /istorinių laikų kilmė lieka neišsami/i);
    assert.doesNotMatch(methodology, /First\/last seen are source observation times/);
    assert.match(documentation, language === "en" ? /provider observation time or declared collector fallback/ : /teikėjo stebėjimo laikas arba deklaruotas rinkiklio laikas/);
  }
});

test("interactive presets and Unicode local search use the verified cohort; failed loads preserve counts and disable exports", async () => {
  const unicodeRow = record("a", [asOf]);
  unicodeRow.domain = new URL("https://swedbanƙ.example").hostname.replaceAll(".", "[.]");
  unicodeRow.domainGroup = unicodeRow.domain;
  const fixture = cohort([unicodeRow, record("b", ["2026-08-01T00:00:00.000Z"])]);
  const september = { ...fixture.metrics.windows[0], key: "month:2026-09", startInclusive: "2026-09-01T00:00:00.000Z", endExclusive: "2026-10-01T00:00:00.000Z" };
  Object.assign(september, periodTotals(fixture.rows, september));
  fixture.metrics.windows.push(september);
  fixture.files.set("/data/period-metrics-v1.json", bytes(fixture.metrics));
  const full = await loadPeriodOverview({ readBytes: fixture.readBytes });
  const dom = new JSDOM('<div id="root"></div>', { url: "https://radar.hecavex.com/" });
  const saved = Object.fromEntries(["window", "document", "navigator", "fetch", "IS_REACT_ACT_ENVIRONMENT"].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.defineProperties(globalThis, { window: { value: dom.window, configurable: true }, document: { value: dom.window.document, configurable: true }, navigator: { value: dom.window.navigator, configurable: true }, IS_REACT_ACT_ENVIRONMENT: { value: true, configurable: true } });
  const requests = [];
  Object.defineProperty(globalThis, "fetch", { configurable: true, value: async (path) => { requests.push(path); return new Response(fixture.files.get(path), { status: fixture.files.has(path) ? 200 : 404 }); } });
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(dom.window.document.getElementById("root"));
  const downloads = [];
  const createUrl = URL.createObjectURL;
  const revokeUrl = URL.revokeObjectURL;
  URL.createObjectURL = (blob) => { downloads.push(blob); return "blob:local-test"; };
  URL.revokeObjectURL = () => {};
  dom.window.HTMLAnchorElement.prototype.click = () => {};
  const settle = async (predicate) => { for (let i = 0; i < 80 && !predicate(); i++) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); }); assert(predicate()); };
  try {
    await act(async () => root.render(createElement(PeriodOverview, { initialData: periodOverviewPreview(full) })));
    const buttons = () => [...dom.window.document.querySelectorAll("button")];
    await settle(() => !buttons().find((button) => button.textContent === "JSON").disabled);
    await act(async () => buttons().find((button) => button.textContent === "All recorded").click());
    assert.equal(dom.window.document.querySelector("[data-period-count]").textContent, "2");
    const input = dom.window.document.querySelector('input[type="search"]');
    await act(async () => { Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set.call(input, "swedbanƙ"); input.dispatchEvent(new dom.window.Event("input", { bubbles: true })); });
    assert.match(dom.window.document.querySelector(".period-list-status").textContent, /Showing 1 of 2/);
    assert.equal(dom.window.document.querySelectorAll("tbody tr").length, 1);
    for (const query of [unicodeRow.domain, unicodeRow.domain.replaceAll("[.]", "."), "swedbanƙ.example", "swedbanƙ[.]example"]) {
      await act(async () => { Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set.call(input, query); input.dispatchEvent(new dom.window.Event("input", { bubbles: true })); });
      assert.match(dom.window.document.querySelector(".period-list-status").textContent, /Showing 1 of 2/, query);
    }
    await act(async () => buttons().find((button) => button.textContent === "JSON").click());
    const exported = JSON.parse(await downloads[0].text());
    assert.equal(exported.recordCount, 1);
    assert.equal(exported.records[0].domain, unicodeRow.domain);
    await act(async () => buttons().find((button) => button.textContent === "CSV").click());
    const csv = await downloads[1].text();
    assert.match(csv, /xn--/);
    assert.doesNotMatch(csv, /"b\[\.\]example"/);
    await act(async () => { dom.window.document.querySelector(".period-controls select").value = "month:2026-09"; dom.window.document.querySelector(".period-controls select").dispatchEvent(new dom.window.Event("change", { bubbles: true })); });
    assert.equal(dom.window.document.querySelector("[data-period-count]").textContent, "0");
    await act(async () => {
      Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set.call(input, ""); input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      for (const dateInput of dom.window.document.querySelectorAll('input[type="date"]')) { Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set.call(dateInput, "2026-08-01"); dateInput.dispatchEvent(new dom.window.Event("input", { bubbles: true })); }
    });
    await act(async () => buttons().find((button) => button.textContent === "Apply dates").click());
    assert.equal(dom.window.document.querySelector("[data-period-count]").textContent, "1");
    assert.match(dom.window.document.querySelector("tbody").textContent, /b\[\.\]example/);
    assert(requests.every((path) => path.startsWith("/data/")));
    await act(async () => root.unmount());
    Object.defineProperty(globalThis, "fetch", { configurable: true, value: async () => new Response("broken", { status: 503 }) });
    const failed = createRoot(dom.window.document.getElementById("root"));
    await act(async () => failed.render(createElement(PeriodOverview, { initialData: periodOverviewPreview(full) })));
    await settle(() => dom.window.document.querySelector(".period-load-notice") !== null);
    assert.equal(dom.window.document.querySelector("[data-period-count]").textContent, "1");
    assert(buttons().find((button) => button.textContent === "JSON").disabled);
    assert.match(dom.window.document.querySelector(".period-list-status").textContent, /preview is not the period total/);
    await act(async () => failed.unmount());
  } finally {
    URL.createObjectURL = createUrl;
    URL.revokeObjectURL = revokeUrl;
    for (const [key, descriptor] of Object.entries(saved)) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key]; }
    dom.window.close();
  }
});
