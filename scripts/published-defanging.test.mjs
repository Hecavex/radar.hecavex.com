import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { findFangedStrings } from "./published-defanging.mjs";

const report = "https://urlscan.io/result/01234567-89ab-cdef-0123-456789abcdef/";
const brands = ["Skelbiu.lt", "DPD"];

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
      }],
    },
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
    return findFangedStrings(root, brands);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test("a clean publication with only allowlisted raw fields passes", () => {
  assert.deepEqual(sweep(cleanFixture()), []);
});

const planted = [
  ["free-text sentence-ending host", (files) => { files["signals/01/0123456789abcdef0123.json"].page.title = "Login at login.example.com."; }],
  ["ideographic full stop", (files) => { files["radar.json"].signals[0].domain = "login。example。com"; }],
  ["raw STIX value outside a domain-name object", (files) => { files["radar.stix.json"].objects[1].value = "login.example.com"; }],
  ["third-party URL in an allowlisted field", (files) => { files["radar.json"].sources[0].homepage = "https://login.example.com/"; }],
  ["live URL scheme", (files) => { files["radar.json"].signals[0].url = "https://login[.]example[.]com/"; }],
  ["fanged object key", (files) => { files["radar.json"].byHost = { "login.example.com": 1 }; }],
  ["brand-prefixed host", (files) => { files["radar.json"].signals[0].domain = "Skelbiu.lt.login-example.com"; }],
  ["Atom title", (files) => { files["events.atom.xml"] = files["events.atom.xml"].replace("login[.]example[.]com", "login.example.com"); }],
  ["Atom link to another origin", (files) => { files["events.atom.xml"] = files["events.atom.xml"].replace("https://radar.hecavex.com/signals/", "https://login.example.com/signals/"); }],
  ["XML comment", (files) => { files["brands/skelbiu-lt/events.rss.xml"] = files["brands/skelbiu-lt/events.rss.xml"].replace("<channel>", "<channel><!-- login.example.com -->"); }],
  ["unexpected published file", (files) => { files["extra.json"] = { note: "see пример.рф" }; }],
];

for (const [name, plant] of planted) {
  test(`a planted fanged string fails the sweep: ${name}`, () => {
    const files = cleanFixture();
    plant(files);
    const findings = sweep(files);
    assert.equal(findings.length, 1, findings.join("\n"));
    assert.doesNotMatch(findings[0], /login\.example\.com|https:\/\/login/u, "Findings must stay defanged in CI logs.");
  });
}
