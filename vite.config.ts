import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { completeSocialMetadata } from "./src/lib/socialMetadata.ts";
import { loadPeriodOverview, periodOverviewPreview, type PeriodOverviewData } from "./src/lib/periodMetrics.ts";
import {
  brandPages, buildSitemap, entryRoute, needsPeriodPreview, publishedSignals, renderEntryPage, signalPages, type GeneratedPage,
} from "./src/prerenderPages.ts";

const snapshotPath = fileURLToPath(new URL("./public/data/radar.json", import.meta.url));
const historyPath = fileURLToPath(new URL("./public/data/history.json", import.meta.url));
const eventsPath = fileURLToPath(new URL("./public/data/events.json", import.meta.url));
const trendsPath = fileURLToPath(new URL("./public/data/daily-trends.json", import.meta.url));
const qualityPath = fileURLToPath(new URL("./public/data/quality-metrics.json", import.meta.url));
const relatedPath = fileURLToPath(new URL("./public/data/related-observations.json", import.meta.url));
const idnEvidencePath = fileURLToPath(new URL("./public/data/idn-matches-v1.json", import.meta.url));
const publicDataPath = fileURLToPath(new URL("./public/data", import.meta.url));
const outputPath = fileURLToPath(new URL("./dist", import.meta.url));
const releaseRevision = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
const releaseDataRevision = process.env.RADAR_DATA_REVISION?.trim() || null;
if (releaseDataRevision && !/^[a-f0-9]{40}$/.test(releaseDataRevision)) {
  throw new Error("RADAR_DATA_REVISION must identify one exact selected data commit.");
}
if (process.env.RADAR_SOURCE_REVISION && process.env.RADAR_SOURCE_REVISION !== releaseRevision) {
  throw new Error("The selected source revision differs from the trusted build checkout.");
}
const cloudflareAnalyticsScript = "https://static.cloudflareinsights.com/beacon.min.js";
const cloudflareAnalyticsToken = process.env.HECAVEX_ANALYTICS_TOKEN?.trim() ?? "";
if (cloudflareAnalyticsToken && !/^[a-f\d]{32}$/i.test(cloudflareAnalyticsToken)) {
  throw new Error("HECAVEX_ANALYTICS_TOKEN must be a 32-character hexadecimal Cloudflare site token.");
}
const cloudflareAnalyticsLoader =
  `(()=>{if(navigator.doNotTrack==="1"||window.doNotTrack==="1")return;` +
  `const token=document.currentScript?.dataset.hecavexAnalyticsToken;if(!token)return;` +
  `const beacon=document.createElement("script");beacon.type="module";beacon.src="${cloudflareAnalyticsScript}";` +
  `beacon.dataset.cfBeacon=JSON.stringify({token});document.head.appendChild(beacon)})();`;
function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, "utf8"));
}

function hasExactKeys(value: object, fields: readonly string[]): boolean {
  return Object.keys(value).length === fields.length && fields.every((field) => Object.hasOwn(value, field));
}

function writeGeneratedPage(relativePath: string, html: string): void {
  const target = resolve(outputPath, relativePath);
  const relativeTarget = relative(resolve(outputPath), target);
  if (relativeTarget.startsWith("..") || isAbsolute(relativeTarget)) {
    throw new Error("Refusing to write a generated page outside dist.");
  }
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, html, "utf8");
}

function cloudflareWebAnalyticsPlugin() {
  return {
    name: "hecavex-cloudflare-web-analytics",
    transformIndexHtml() {
      if (!cloudflareAnalyticsToken) return [];
      return [
        {
          tag: "script",
          attrs: { "data-hecavex-analytics-token": cloudflareAnalyticsToken },
          children: cloudflareAnalyticsLoader,
          injectTo: "body" as const,
        },
      ];
    },
  };
}

function portfolioIdentityPlugin() {
  const identityLinks = [
    '<link rel="icon" href="/favicon.svg" type="image/svg+xml" />',
    '<link rel="icon" href="/favicon.ico" sizes="any" />',
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png" />',
    '<link rel="manifest" href="/site.webmanifest" />',
  ].join("\n    ");

  return {
    name: "hecavex-portfolio-identity",
    transformIndexHtml: {
      order: "pre" as const,
      handler(html: string) {
        const withoutLegacyIdentity = html
          .replace(/<link\s+rel=["']icon["'][^>]*>\s*/gi, "")
          .replace(/<link\s+rel=["']apple-touch-icon["'][^>]*>\s*/gi, "")
          .replace(/<link\s+rel=["']manifest["'][^>]*>\s*/gi, "");
        return withoutLegacyIdentity.replace("</head>", `    ${identityLinks}\n  </head>`);
      },
    },
  };
}

function socialMetadataDefaultsPlugin() {
  return {
    name: "hecavex-social-metadata-defaults",
    transformIndexHtml: {
      order: "post" as const,
      handler(html: string) {
        return completeSocialMetadata(html);
      },
    },
  };
}

function staticPagePlugin() {
  let periodOverview: Promise<PeriodOverviewData> | undefined;
  const observedPreview = () => {
    if (!existsSync(resolve(publicDataPath, "period-metrics-v1.json")) && !existsSync(resolve(publicDataPath, "observed-hostnames-v1.json"))) return undefined;
    periodOverview ??= loadPeriodOverview({ readBytes: async (path, maximumBytes) => {
      const target = resolve(publicDataPath, "..", `.${path}`);
      const withinData = relative(publicDataPath, target);
      if (withinData.startsWith("..") || isAbsolute(withinData) || statSync(target).size > maximumBytes) throw new Error("Invalid observation artifact path or byte limit.");
      return new Uint8Array(readFileSync(target));
    } }).then((data) => periodOverviewPreview(data));
    return periodOverview;
  };
  return {
    name: "hecavex-static-pages",
    transformIndexHtml: {
      order: "pre" as const,
      async handler(html: string, context: { path: string }) {
        const route = entryRoute(context.path);
        if (!route) return html;

        const [{ parseSnapshot }, { parseHistory }, renderers] = await Promise.all([
          import("./src/lib/data.ts"),
          import("./src/lib/historyData.ts"),
          import("./src/prerender.ts"),
        ]);
        const snapshot = parseSnapshot(readJson(snapshotPath));
        const history = await parseHistory(readJson(historyPath), async (path) =>
          new Uint8Array(readFileSync(resolve(dirname(historyPath), path))));
        const periodPreview = needsPeriodPreview(route) ? await observedPreview() : undefined;
        const artifacts = route.type === "static"
          ? { events: readJson(eventsPath), trends: readJson(trendsPath), quality: readJson(qualityPath), related: readJson(relatedPath) }
          : undefined;
        return renderEntryPage(html, context.path, route, { snapshot, history, periodPreview, artifacts }, renderers);
      },
    },
  };
}

function dynamicRoutesPlugin() {
  return {
    name: "hecavex-dynamic-static-routes",
    async closeBundle() {
      const signalTemplatePath = resolve(outputPath, "templates", "signal", "index.html");
      const brandTemplatePath = resolve(outputPath, "templates", "brand", "index.html");
      if (!existsSync(signalTemplatePath) || !existsSync(brandTemplatePath)) {
        throw new Error("Dynamic page templates were not emitted by Vite.");
      }
      const signalTemplate = readFileSync(signalTemplatePath, "utf8");
      const brandTemplate = readFileSync(brandTemplatePath, "utf8");
      const [
        { parseSnapshot },
        { parseHistory },
        { parseRelatedObservations },
        { parseIdnEvidence, MAXIMUM_IDN_EVIDENCE_BYTES },
        { parseEventArtifact },
        { renderBrandPage, renderSignalPage },
      ] = await Promise.all([
        import("./src/lib/data.ts"),
        import("./src/lib/historyData.ts"),
        import("./src/lib/relatedObservations.ts"),
        import("./src/lib/idnEvidence.ts"),
        import("./src/lib/staticPageBootstrap.ts"),
        import("./src/prerender.ts"),
      ]);
      const snapshot = parseSnapshot(readJson(snapshotPath));
      const history = await parseHistory(readJson(historyPath), async (path) =>
        new Uint8Array(readFileSync(resolve(dirname(historyPath), path))));
      mkdirSync(resolve(outputPath, ".well-known"), { recursive: true });
      writeFileSync(resolve(outputPath, ".well-known/hecavex-release.json"), JSON.stringify({
        schemaVersion: 1, repository: "Hecavex/radar.hecavex.com", revision: releaseRevision,
        sourceRevision: releaseRevision, dataRevision: releaseDataRevision,
      }) + "\n");
      const related = parseRelatedObservations(readJson(relatedPath));
      // Older coherent publications have no supplemental IDN explanation.
      // When present, bind it to validated complete-set shards and exact snapshot bytes.
      let idnMatches: ReturnType<typeof parseIdnEvidence>["records"] = [];
      if (existsSync(idnEvidencePath)) {
        if (statSync(idnEvidencePath).size > MAXIMUM_IDN_EVIDENCE_BYTES) throw new Error("IDN evidence exceeds its byte budget.");
        const idnBytes = readFileSync(idnEvidencePath);
        if (idnBytes.length > MAXIMUM_IDN_EVIDENCE_BYTES) throw new Error("IDN evidence exceeds its byte budget.");
        const indexPath = resolve(publicDataPath, "radar.index.json");
        if (statSync(indexPath).size > 256 * 1024) throw new Error("IDN evidence signal index exceeds its byte budget.");
        const rawIndex = readJson(indexPath);
        if (typeof rawIndex !== "object" || rawIndex === null || !("shards" in rawIndex) ||
            !hasExactKeys(rawIndex, ["schemaVersion", "dataset", "generatedAt", "signalCount", "dashboardSignalCount", "shards"]) ||
            !("schemaVersion" in rawIndex) || rawIndex.schemaVersion !== 1 ||
            !("dataset" in rawIndex) || rawIndex.dataset !== "radar-signal-index" ||
            !("signalCount" in rawIndex) || typeof rawIndex.signalCount !== "number" ||
            !Number.isInteger(rawIndex.signalCount) || rawIndex.signalCount < 0 || rawIndex.signalCount > 25000 ||
            !("dashboardSignalCount" in rawIndex) || rawIndex.dashboardSignalCount !== snapshot.signals.length ||
            !("generatedAt" in rawIndex) || rawIndex.generatedAt !== snapshot.lastSuccessfulSyncAt ||
            !Array.isArray(rawIndex.shards) || rawIndex.shards.length > 1000) {
          throw new Error("IDN evidence requires a coherent bounded signal index.");
        }
        const completeSignals: typeof snapshot.signals = [];
        for (const [index, row] of rawIndex.shards.entries()) {
          const expectedPath = `/data/radar-shards/${String(index + 1).padStart(4, "0")}.json`;
          if (typeof row !== "object" || row === null ||
              !hasExactKeys(row, ["number", "path", "signals", "bytes", "sha256", "firstSignalId", "lastSignalId"]) ||
              row.path !== expectedPath || row.number !== index + 1 ||
              !Number.isInteger(row.bytes) || row.bytes < 1 || row.bytes > 256 * 1024 ||
              !Number.isInteger(row.signals) || row.signals < 1 || row.signals > 25000 ||
              typeof row.sha256 !== "string" || !/^[a-f\d]{64}$/u.test(row.sha256)) {
            throw new Error("IDN evidence signal index contains an invalid shard path.");
          }
          const shardPath = resolve(publicDataPath, "radar-shards", `${String(index + 1).padStart(4, "0")}.json`);
          if (statSync(shardPath).size > 256 * 1024) throw new Error("IDN evidence signal shard exceeds its byte budget.");
          const bytes = readFileSync(shardPath);
          if (bytes.length > 256 * 1024 || bytes.length !== row.bytes ||
              createHash("sha256").update(bytes).digest("hex") !== row.sha256) {
            throw new Error("IDN evidence signal shard fails its byte or digest boundary.");
          }
          const shard = JSON.parse(bytes.toString("utf8")) as Record<string, unknown>;
          if (typeof shard !== "object" || shard === null ||
              !hasExactKeys(shard, ["schemaVersion", "dataset", "generatedAt", "shard", "signals"]) ||
              shard.schemaVersion !== 1 || shard.dataset !== "radar-signal-shard" ||
              shard.generatedAt !== rawIndex.generatedAt || shard.shard !== index + 1) {
            throw new Error("IDN evidence signal shard has an invalid release boundary.");
          }
          const parsed = parseSnapshot({ ...snapshot, signals: shard.signals }).signals;
          if (parsed.length !== row.signals || parsed[0]?.id !== row.firstSignalId ||
              parsed.at(-1)?.id !== row.lastSignalId) throw new Error("IDN evidence shard counts do not reconcile.");
          completeSignals.push(...parsed);
          if (completeSignals.length > rawIndex.signalCount) throw new Error("IDN evidence shards exceed their declared complete-set count.");
        }
        if (!("signalCount" in rawIndex) || completeSignals.length !== rawIndex.signalCount ||
            new Set(completeSignals.map((signal) => signal.id)).size !== completeSignals.length ||
            snapshot.signals.some((signal, index) => completeSignals[index]?.id !== signal.id)) {
          throw new Error("IDN evidence complete-set identity or ordering is invalid.");
        }
        idnMatches = parseIdnEvidence(
          JSON.parse(idnBytes.toString("utf8")), completeSignals, snapshot.lastSuccessfulSyncAt,
          createHash("sha256").update(readFileSync(snapshotPath)).digest("hex"),
        ).records;
      }
      const allSignals = publishedSignals(snapshot, history);
      parseEventArtifact(readJson(eventsPath), new Set(allSignals.keys()));
      const generatedPages: { path: string; indexable?: boolean; lastmod?: string }[] = [];
      const writePages = (generated: Iterable<GeneratedPage>) => {
        for (const page of generated) {
          writeGeneratedPage(`${page.path.slice(1)}index.html`, page.html);
          generatedPages.push({ path: page.path, indexable: page.indexable, lastmod: page.lastmod });
        }
      };
      let manifestSha256: string | undefined;
      writePages(signalPages({
        template: signalTemplate, snapshot, history, allSignals, related, idnMatches,
        readDetail: (signal) => {
          const detailPath = resolve(publicDataPath, "signals", signal.id.slice(0, 2), `${signal.id}.json`);
          return existsSync(detailPath) ? readJson(detailPath) : undefined;
        },
        sourceRevision: releaseRevision,
        dataRevision: releaseDataRevision,
        manifestSha256: () => manifestSha256 ??=
          createHash("sha256").update(readFileSync(resolve(publicDataPath, "feed-manifest.json"))).digest("hex"),
      }, renderSignalPage));
      writePages(brandPages({ template: brandTemplate, snapshot, history }, renderBrandPage));

      const templateDirectory = resolve(outputPath, "templates");
      const templateRelative = relative(resolve(outputPath), templateDirectory);
      if (templateRelative !== "templates" || isAbsolute(templateRelative)) {
        throw new Error("Refusing to remove an unexpected template output directory.");
      }
      rmSync(templateDirectory, { recursive: true, force: false });

      writeGeneratedPage("sitemap.xml", buildSitemap(generatedPages, snapshot.generatedAt));
      writeGeneratedPage(".well-known/security.txt", readFileSync(resolve("public", ".well-known", "security.txt"), "utf8"));
    },
  };
}

export default defineConfig({
  plugins: [portfolioIdentityPlugin(), staticPagePlugin(), socialMetadataDefaultsPlugin(), cloudflareWebAnalyticsPlugin(), react(), dynamicRoutesPlugin()],
  build: {
    rollupOptions: {
      input: {
        radar: fileURLToPath(new URL("./index.html", import.meta.url)),
        history: fileURLToPath(new URL("./history/index.html", import.meta.url)),
        ltHistory: fileURLToPath(new URL("./lt/istorija/index.html", import.meta.url)),
        brands: fileURLToPath(new URL("./brands/index.html", import.meta.url)),
        methodology: fileURLToPath(new URL("./methodology/index.html", import.meta.url)),
        documentation: fileURLToPath(new URL("./docs/index.html", import.meta.url)),
        notFound: fileURLToPath(new URL("./404.html", import.meta.url)),
        changes: fileURLToPath(new URL("./changes/index.html", import.meta.url)),
        trends: fileURLToPath(new URL("./trends/index.html", import.meta.url)),
        associations: fileURLToPath(new URL("./associations/index.html", import.meta.url)),
        tools: fileURLToPath(new URL("./tools/index.html", import.meta.url)),
        dataset: fileURLToPath(new URL("./dataset/index.html", import.meta.url)),
        ltRadar: fileURLToPath(new URL("./lt/index.html", import.meta.url)),
        ltChanges: fileURLToPath(new URL("./lt/pokyciai/index.html", import.meta.url)),
        ltBrands: fileURLToPath(new URL("./lt/prekes-zenklai/index.html", import.meta.url)),
        ltMethodology: fileURLToPath(new URL("./lt/metodologija/index.html", import.meta.url)),
        ltTrends: fileURLToPath(new URL("./lt/tendencijos/index.html", import.meta.url)),
        ltAssociations: fileURLToPath(new URL("./lt/sasajos/index.html", import.meta.url)),
        ltTools: fileURLToPath(new URL("./lt/irankiai/index.html", import.meta.url)),
        ltDataset: fileURLToPath(new URL("./lt/duomenys/index.html", import.meta.url)),
        ltDocumentation: fileURLToPath(new URL("./lt/dokumentacija/index.html", import.meta.url)),
        signalTemplate: fileURLToPath(new URL("./templates/signal/index.html", import.meta.url)),
        brandTemplate: fileURLToPath(new URL("./templates/brand/index.html", import.meta.url)),
      },
    },
  },
});
