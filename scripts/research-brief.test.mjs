import assert from "node:assert/strict";
import test from "node:test";
import { buildResearchBrief, researchBriefFilename, safeResearchReference } from "../src/lib/researchBrief.ts";

function fixture(language = "en") {
  return {
    language, generatedAt: "2026-09-10T06:37:49.894Z", detail: null, history: null, brand: null,
    relatedNodes: [], relatedEdges: [],
    signal: {
      id: "de431437e4ab848ecdeb", domain: "candidate[.]example", url: "hxxps://candidate[.]example/path",
      firstSeen: "2026-09-10T04:00:00.000Z", lastSeen: "2026-09-10T05:00:00.000Z",
      status: "suspected", sources: ["CertStream"], brand: null, country: null, host: null, screenshotUrl: null,
    },
  };
}

for (const language of ["en", "lt"]) {
  test(`${language}: missing published fields remain unknown without inferred review`, () => {
    const data = fixture(language);
    const brief = buildResearchBrief(data);
    assert.ok(brief.includes(language === "lt" ? "Nepaskelbta / nežinoma" : "Not published / unknown"));
    assert.ok(brief.includes("candidate[.]example"));
    assert.ok(brief.includes(`https://radar.hecavex.com/${language === "lt" ? "lt/signalai" : "signals"}/${data.signal.id}/`));
    assert.ok(!brief.includes("confirmed-suspicious"));
    assert.ok(!brief.includes("certstream-live"), "Sources alone must not infer discovery method");
    assert.ok(brief.includes(language === "lt" ? "KLAUSIMAI — NE IŠVADOS" : "QUESTIONS — NOT FINDINGS"));
    assert.equal(researchBriefFilename(data), `radar-research-${data.signal.id}-${language}.txt`);
  });
}

test("reviewed and unreviewed states are copied only from explicit publication fields", () => {
  for (const reviewState of ["unreviewed", "needs-review", "confirmed-suspicious", "false-positive", "benign-brand-reference", "inconclusive"]) {
    const data = fixture();
    Object.assign(data.signal, { reviewState, discoveredVia: ["certstream-live"], corroboratedBy: ["urlscan-public-report"] });
    const brief = buildResearchBrief(data);
    assert.ok(brief.includes(`Published review state: ${reviewState}`));
    assert.ok(brief.includes("Discovery methods: certstream-live"));
    assert.ok(brief.includes("Corroboration methods: urlscan-public-report"));
    assert.ok(brief.includes("Published evidence tier: Not published / unknown"));
  }
});

test("unsupported fields, malformed dates and Markdown breakout never become findings or live candidate links", () => {
  const data = fixture();
  Object.assign(data.signal, {
    id: "../../evil", url: "candidate\n# confirmed\n[go](https://evil.example)", domain: "<https://evil.example>",
    firstSeen: "2026-02-31T00:00:00.000Z", reviewState: "confirmed\n# injected", discoveredVia: ["invented"],
    referenceUrl: "https://urlscan.io@evil.example/result/",
  });
  const brief = buildResearchBrief(data);
  assert.ok(!brief.includes("evil"));
  assert.ok(!brief.includes("# confirmed"));
  assert.ok(!brief.includes("invented"));
  assert.equal(researchBriefFilename(data), "radar-research-unknown-en.txt");
  const raw = fixture();
  raw.signal.url = "https://candidate.example/[click](https://evil.example)";
  assert.ok(!buildResearchBrief(raw).includes("https://candidate"));
  assert.ok(!buildResearchBrief(raw).includes("]("));
});

test("only bounded exact public URLScan report references are retained", () => {
  const valid = "https://urlscan.io/result/00000000-0000-4000-8000-000000000001/";
  assert.equal(safeResearchReference(valid), valid);
  for (const invalid of [valid + "?next=evil", valid + "#section", valid.replace("urlscan.io", "urlscan.io.evil"), "javascript:alert(1)", "https://candidate.example", "https://urlscan.io/screenshots/test.png"]) {
    assert.equal(safeResearchReference(invalid), null);
  }
});

test("only matching bounded sidecar observations appear, without arbitrary titles or network fields", () => {
  const data = fixture();
  data.detail = { signalId: data.signal.id, observations: [{ source: "URLScan", observedAt: data.generatedAt, page: { title: "DO NOT COPY PRIVATE TITLE" } }] };
  const brief = buildResearchBrief(data);
  assert.ok(brief.includes(`URLScan / ${data.generatedAt}`));
  assert.ok(!brief.includes("PRIVATE TITLE"));
  data.detail.signalId = "other";
  assert.ok(!buildResearchBrief(data).includes(`URLScan / ${data.generatedAt}`));
});

test("large observation lists remain bounded and advertise that bound", () => {
  const data = fixture();
  data.detail = { signalId: data.signal.id, observations: Array.from({ length: 200 }, () => ({ source: "CertStream", observedAt: data.generatedAt })) };
  const brief = buildResearchBrief(data);
  assert.equal(brief.split(`CertStream / ${data.generatedAt}`).length - 1, 20);
  assert.ok(brief.includes("up to 20"));
  assert.ok(brief.length < 8192);
});
