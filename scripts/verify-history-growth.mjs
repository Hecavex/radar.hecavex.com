// Opt-in full production build with synthetic history in an isolated temporary
// tree. It never modifies source data, contacts indicators or deploys a site.
import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import process from "node:process";
import { createHash } from "node:crypto";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, relative, resolve, sep } from "node:path";
import { build } from "vite";
import { parseHistory } from "../src/lib/historyData.ts";
import { maximumOutputBytes } from "./deployment-capacity.mjs";
import { verifyGzipBudget } from "./gzip-budget.mjs";

const root = resolve(import.meta.dirname, "..");
const measureExisting = process.argv[2] === "--measure-existing";
const fixtureRoot = measureExisting ? resolve(process.argv[3]) : mkdtempSync(join(tmpdir(), "radar-history-growth-"));
assert.equal(resolve(fixtureRoot).startsWith(resolve(tmpdir()) + sep + "radar-history-growth-"), true);
const excluded = new Set([".git", "node_modules", "dist", ".venv", ".radar-local", ".hypothesis", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"]);
const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
const walk = (path) => readdirSync(path, { withFileTypes: true }).flatMap((entry) => entry.isDirectory() ? walk(join(path, entry.name)) : [join(path, entry.name)]);
function cleanup() {
  assert.equal(resolve(fixtureRoot).startsWith(resolve(tmpdir()) + sep + "radar-history-growth-"), true);
  try { unlinkSync(join(fixtureRoot, "node_modules")); } catch (error) { if (error.code !== "ENOENT") throw error; }
  rmSync(fixtureRoot, { recursive: true, force: true });
}
try {
  if (!measureExisting) {
  process.stdout.write("Preparing an isolated 5000-record history build fixture.\n");
  cpSync(root, fixtureRoot, { recursive: true, filter: (path) => !relative(root, path).split(sep).some((part) => excluded.has(part)) });
  symlinkSync(join(root, "node_modules"), join(fixtureRoot, "node_modules"), "junction");
  const publicData = join(fixtureRoot, "public", "data");
  const original = JSON.parse(readFileSync(join(publicData, "history.json"), "utf8"));
  const history = await parseHistory(original, async (path) => new Uint8Array(readFileSync(join(publicData, path))));
  const seed = history.signals[0];
  assert.ok(seed, "Growth build requires one valid source-history contract fixture.");
  for (let count = history.signals.length; count < 5000; count += 1) {
    const domain = `growth-fixture-${count}[.]example`;
    history.signals.push({ ...seed, domain, id: digest(domain).slice(0, 20), statusTransitions: seed.statusTransitions.slice(0, 1) });
  }
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
  process.stdout.write(JSON.stringify({ retainedRecords: 5000, bilingualSignalPages: 10000,
    totalBytes: total, maximumBytes: maximumOutputBytes, maximumHtmlGzipUpperBound,
    exactlyMeasuredPages, boundedPages: html.length - exactlyMeasuredPages, fixtureOnly: true }) + "\n");
} finally {
  // Remove the junction itself before recursively removing this owned fixture.
  cleanup();
}
