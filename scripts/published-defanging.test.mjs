import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { performance } from "node:perf_hooks";
import test from "node:test";
import { URL } from "node:url";
import { containsFangedHost, findFangedStrings } from "./published-defanging.mjs";

const report = "https://urlscan.io/result/01234567-89ab-cdef-0123-456789abcdef/";
const options = { brandNames: ["Skelbiu.lt", "DPD"], officialDomains: ["skelbiu.lt", "dpd.lt"] };
const parity = JSON.parse(readFileSync(new URL("../tests/fixtures/defang-parity.json", import.meta.url), "utf8"));

function cleanFixture() {
  return {
    "radar.json": {
      sources: [{ name: "URLScan", homepage: "https://urlscan.io/" }],
      signals: [{
        brand: "Skelbiu.lt",
        domain: "login[.]example[.]com",
        url: "hxxps://login[.]example[.]com/index[.]php",
        referenceUrl: report,
        screenshotUrl: "https://urlscan.io/screenshots/01234567-89ab-cdef-0123-456789abcdef.png",
        note: "A Skelbiu.lt and DPD candidate",
      }],
    },
    "radar.json.sha256": `${"0".repeat(64)}  radar.json\n`,
    "signals/01/0123456789abcdef0123.json": {
      page: { title: "Prisijunkite prie login[.]example[.]com." },
      contextChanges: [{ source: { referenceUrl: "https://cloudflare-dns.com/dns-query" } }],
    },
    "radar.stix.json": {
      objects: [
        { type: "domain-name", value: "login.example.com" },
        { type: "observed-data", external_references: [{ source_name: "URLScan", url: report }] },
      ],
    },
    "misp-warninglists/hecavex-official-domains/list.json": { list: ["skelbiu.lt"] },
    "history.json": { partitions: [{ path: `history-parts/${"a".repeat(64)}.json` }] },
    "brand-feeds.json": { brands: [{ brand: "Skelbiu.lt", atom: "/data/brands/skelbiu-lt/events.atom.xml" }] },
    "schemas/radar-v2.schema.json": {
      $schema: "https://json-schema.org/draft/2020-12/schema",
      $id: "https://radar.hecavex.com/data/schemas/radar-v2.schema.json",
      properties: { referenceUrl: { type: ["string", "null"], pattern: "^https://urlscan\\.io/result/" } },
    },
    "events.atom.xml": '<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">' +
      '<link rel="self" href="https://radar.hecavex.com/data/events.atom.xml" />' +
      '<entry><title>First publication: login[.]example[.]com</title>' +
      '<link href="https://radar.hecavex.com/signals/0123456789abcdef0123/" /></entry></feed>',
    "brands/skelbiu-lt/events.rss.xml": '<rss version="2.0"><channel><title>Skelbiu[.]lt</title>' +
      "<link>https://radar.hecavex.com/brands/skelbiu-lt/</link></channel></rss>",
  };
}

function sweep(files) {
  const root = mkdtempSync(join(tmpdir(), "radar-defang-"));
  try {
    for (const [path, content] of Object.entries(files)) {
      mkdirSync(dirname(join(root, path)), { recursive: true });
      writeFileSync(join(root, path), typeof content === "string" ? content : JSON.stringify(content));
    }
    return findFangedStrings(root, options);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test("a clean publication with only allowlisted raw fields passes", () => {
  assert.deepEqual(sweep(cleanFixture()), []);
});

const atom = (files, from, to) => { files["events.atom.xml"] = files["events.atom.xml"].replace(from, to); };
const planted = [
  ["free-text sentence-ending host", (files) => { files["signals/01/0123456789abcdef0123.json"].page.title = "Login at login.example.com."; }],
  ["ideographic full stop", (files) => { files["radar.json"].signals[0].domain = "login\u3002example\u3002com"; }],
  ["host around a brand name", (files) => { files["radar.json"].signals[0].note = "see evi.Skelbiu.lt.com"; }],
  ["brand name as a host label", (files) => { files["radar.json"].signals[0].note = "DPD.cam"; }],
  ["brand name inside a host", (files) => { files["radar.json"].signals[0].note = "x.DPD.cam"; }],
  ["brand-prefixed host", (files) => { files["radar.json"].signals[0].domain = "Skelbiu.lt.login-example.com"; }],
  ["raw STIX value outside a domain-name object", (files) => { files["radar.stix.json"].objects[1].value = "login.example.com"; }],
  ["STIX domain-name value that is a URL", (files) => { files["radar.stix.json"].objects[0].value = "login.example.com/path"; }],
  ["warninglist entry outside the registry", (files) => { files["misp-warninglists/hecavex-official-domains/list.json"].list.push("login.example.com"); }],
  ["third-party URL in an allowlisted field", (files) => { files["radar.json"].sources[0].homepage = "https://login.example.com/"; }],
  ["own-origin URL carrying a host segment", (files) => { files["brand-feeds.json"].brands[0].atom = "/data/login.example.com/events.atom.xml"; }],
  ["schema pattern outside a string schema", (files) => { files["schemas/radar-v2.schema.json"].properties.note = { pattern: "login.example.com" }; }],
  ["live URL scheme", (files) => { files["radar.json"].signals[0].url = "https://login[.]example[.]com/"; }],
  ["fanged object key", (files) => { files["radar.json"].byHost = { "login.example.com": 1 }; }],
  ["Atom title", (files) => atom(files, "login[.]example[.]com", "login.example.com")],
  ["Atom link to another origin", (files) => atom(files, "https://radar.hecavex.com/signals/", "https://login.example.com/signals/")],
  ["Atom link with a host-like path", (files) => atom(files, "/signals/0123456789abcdef0123/", "/x/login.example.com/")],
  ["XML DOCTYPE", (files) => atom(files, "<feed ", '<!DOCTYPE feed SYSTEM "feed.dtd"><feed ')],
  ["XML element name", (files) => atom(files, "<title>", '<x:login.example.com xmlns:x="urn:x" /><title>')],
  ["XML comment", (files) => { files["brands/skelbiu-lt/events.rss.xml"] = files["brands/skelbiu-lt/events.rss.xml"].replace("<channel>", "<channel><!-- login.example.com -->"); }],
  ["unexpected JSON file", (files) => { files["extra.json"] = { note: "see \u043f\u0440\u0438\u043c\u0435\u0440.\u0440\u0444" }; }],
  ["NDJSON file the sweep does not parse", (files) => { files["extra.ndjson"] = '{"note":"login[.]example[.]com"}\n'; }],
  ["text file", (files) => { files["notes.txt"] = "nothing fanged"; }],
  ["checksum sidecar with extra text", (files) => { files["radar.json.sha256"] = `${"0".repeat(64)}  radar.json login.example.com\n`; }],
];

for (const [name, plant] of planted) {
  test(`a planted value fails the sweep: ${name}`, () => {
    const files = cleanFixture();
    plant(files);
    const findings = sweep(files);
    assert.equal(findings.length, 1, findings.join("\n"));
    assert.doesNotMatch(findings[0], /login\.example\.com|https:\/\/login/u, "Findings must stay defanged in CI logs.");
  });
}

test("the JS host pattern agrees with the Python defanger on the shared parity cases", () => {
  for (const [fanged, defanged] of parity.defanged) {
    assert.ok(containsFangedHost(fanged), `missed ${fanged}`);
    assert.ok(!containsFangedHost(defanged), `flagged defanged ${defanged}`);
  }
  for (const text of parity.unchanged) assert.ok(!containsFangedHost(text), `flagged ${text}`);
});

test("adversarial input is matched in linear time", () => {
  for (const text of ["1.".repeat(5000), "a.".repeat(5000), "a-".repeat(5000), `${"a".repeat(62)}.`.repeat(160) + "1"]) {
    const started = performance.now();
    containsFangedHost(text);
    assert.ok(performance.now() - started < 1000, `slow on ${text.slice(0, 8)}...`);
  }
});
