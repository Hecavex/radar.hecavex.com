import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { fileURLToPath, URL } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { parseIdnEvidence } from "../src/lib/idnEvidence.ts";
import { compareToOfficialDomain, domainToUnicode } from "../src/lib/signalComparison.ts";
import { DEFAULT_FILTERS, filterSignals } from "../src/lib/dashboard.ts";
import { checkIocs, normalizeIoc } from "../src/lib/iocCheck.ts";

// Exercise the actual SSR components; Node's type stripping does not support JSX.
registerHooks({
  load(url, context, nextLoad) {
    if (url.startsWith("file:") && url.endsWith(".tsx")) {
      return {
        format: "module", shortCircuit: true,
        source: ts.transpileModule(readFileSync(fileURLToPath(url), "utf8"), {
          compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2023 },
        }).outputText,
      };
    }
    return nextLoad(url, context);
  },
});
const { SignalPage } = await import("../src/SignalPage.tsx");
const { Methodology } = await import("../src/components/Methodology.tsx");
const { Documentation } = await import("../src/components/Documentation.tsx");
const { LtDocumentation } = await import("../src/lt/LtDocumentation.tsx");

const timestamp = "2026-10-15T12:00:00.000Z";
const digest = "a".repeat(64);

function fixture(label = "swedbanƙ") {
  const hostname = new URL(`https://${label}.example`).hostname;
  const signal = {
    id: "a".repeat(20), domain: hostname.replaceAll(".", "[.]"), url: `hxxps://${hostname.replaceAll(".", "[.]")}`,
    brand: "Swedbank", firstSeen: timestamp, lastSeen: timestamp, sources: ["CertStream"],
    status: "suspected", country: null, host: null, screenshotUrl: null,
    reasonCodes: ["brand-domain-match", "punycode"], matchScore: 84,
    evidenceTier: "name-only", reviewState: "unreviewed",
  };
  const record = {
    signalId: signal.id, domain: signal.domain, brand: signal.brand, alias: "swedbank",
    matchedLabel: label, labelIndex: 0, labelRole: "registrable",
    substitutions: [{ position: 7, codePoint: "U+0199", replacement: "k" }],
  };
  return { signal, record, artifact: {
    schemaVersion: 1, dataset: "radar-idn-matches", generatedAt: timestamp,
    snapshotSha256: digest, profile: "radar-idn-visual-v1", records: [record],
  } };
}

test("IDN explanations bind exact current signals and the serialized snapshot release", () => {
  const { signal, artifact } = fixture();
  assert.equal(parseIdnEvidence(artifact, [signal], timestamp, digest), artifact);
  assert.throws(() => parseIdnEvidence(artifact, [signal], "2026-10-15T13:00:00.000Z", digest));
  assert.throws(() => parseIdnEvidence(artifact, [signal], timestamp, "b".repeat(64)));
  assert.throws(() => parseIdnEvidence(artifact, []));
  assert.throws(() => parseIdnEvidence(artifact, [{ ...signal, brand: "Other brand" }]));
  assert.throws(() => parseIdnEvidence(artifact, [{ ...signal, domain: "other[.]example" }]));
  assert.equal(signal.reviewState, "unreviewed");
});

test("unknown top-level, record and substitution keys are rejected; no skeleton can be published", () => {
  for (const modify of [
    (value) => { value.skeleton = "swedbank"; },
    (value) => { value.records[0].skeleton = "swedbank"; },
    (value) => { value.records[0].substitutions[0].skeleton = "swedbank"; },
  ]) {
    const { signal, artifact } = fixture();
    modify(artifact);
    assert.throws(() => parseIdnEvidence(artifact, [signal]));
  }
});

test("only the three reviewed supplemental source characters and replacements are accepted", () => {
  for (const [character, codePoint, replacements] of [["ƙ", "U+0199", ["k"]], ["ө", "U+04E9", ["o", "e"]], ["ӏ", "U+04CF", ["i", "l"]]]) {
    for (const replacement of replacements) {
      const { signal, artifact, record } = fixture(`swedban${character}`);
      record.substitutions[0] = { position: 7, codePoint, replacement };
      assert.equal(parseIdnEvidence(artifact, [signal]).records[0].substitutions[0].replacement, replacement);
    }
  }
  for (const invalid of ["y", "kk", "K", "<k>", "constructor"]) {
    const { signal, artifact } = fixture();
    artifact.records[0].substitutions[0].replacement = invalid;
    assert.throws(() => parseIdnEvidence(artifact, [signal]));
  }
  const { signal, artifact } = fixture("swedbanү");
  artifact.records[0].substitutions[0] = { position: 7, codePoint: "U+04AF", replacement: "y" };
  assert.throws(() => parseIdnEvidence(artifact, [signal]));
});

test("code-point positions, decoded label, ordered unique substitutions and role are checked", () => {
  for (const modify of [
    (record) => { record.labelIndex = 1; },
    (record) => { record.matchedLabel = "other"; },
    (record) => { record.labelRole = "suffix"; },
    (record) => { record.substitutions[0].position = 6; },
    (record) => { record.substitutions[0].position = 8; },
    (record) => { record.substitutions[0].codePoint = "U+04E9"; },
    (record) => { record.substitutions.push(record.substitutions[0]); },
    (record) => { record.substitutions = []; },
  ]) {
    const { signal, artifact, record } = fixture();
    modify(record);
    assert.throws(() => parseIdnEvidence(artifact, [signal]));
  }
});

test("empty artifact is valid; duplicate IDs, record budget and invalid release timestamps fail closed", () => {
  const { signal, artifact } = fixture();
  assert.equal(parseIdnEvidence({ ...artifact, records: [] }, [signal]).records.length, 0);
  assert.throws(() => parseIdnEvidence({ ...artifact, records: [artifact.records[0], artifact.records[0]] }, [signal]));
  assert.throws(() => parseIdnEvidence({ ...artifact, records: Array(2501).fill(artifact.records[0]) }, [signal]));
  for (const generatedAt of ["2026-02-31T12:00:00.000Z", "2026-10-15T12:00:00Z", "2026-10-15T15:00:00.000+03:00"]) {
    assert.throws(() => parseIdnEvidence({ ...artifact, generatedAt }, [signal]));
  }
  const oversized = globalThis.structuredClone(artifact);
  oversized.records[0].matchedLabel = "x".repeat(2 * 1024 * 1024);
  assert.throws(() => parseIdnEvidence(oversized, [signal]), /byte budget/u);
});

test("reference selection and displayed distance use the same Unicode code-point metric", () => {
  const { signal } = fixture();
  const comparison = compareToOfficialDomain(signal.domain, { officialDomains: ["xn--swedban-p3c.example", "swedbank.example"] });
  assert.equal(comparison.officialDomain, "swedbank.example");
  assert.equal(comparison.distance, 1);
  assert.deepEqual(comparison.operations.filter((operation) => operation.kind !== "same"), [{ official: "k", observed: "ƙ", kind: "changed" }]);
  for (const language of ["en", "lt"]) assert.ok(compareToOfficialDomain(signal.domain, { officialDomains: ["swedbank.example"] }, language).observations.length);
});

test("astral Unicode is one edit and cannot split into surrogate operations", () => {
  const hostname = new URL("https://ab𐐨.example").hostname;
  assert.equal(domainToUnicode(hostname), "ab𐐨.example");
  const comparison = compareToOfficialDomain(hostname, { officialDomains: ["abc.example"] });
  assert.equal(comparison.distance, 1);
  assert.deepEqual(comparison.operations.filter((operation) => operation.kind !== "same"), [{ official: "c", observed: "𐐨", kind: "changed" }]);
});

test("A-label and U-label local search find the same published candidate", () => {
  const { signal } = fixture();
  for (const query of ["swedbanƙ", "swedbanƙ[.]example", "swedbanƙ.example", signal.domain, signal.domain.replaceAll("[.]", ".")]) {
    assert.deepEqual(filterSignals([signal], { ...DEFAULT_FILTERS, query }), [signal]);
  }
  assert.deepEqual(filterSignals([signal], { ...DEFAULT_FILTERS, query: "unrelated" }), []);
});

test("IOC exact lookup is unchanged: equivalent IDNA forms merge, visual resemblance remains unknown", () => {
  const { signal } = fixture();
  const indicators = [normalizeIoc("swedbanƙ.example"), normalizeIoc(signal.domain), normalizeIoc("swedbank.example")];
  const results = checkIocs(indicators, [signal], null);
  assert.equal(results[0].normalized, results[1].normalized);
  assert.equal(results[0].matches[0].signalId, signal.id);
  assert.equal(results[1].matches[0].signalId, signal.id);
  assert.deepEqual(results[2].matches, []);
});

for (const language of ["en", "lt"]) {
  test(`${language}: signal SSR shows defanged IDNA forms and only bound current curated evidence`, () => {
    const { signal, record } = fixture();
    const data = {
      language, generatedAt: timestamp, signal, history: null, detail: null, relatedNodes: [], relatedEdges: [],
      brand: { brand: signal.brand, officialDomains: ["swedbank.example"] }, idnMatch: record,
    };
    const markup = renderToStaticMarkup(createElement(SignalPage, { data }));
    assert.ok(markup.includes(signal.domain));
    assert.ok(markup.includes("swedbanƙ[.]example"));
    assert.ok(markup.includes("U+0199"));
    assert.ok(markup.includes(language === "en" ? "Latin script" : "lotynų raštas"));
    assert.ok(markup.includes("radar-idn-visual-v1"));
    assert.ok(markup.includes(language === "en" ? "not an exact UTS #39 match" : "nėra tikslus UTS #39 sutapimas"));
    assert.ok(markup.includes(language === "en" ? "current-release analysis" : "dabartinio leidinio analizė"));
    assert.ok(!markup.includes(`href="https://${signal.domain.replaceAll("[.]", ".")}`));
    assert.ok(!markup.includes("swedbanƙ.example"), "Unicode candidate text remains defanged");
    for (const idnMatch of [undefined, { ...record, signalId: "b".repeat(20) }, { ...record, brand: "Other" }]) {
      const withoutTrace = renderToStaticMarkup(createElement(SignalPage, { data: { ...data, idnMatch } }));
      assert.ok(!withoutTrace.includes("radar-idn-visual-v1"), "Missing or unrelated evidence cannot invent a curated trace");
      assert.ok(withoutTrace.includes(language === "en" ? "not a maliciousness verdict" : "ne kenkėjiškumo verdiktas"));
      assert.ok(withoutTrace.includes(language === "en" ? "Missing evidence is unknown" : "Duomenų nebuvimas nieko nepatvirtina"));
    }
    const exactMarkup = renderToStaticMarkup(createElement(SignalPage, { data: { ...data, idnMatch: null, signal: { ...signal, reasonCodes: ["unicode-confusable"] } } }));
    assert.ok(exactMarkup.includes(language === "en" ? "comparison skeleton matched" : "palyginimo forma sutapo"));
    assert.ok(!exactMarkup.includes("radar-idn-visual-v1"));
    for (const [character, codePoint, replacement] of [["ө", "U+04E9", "e"], ["ӏ", "U+04CF", "l"]]) {
      const cyrillic = fixture(`swedban${character}`);
      cyrillic.record.substitutions[0] = { position: 7, codePoint, replacement };
      const cyrillicMarkup = renderToStaticMarkup(createElement(SignalPage, { data: { ...data, signal: cyrillic.signal, idnMatch: cyrillic.record } }));
      assert.ok(cyrillicMarkup.includes(language === "en" ? "Cyrillic script" : "kirilica"));
    }
  });

  test(`${language}: methodology dates browser research and documentation separates the visual artifact`, () => {
    const methodology = renderToStaticMarkup(createElement(Methodology, { language }));
    assert.ok(methodology.includes("turning-idn-edge-cases-into-typosquats"));
    assert.ok(methodology.includes(language === "en" ? "3 October 2026" : "2026 m. spalio 3 d."));
    assert.ok(methodology.includes(language === "en" ? "do not predict" : "neprognozuoja"));
    const documentation = renderToStaticMarkup(createElement(language === "en" ? Documentation : LtDocumentation));
    assert.ok(documentation.includes("/data/idn-matches-v1.json"));
    assert.ok(documentation.includes("radar-idn-visual-v1"));
    assert.ok(documentation.includes(language === "en" ? "separate from an exact" : "atskirtas nuo tikslaus"));
  });
}
