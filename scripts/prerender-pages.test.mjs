import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { relative } from "node:path";
import test from "node:test";
import { fileURLToPath, URL } from "node:url";
import config from "../vite.config.ts";
import {
  brandPages,
  buildSitemap,
  entryRoute,
  fixedSitemapRoutes,
  lithuanianPages,
  pages,
  publishedSignals,
  renderEntryPage,
  signalPages,
  staticPages,
} from "../src/prerenderPages.ts";

const root = fileURLToPath(new URL("..", import.meta.url));
const entryTemplate = '<!doctype html>\n<html lang="en">\n<body><div id="root"></div></body>\n</html>\n';
const signalTemplate = readFileSync(new URL("../templates/signal/index.html", import.meta.url), "utf8");
const brandTemplate = readFileSync(new URL("../templates/brand/index.html", import.meta.url), "utf8");

// Assembly is under test, not React: renderers return a marker naming their arguments.
const renderers = {
  renderPrerenderedPage: (page, _snapshot, renderedAt, _history, language) => `<main>${page}:${language}:${renderedAt}</main>`,
  renderStaticPage: (kind, _data, language) => `<main>${kind}:${language}</main>`,
  renderLithuanianPage: (page) => `<main>lt-${page}</main>`,
  renderSignalPage: (data) => `<main>signal ${data.signal.id} ${data.language}</main>`,
  renderBrandPage: (data) => `<main>brand ${data.brand.brand} ${data.language}</main>`,
};

const signal = {
  id: "0123456789abcdef0123",
  url: "hxxps://example[.]test",
  domain: "example[.]test",
  firstSeen: "2026-09-01T00:00:00Z",
  lastSeen: "2026-09-02T00:00:00Z",
  sources: ["certstream"],
  status: "active",
  brand: null,
  country: null,
  host: null,
  screenshotUrl: null,
  matchScore: 10,
  evidenceTier: "name-only",
  reasonCodes: [],
};
const historical = {
  id: "fedcba9876543210fedc",
  domain: "older[.]test",
  firstSeen: "2026-08-01T00:00:00Z",
  lastSeen: "2026-08-02T00:00:00Z",
  sources: ["urlscan"],
  latestStatus: "inactive",
  brand: null,
  reasonCodes: ["brand-token"],
};
const snapshot = {
  schemaVersion: 2,
  dataset: "live",
  generatedAt: "2026-09-02T00:00:00Z",
  lastSuccessfulSyncAt: "2026-09-02T01:00:00Z",
  signals: [signal],
  sources: [],
};
const history = { generatedAt: "2026-09-02T02:00:00Z", signals: [historical] };
const pageData = { snapshot, history, periodPreview: undefined, artifacts: undefined };

test("the route tables map every HTML entry in rollupOptions.input and nothing else", () => {
  const entryPaths = Object.entries(config.build.rollupOptions.input)
    .filter(([name]) => !name.endsWith("Template"))
    .map(([, path]) => `/${relative(root, path).replaceAll("\\", "/")}`);
  assert.equal(entryPaths.length, 21);
  for (const path of entryPaths) assert.ok(entryRoute(path), `no prerender route for ${path}`);
  const tableHtmlPaths = [...Object.keys(pages), ...Object.keys(staticPages), ...Object.keys(lithuanianPages)]
    .filter((path) => path.endsWith(".html"));
  assert.deepEqual(tableHtmlPaths.sort(), [...entryPaths].sort());
  // Vite also asks for the directory form of each route during dev serving.
  for (const path of entryPaths.filter((entry) => entry.endsWith("/index.html"))) {
    assert.deepEqual(entryRoute(path.slice(0, -"index.html".length)), entryRoute(path));
  }
  assert.equal(entryRoute("/signals/0123456789abcdef0123/"), undefined);
});

test("the radar page carries the snapshot bootstrap and the LT history page renders in Lithuanian", () => {
  const html = renderEntryPage(entryTemplate, "/", entryRoute("/"), pageData, renderers);
  const renderedAt = Date.parse(snapshot.lastSuccessfulSyncAt);
  const bootstrap = encodeURIComponent(JSON.stringify({ snapshot, renderedAt }));
  assert.ok(html.includes(`<div id="root" data-radar-bootstrap="${bootstrap}"><main>radar:en:${renderedAt}</main></div>`));

  const ltHistory = renderEntryPage(entryTemplate, "/lt/istorija/", entryRoute("/lt/istorija/"), pageData, renderers);
  assert.ok(ltHistory.includes(`<main>history:lt:${Date.parse(history.generatedAt)}</main>`));
  assert.ok(ltHistory.includes('<div id="root" data-history-bootstrap="'));
});

test("a static page carries its kind, language and data bootstrap", () => {
  const artifacts = {
    events: {
      schemaVersion: 1, dataset: "radar-events", generatedAt: "2026-09-02T00:00:00.000Z",
      window: { days: 30, from: "2026-08-03T00:00:00.000Z", to: "2026-09-02T00:00:00.000Z" },
      totalAvailable: 0, truncated: false, events: [],
    },
    trends: { days: [] },
    quality: { metrics: [] },
    related: {
      schemaVersion: 1, dataset: "radar-related-observations", generatedAt: "2026-09-02T00:00:00.000Z",
      semantics: "Shared evidence is a bounded association. It is not attribution.",
      nodes: [], edges: [], suppressedEvidence: { highFanoutValues: 0, temporalPairs: 0, edgeLimit: 0 },
    },
  };
  const route = entryRoute("/lt/pokyciai/index.html");
  assert.deepEqual(route, { type: "static", kind: "changes", language: "lt" });
  const html = renderEntryPage(entryTemplate, "/lt/pokyciai/index.html", route, { ...pageData, artifacts }, renderers);
  const bootstrap = html.match(/data-page-bootstrap="([^"]+)"/u)[1];
  assert.deepEqual(Object.keys(JSON.parse(decodeURIComponent(bootstrap))),
    ["snapshot", "history", "historyTotal", "events", "trends", "quality", "related", "renderedAt"]);
  assert.throws(() => renderEntryPage(entryTemplate, "/lt/pokyciai/", route,
    { ...pageData, artifacts: { ...artifacts, events: {} } }, renderers), /event artifact/u);
  assert.match(html, /<div id="root" data-page-kind="changes" data-page-language="lt" data-page-bootstrap="[^"]+"><main>changes:lt<\/main><\/div>/u);
});

test("entry pages without a root fail closed", () => {
  assert.throws(() => renderEntryPage("<body></body>", "/", entryRoute("/"), pageData, renderers),
    /Missing static-render root in \//u);
});

test("signal pages decorate canonical, alternate and lang for both languages", () => {
  const allSignals = publishedSignals(snapshot, history);
  assert.deepEqual([...allSignals.keys()], [signal.id, historical.id]);
  assert.equal(allSignals.get(historical.id).url, "hxxps://older[.]test");
  const generated = [...signalPages({
    template: signalTemplate,
    snapshot,
    history,
    allSignals,
    related: { nodes: [], edges: [] },
    idnMatches: [],
    readDetail: () => undefined,
    sourceRevision: "a".repeat(40),
    dataRevision: null,
    manifestSha256: () => "b".repeat(64),
  }, renderers.renderSignalPage)];
  assert.deepEqual(generated.map((page) => page.path), [
    `/signals/${signal.id}/`, `/lt/signalai/${signal.id}/`,
    `/signals/${historical.id}/`, `/lt/signalai/${historical.id}/`,
  ]);
  const lt = generated[1].html;
  assert.ok(lt.includes('<html lang="lt">'));
  assert.ok(lt.includes(`<link rel="canonical" href="https://radar.hecavex.com/lt/signalai/${signal.id}/" />`));
  assert.ok(lt.includes(`<link rel="alternate" hreflang="en" href="https://radar.hecavex.com/signals/${signal.id}/" />`));
  assert.ok(lt.includes(`<link rel="alternate" hreflang="lt" href="https://radar.hecavex.com/lt/signalai/${signal.id}/" />`));
  assert.ok(lt.includes('<meta property="og:locale" content="lt_LT" />'));
  assert.ok(lt.includes(`<div id="root" data-page-bootstrap="`));
  assert.ok(lt.includes(`<main>signal ${signal.id} lt</main>`));
  const en = generated[0].html;
  assert.ok(en.includes('<html lang="en">'));
  assert.ok(en.includes(`<link rel="canonical" href="https://radar.hecavex.com/signals/${signal.id}/" />`));
  assert.ok(en.includes("<title>example[.]test · HECAVEX Radar</title>"));
});

test("brand pages are generated in both languages with their feed root", () => {
  const generated = [...brandPages({ template: brandTemplate, snapshot, history }, renderers.renderBrandPage)];
  assert.ok(generated.length >= 2 && generated.length % 2 === 0);
  assert.ok(generated[0].path.startsWith("/brands/"));
  assert.ok(generated[1].path.startsWith("/lt/"));
  assert.ok(generated[0].html.includes("https://radar.hecavex.com/data/brands/"));
});

test("the sitemap lists the fixed routes and generated pages once, sorted", () => {
  const sitemap = buildSitemap([`/signals/${signal.id}/`, "/", `/lt/signalai/${signal.id}/`]);
  const locations = [...sitemap.matchAll(/<loc>https:\/\/radar\.hecavex\.com([^<]+)<\/loc>/gu)].map((match) => match[1]);
  assert.equal(locations.length, fixedSitemapRoutes.length + 2);
  assert.deepEqual(locations, [...locations].sort());
  for (const path of [...fixedSitemapRoutes, `/signals/${signal.id}/`, `/lt/signalai/${signal.id}/`]) {
    assert.ok(locations.includes(path), `sitemap misses ${path}`);
  }
  assert.ok(sitemap.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'));
  assert.ok(sitemap.endsWith("</url>\n</urlset>\n"));
});
