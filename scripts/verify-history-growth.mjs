// Opt-in full production build with synthetic history in an isolated temporary
// tree. It never modifies source data, contacts indicators or deploys a site.
import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { execFileSync } from "node:child_process";
import process from "node:process";
import { createHash } from "node:crypto";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "vite";
import { parseHistory } from "../src/lib/historyData.ts";
import { loadPeriodOverview, periodTotals } from "../src/lib/periodMetrics.ts";
import { maximumOutputBytes } from "./deployment-capacity.mjs";
import { verifyGzipBudget } from "./gzip-budget.mjs";

const root = resolve(import.meta.dirname, "..");
const excluded = new Set([".git", "node_modules", "dist", ".venv", ".radar-local", ".hypothesis", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"]);
const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
const walk = (path) => readdirSync(path, { withFileTypes: true }).flatMap((entry) => entry.isDirectory() ? walk(join(path, entry.name)) : [join(path, entry.name)]);

const periodReader = (publicData) => async (path, maximumBytes) => {
  assert.ok(path.startsWith("/data/"));
  const target = resolve(publicData, path.slice("/data/".length));
  assert.ok(target.startsWith(resolve(publicData) + sep), "Growth fixture path escaped public data.");
  const bytes = readFileSync(target);
  assert.ok(bytes.byteLength <= maximumBytes, "Growth artifact exceeds its supported response limit.");
  return new Uint8Array(bytes);
};

/** Preserve the original complete cohort and exercise every new part through the browser reader. */
export async function growPeriodCohort(publicData, history, targetCount = 5000) {
  const ownedFixture = resolve(publicData, "..", "..");
  assert.ok(ownedFixture.startsWith(resolve(tmpdir()) + sep + "radar-history-growth-"),
    "Synthetic period records may only be written inside the owned temporary growth fixture.");
  assert.equal(resolve(publicData), join(ownedFixture, "public", "data"));
  const source = await loadPeriodOverview({ readBytes: periodReader(publicData) });
  const seed = history.signals[0];
  assert.ok(seed, "Growth build requires one valid source-history contract fixture.");
  assert.ok(history.signals.length <= targetCount && source.records.length <= targetCount);
  const historyIds = new Set(history.signals.map((row) => row.id));
  for (const row of source.records) {
    if (!historyIds.has(row.id)) {
      history.signals.push({ ...seed, id: row.id, domain: row.domain, brand: row.brand,
        firstSeen: row.firstSeen, lastSeen: row.lastSeen, sources: row.sources,
        observationCount: row.observedDays.length, statusTransitions: [] });
      historyIds.add(row.id);
    }
  }
  assert.ok(history.signals.length <= targetCount, "Existing combined cohorts exceed the growth target.");
  for (let number = 0; history.signals.length < targetCount; number += 1) {
    const domain = `growth-fixture-${number}[.]example`;
    const id = digest(domain).slice(0, 20);
    if (historyIds.has(id)) continue;
    history.signals.push({ ...seed, domain, id, firstSeen: source.index.asOf, lastSeen: source.index.asOf,
      observationCount: 1, statusTransitions: [] });
    historyIds.add(id);
  }
  const byId = new Map(source.records.map((row) => [row.id, { ...row, recordAvailable: true }]));
  const added = history.signals.filter((row) => !byId.has(row.id));
  const canonical = JSON.parse(execFileSync("python", ["-B", "-c",
    "import json,sys; from hecavex_radar.observation_store import canonical_hostname,grouping_metadata; " +
    "print(json.dumps({'grouping':grouping_metadata(),'hosts':[canonical_hostname(x) for x in json.load(sys.stdin)]}))"],
  { cwd: root, input: JSON.stringify(added.map((row) => row.domain)), encoding: "utf8", maxBuffer: 4 * 1024 * 1024 }));
  assert.deepEqual(canonical.grouping, source.index.grouping, "Growth fixture requires the same pinned PSL runtime.");
  const groups = new Map(canonical.hosts.map((row) => [row.id, row.domainGroup]));
  for (const row of history.signals) {
    if (byId.has(row.id)) continue;
    const days = [...new Set([row.firstSeen.slice(0, 10), row.lastSeen.slice(0, 10)])].sort();
    const lastByDay = Object.fromEntries(days.map((day) => [day,
      day === row.lastSeen.slice(0, 10) ? row.lastSeen : row.firstSeen]));
    byId.set(row.id, {
      id: row.id, domain: row.domain, domainGroup: groups.get(row.id), brand: row.brand,
      firstSeen: row.firstSeen, lastSeen: row.lastSeen,
      firstRecordedAt: source.index.coverage.historicalRecordingTimesComplete ||
        source.index.coverage.historicalPublicationTimesComplete ? source.index.asOf : null,
      firstPublishedAt: source.index.coverage.historicalPublicationTimesComplete ? source.index.asOf : null,
      observedDays: days, observedDayLastSeen: lastByDay, sources: row.sources,
      match: { score: null, reasonCodes: row.reasonCodes, policyVersion: "synthetic-growth-fixture" },
      assessment: null, recordAvailable: true,
    });
  }
  const records = [...byId.values()].sort((left, right) => left.id.localeCompare(right.id));
  assert.equal(records.length, targetCount);
  assert.equal(new Set(records.map((row) => row.domain)).size, targetCount);
  assert.ok(records.every((row) => historyIds.has(row.id)), "A growth hostname has no generated history route.");
  const parts = [];
  const partRoot = join(publicData, "observed-hostnames-parts");
  mkdirSync(partRoot, { recursive: true });
  let chunk = [];
  let used = 3;
  const flush = () => {
    if (!chunk.length) return;
    const bytes = Buffer.from(JSON.stringify(chunk) + "\n");
    assert.ok(bytes.length <= 256 * 1024, "Synthetic hostname part exceeds production limit.");
    const sha256 = digest(bytes);
    writeFileSync(join(partRoot, `${sha256}.json`), bytes);
    parts.push({ path: `/data/observed-hostnames-parts/${sha256}.json`, sha256, bytes: bytes.length, records: chunk.length });
    chunk = [];
    used = 3;
  };
  for (const row of records) {
    const bytes = Buffer.byteLength(JSON.stringify(row));
    assert.ok(bytes + 3 <= 256 * 1024);
    if (chunk.length && used + bytes + 1 > 256 * 1024) flush();
    chunk.push(row);
    used += bytes + 1;
  }
  flush();
  assert.ok(parts.length <= 512);
  const coverage = { ...source.index.coverage, availableFrom: records.reduce((first, row) =>
    first === null || row.firstSeen < first ? row.firstSeen : first, source.index.coverage.availableFrom) };
  const index = { ...source.index, coverage, recordCount: records.length, partitions: parts };
  const indexBytes = Buffer.from(JSON.stringify(index) + "\n");
  assert.ok(indexBytes.length <= 256 * 1024);
  writeFileSync(join(publicData, "observed-hostnames-v1.json"), indexBytes);
  const metrics = { ...source.metrics, coverage, hostnamesSha256: digest(indexBytes), windows: source.metrics.windows.map((window) => {
    const clockCount = (field) => records.filter((row) => row[field] !== null &&
      row[field] >= (window.startInclusive ?? "") && row[field] < window.endExclusive).length;
    return { ...window, ...periodTotals(records, window),
      firstRecordedHostnames: window.firstRecordedHostnames === null ? null : clockCount("firstRecordedAt"),
      firstPublishedHostnames: window.firstPublishedHostnames === null ? null : clockCount("firstPublishedAt") };
  }) };
  const metricBytes = Buffer.from(JSON.stringify(metrics) + "\n");
  assert.ok(metricBytes.length <= 256 * 1024);
  writeFileSync(join(publicData, "period-metrics-v1.json"), metricBytes);
  const verified = await loadPeriodOverview({ readBytes: periodReader(publicData) });
  assert.equal(verified.complete, true);
  assert.equal(verified.records.length, targetCount);
  assert.equal(verified.metrics.windows.find((window) => window.key === "all").uniqueHostnames, targetCount);
  return verified;
}

async function main() {
const measureExisting = process.argv[2] === "--measure-existing";
const fixtureRoot = measureExisting ? resolve(process.argv[3]) : mkdtempSync(join(tmpdir(), "radar-history-growth-"));
assert.equal(resolve(fixtureRoot).startsWith(resolve(tmpdir()) + sep + "radar-history-growth-"), true);
function cleanup() {
  assert.equal(resolve(fixtureRoot).startsWith(resolve(tmpdir()) + sep + "radar-history-growth-"), true);
  try { unlinkSync(join(fixtureRoot, "node_modules")); } catch (error) { if (error.code !== "ENOENT") throw error; }
  rmSync(fixtureRoot, { recursive: true, force: true });
}
try {
  if (!measureExisting) {
  process.stdout.write("Preparing an isolated 5000-record history and hostname-period build fixture.\n");
  cpSync(root, fixtureRoot, { recursive: true, filter: (path) => !relative(root, path).split(sep).some((part) => excluded.has(part)) });
  symlinkSync(join(root, "node_modules"), join(fixtureRoot, "node_modules"), "junction");
  const publicData = join(fixtureRoot, "public", "data");
  const original = JSON.parse(readFileSync(join(publicData, "history.json"), "utf8"));
  const history = await parseHistory(original, async (path) => new Uint8Array(readFileSync(join(publicData, path))));
  const period = await growPeriodCohort(publicData, history);
  process.stdout.write(JSON.stringify({ growthHostnames: period.records.length,
    hostnameParts: period.index.partitions.length, originalCohortPreserved: true }) + "\n");
  const partitions = [];
  const partRoot = join(publicData, "history-parts");
  mkdirSync(partRoot, { recursive: true });
  for (let offset = 0; offset < history.signals.length; offset += 100) {
    const rows = history.signals.slice(offset, offset + 100);
    const body = Buffer.from(JSON.stringify(rows));
    assert.ok(body.length <= 256 * 1024, "Synthetic history partition exceeds production limit.");
    const sha256 = digest(body);
    writeFileSync(join(partRoot, `${sha256}.json`), body);
    partitions.push({ path: `history-parts/${sha256}.json`, sha256, bytes: body.length, signals: rows.length });
  }
  writeFileSync(join(publicData, "history.json"), JSON.stringify({ ...history, schemaVersion: 2,
    signals: [], signalCount: history.signals.length, partitionFormat: "hecavex-history-partitions-v1", partitions }));
  await build({ root: fixtureRoot, configFile: join(fixtureRoot, "vite.config.ts"), logLevel: "warn" });
  }
  process.stdout.write("Build complete. Measuring every generated page and the entire deployment.\n");
  const output = join(fixtureRoot, "dist");
  const builtPeriod = await loadPeriodOverview({ readBytes: periodReader(join(output, "data")) });
  assert.equal(builtPeriod.records.length, 5000, "The build omitted growth hostname records.");
  const files = walk(output);
  const total = files.reduce((sum, path) => sum + statSync(path).size, 0);
  const html = files.filter((path) => path.endsWith(".html"));
  let maximumHtmlGzipUpperBound = 0;
  let exactlyMeasuredPages = 0;
  for (const [index, path] of html.entries()) {
    const proof = verifyGzipBudget(statSync(path).size, () => readFileSync(path));
    maximumHtmlGzipUpperBound = Math.max(maximumHtmlGzipUpperBound, proof.bytes);
    if (proof.method === "measured-gzip") exactlyMeasuredPages += 1;
    if (index > 0 && index % 1000 === 0) process.stdout.write(`Measured ${index} of ${html.length} HTML pages.\n`);
  }
  assert.equal(walk(join(output, "signals")).filter((path) => basename(path) === "index.html").length, 5000);
  assert.equal(walk(join(output, "lt", "signalai")).filter((path) => basename(path) === "index.html").length, 5000);
  assert.ok(total <= maximumOutputBytes, `5000-record build exceeds ${maximumOutputBytes} bytes: ${total}`);
  assert.ok(maximumHtmlGzipUpperBound <= 512 * 1024, "Growth build exceeds individual HTML budget.");
  process.stdout.write(JSON.stringify({ retainedRecords: 5000, observedHostnames: builtPeriod.records.length,
    observedHostnameParts: builtPeriod.index.partitions.length, bilingualSignalPages: 10000,
    totalBytes: total, maximumBytes: maximumOutputBytes, maximumHtmlGzipUpperBound,
    exactlyMeasuredPages, boundedPages: html.length - exactlyMeasuredPages, fixtureOnly: true }) + "\n");
} finally {
  // Remove the junction itself before recursively removing this owned fixture.
  cleanup();
}
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) await main();
