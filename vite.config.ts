import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import type { StaticPageData } from "./src/lib/staticPageBootstrap.ts";
import { historyPreview } from "./src/lib/historyPreview.ts";

const snapshotPath = fileURLToPath(new URL("./public/data/radar.json", import.meta.url));
const historyPath = fileURLToPath(new URL("./public/data/history.json", import.meta.url));
const eventsPath = fileURLToPath(new URL("./public/data/events.json", import.meta.url));
const trendsPath = fileURLToPath(new URL("./public/data/daily-trends.json", import.meta.url));
const qualityPath = fileURLToPath(new URL("./public/data/quality-metrics.json", import.meta.url));
const relatedPath = fileURLToPath(new URL("./public/data/related-observations.json", import.meta.url));
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
type PrerenderPage = "radar" | "history" | "brands" | "methodology" | "documentation" | "not-found";
type StaticPageKind = "changes" | "trends" | "associations" | "tools" | "dataset";
type PageLanguage = "en" | "lt";
type StaticPageRoute = { kind: StaticPageKind; language: PageLanguage };

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, "utf8"));
}

function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function replacePageRoot(html: string, markup: string, bootstrap: string): string {
  const root = '<div id="root"></div>';
  if (!html.includes(root)) throw new Error("Missing dynamic page root.");
  return html.replace(root, `<div id="root" data-page-bootstrap="${bootstrap}">${markup}</div>`);
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
        const tags: string[] = [];
        if (!html.includes('property="og:image"')) {
          tags.push('<meta property="og:image" content="https://hecavex.com/assets/img/og/hecavex-default-en.png" />');
        }
        if (!html.includes('name="twitter:card"')) {
          tags.push('<meta name="twitter:card" content="summary_large_image" />');
        }
        return tags.length ? html.replace("</head>", `${tags.join("")}\n</head>`) : html;
      },
    },
  };
}

function staticPagePlugin() {
  return {
    name: "hecavex-static-pages",
    transformIndexHtml: {
      order: "pre" as const,
      async handler(html: string, context: { path: string }) {
        const pages: Record<string, PrerenderPage> = {
          "/index.html": "radar",
          "/": "radar",
          "/history/index.html": "history",
          "/history/": "history",
          "/lt/istorija/index.html": "history",
          "/lt/istorija/": "history",
          "/brands/index.html": "brands",
          "/brands/": "brands",
          "/methodology/index.html": "methodology",
          "/methodology/": "methodology",
          "/docs/index.html": "documentation",
          "/docs/": "documentation",
          "/lt/dokumentacija/index.html": "documentation",
          "/lt/dokumentacija/": "documentation",
          "/404.html": "not-found",
        };
        const staticPages: Record<string, StaticPageRoute> = {
          "/changes/index.html": { kind: "changes", language: "en" },
          "/changes/": { kind: "changes", language: "en" },
          "/lt/pokyciai/index.html": { kind: "changes", language: "lt" },
          "/lt/pokyciai/": { kind: "changes", language: "lt" },
          "/trends/index.html": { kind: "trends", language: "en" },
          "/trends/": { kind: "trends", language: "en" },
          "/associations/index.html": { kind: "associations", language: "en" },
          "/associations/": { kind: "associations", language: "en" },
          "/tools/index.html": { kind: "tools", language: "en" },
          "/tools/": { kind: "tools", language: "en" },
          "/dataset/index.html": { kind: "dataset", language: "en" },
          "/dataset/": { kind: "dataset", language: "en" },
          "/lt/tendencijos/index.html": { kind: "trends", language: "lt" },
          "/lt/tendencijos/": { kind: "trends", language: "lt" },
          "/lt/sasajos/index.html": { kind: "associations", language: "lt" },
          "/lt/sasajos/": { kind: "associations", language: "lt" },
          "/lt/irankiai/index.html": { kind: "tools", language: "lt" },
          "/lt/irankiai/": { kind: "tools", language: "lt" },
          "/lt/duomenys/index.html": { kind: "dataset", language: "lt" },
          "/lt/duomenys/": { kind: "dataset", language: "lt" },
        };
        const lithuanianPages: Record<string, "radar" | "brands" | "methodology"> = {
          "/lt/index.html": "radar",
          "/lt/": "radar",
          "/lt/prekes-zenklai/index.html": "brands",
          "/lt/prekes-zenklai/": "brands",
          "/lt/metodologija/index.html": "methodology",
          "/lt/metodologija/": "methodology",
        };
        const page = pages[context.path];
        const staticPage = staticPages[context.path];
        const lithuanianPage = lithuanianPages[context.path];
        const pageLanguage: PageLanguage = context.path.startsWith("/lt/") ? "lt" : "en";
        if (!page && !staticPage && !lithuanianPage) return html;

        const [
          { parseSnapshot },
          { parseHistory },
          { encodeSnapshotBootstrap },
          { encodeHistoryBootstrap },
          { encodeStaticPageBootstrap, parseEventArtifact },
          { parseRelatedObservations },
          { renderLithuanianPage, renderPrerenderedPage, renderStaticPage },
        ] = await Promise.all([
          import("./src/lib/data.ts"),
          import("./src/lib/historyData.ts"),
          import("./src/lib/snapshotBootstrap.ts"),
          import("./src/lib/historyBootstrap.ts"),
          import("./src/lib/staticPageBootstrap.ts"),
          import("./src/lib/relatedObservations.ts"),
          import("./src/prerender.ts"),
        ]);
        const snapshot = parseSnapshot(readJson(snapshotPath));
        const history = await parseHistory(readJson(historyPath), async (path) =>
          new Uint8Array(readFileSync(resolve(dirname(historyPath), path))));
        const renderedAt = Date.parse(page === "history" ? history.generatedAt : snapshot.lastSuccessfulSyncAt);
        const embeddedHistory = historyPreview(history);
        let staticMarkup: string;
        let bootstrap = "";
        if (staticPage) {
          const availableSignalIds = new Set([
            ...snapshot.signals.map((signal) => signal.id),
            ...history.signals.map((signal) => signal.id),
          ]);
          const data = {
            snapshot,
            history: embeddedHistory,
            historyTotal: history.signals.length,
            events: parseEventArtifact(readJson(eventsPath), availableSignalIds),
            trends: readJson(trendsPath),
            quality: readJson(qualityPath),
            related: parseRelatedObservations(readJson(relatedPath)),
            renderedAt,
          } as StaticPageData;
          staticMarkup = renderStaticPage(staticPage.kind, data, staticPage.language);
          bootstrap = ` data-page-kind="${staticPage.kind}" data-page-language="${staticPage.language}" data-page-bootstrap="${encodeStaticPageBootstrap(data)}"`;
        } else if (lithuanianPage) {
          staticMarkup = renderLithuanianPage(lithuanianPage, snapshot, renderedAt);
          bootstrap = lithuanianPage === "radar"
            ? ` data-radar-bootstrap="${encodeSnapshotBootstrap(snapshot, renderedAt)}"`
            : "";
        } else {
          staticMarkup = renderPrerenderedPage(page!, snapshot, renderedAt, embeddedHistory, pageLanguage, history.signals.length);
          bootstrap = page === "radar"
            ? ` data-radar-bootstrap="${encodeSnapshotBootstrap(snapshot, renderedAt)}"`
            : page === "history"
              ? ` data-history-bootstrap="${encodeHistoryBootstrap(embeddedHistory, renderedAt, history.signals.length)}"`
              : page === "documentation"
                ? ` data-page-language="${pageLanguage}"`
              : "";
        }
        const root = '<div id="root"></div>';
        if (!html.includes(root)) throw new Error(`Missing static-render root in ${context.path}`);
        return html.replace(root, `<div id="root"${bootstrap}>${staticMarkup}</div>`);
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
        { parseSignalDetail },
        { parseRelatedObservations },
        { brandEntries, brandPath, brandSlug, findBrand },
        { signalPath },
        { encodePageBootstrap },
        { parseEventArtifact },
        { renderBrandPage, renderSignalPage },
      ] = await Promise.all([
        import("./src/lib/data.ts"),
        import("./src/lib/historyData.ts"),
        import("./src/lib/signalDetail.ts"),
        import("./src/lib/relatedObservations.ts"),
        import("./src/lib/brandRegistry.ts"),
        import("./src/lib/signalRoutes.ts"),
        import("./src/lib/pageBootstrap.ts"),
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
      const currentById = new Map(snapshot.signals.map((signal) => [signal.id, signal]));
      const historicalById = new Map(history.signals.map((signal) => [signal.id, signal]));
      const allSignals = new Map(currentById);
      for (const record of history.signals) {
        if (allSignals.has(record.id)) continue;
        allSignals.set(record.id, {
          id: record.id,
          url: `hxxps://${record.domain}`,
          domain: record.domain,
          firstSeen: record.firstSeen,
          lastSeen: record.lastSeen,
          sources: record.sources,
          status: record.latestStatus,
          brand: record.brand,
          country: null,
          host: null,
          screenshotUrl: null,
          matchScore: 0,
          evidenceTier: "name-only",
          reasonCodes: record.reasonCodes,
        });
      }
      parseEventArtifact(readJson(eventsPath), new Set(allSignals.keys()));
      const nodesById = new Map(related.nodes.map((node) => [node.signalId, node]));
      const sitemapUrls = new Set<string>([
        "/", "/changes/", "/history/", "/lt/istorija/", "/brands/", "/trends/", "/associations/", "/tools/",
        "/dataset/", "/methodology/", "/docs/", "/lt/", "/lt/pokyciai/", "/lt/prekes-zenklai/",
        "/lt/tendencijos/", "/lt/sasajos/", "/lt/irankiai/", "/lt/duomenys/", "/lt/metodologija/",
        "/lt/dokumentacija/",
      ]);

      const decorate = (template: string, options: {
        title: string;
        description: string;
        canonical: string;
        alternate: string;
        alternateLanguage: "en" | "lt";
        language: "en" | "lt";
        markup: string;
        bootstrap: string;
        feedRoot?: string;
        feedTitle?: string;
      }) => {
        const withRoot = replacePageRoot(template, options.markup, options.bootstrap);
        const english = options.language === "en" ? options.canonical : options.alternate;
        const lithuanian = options.language === "lt" ? options.canonical : options.alternate;
        return withRoot
          .replace('<html lang="en">', `<html lang="${options.language}">`)
          .replaceAll("__TITLE__", escapeHtml(options.title))
          .replaceAll("__DESCRIPTION__", escapeHtml(options.description))
          .replaceAll("__CANONICAL__", options.canonical)
          .replaceAll("__ALTERNATE__", options.alternate)
          .replaceAll("__ALTERNATE_LANG__", options.alternateLanguage)
          .replaceAll("__ENGLISH__", english)
          .replaceAll("__LITHUANIAN__", lithuanian)
          .replaceAll("__FEED_ROOT__", options.feedRoot ?? "")
          .replaceAll("__FEED_TITLE__", escapeHtml(options.feedTitle ?? "HECAVEX Radar brand changes"));
      };

      for (const signal of [...allSignals.values()].sort((left, right) => left.id.localeCompare(right.id))) {
        const detailPath = resolve(publicDataPath, "signals", signal.id.slice(0, 2), `${signal.id}.json`);
        const detail = existsSync(detailPath) ? parseSignalDetail(readJson(detailPath), signal) : null;
        const attachedEdges = related.edges.filter((edge) => edge.source === signal.id || edge.target === signal.id);
        const attachedIds = new Set(attachedEdges.flatMap((edge) => [edge.source, edge.target]));
        const attachedNodes = [...attachedIds].map((id) => nodesById.get(id)).filter((node) => node !== undefined);
        for (const language of ["en", "lt"] as const) {
          const path = signalPath(signal, language);
          const alternate = signalPath(signal, language === "en" ? "lt" : "en");
          const data = {
            signal,
            generatedAt: snapshot.generatedAt,
            publicationIdentity: {
              sourceRevision: releaseRevision,
              dataRevision: releaseDataRevision,
              manifestSha256: createHash("sha256").update(readFileSync(resolve(publicDataPath, "feed-manifest.json"))).digest("hex"),
              recordScope: currentById.has(signal.id) ? "snapshot" as const : "history" as const,
            },
            history: historicalById.get(signal.id) ?? null,
            detail,
            brand: signal.brand ? findBrand(signal.brand) ?? null : null,
            relatedNodes: attachedNodes,
            relatedEdges: attachedEdges,
            language,
          };
          const title = `${signal.domain} · HECAVEX Radar`;
          const description = language === "lt"
            ? `Išsaugotas galimo apsimetimo signalo įrašas: ${signal.domain}. Įrašas galioja viešos istorijos saugojimo laikotarpiu; tai automatinis tyrimo kandidatas, ne kenkėjiškumo verdiktas.`
            : `Durable potential impersonation signal record for ${signal.domain}. Retained under the public history policy; an automated research candidate, not a maliciousness verdict.`;
          const html = decorate(signalTemplate, {
            title,
            description,
            canonical: `https://radar.hecavex.com${path}`,
            alternate: `https://radar.hecavex.com${alternate}`,
            alternateLanguage: language === "en" ? "lt" : "en",
            language,
            markup: renderSignalPage(data),
            bootstrap: encodePageBootstrap(data),
          });
          writeGeneratedPage(`${path.slice(1)}index.html`, html);
          sitemapUrls.add(path);
        }
      }

      for (const brand of brandEntries) {
        const currentSignals = snapshot.signals.filter((signal) => signal.brand === brand.brand)
          .sort((left, right) => Date.parse(right.lastSeen) - Date.parse(left.lastSeen));
        const brandHistory = history.signals.filter((signal) => signal.brand === brand.brand)
          .sort((left, right) => Date.parse(right.lastSeen) - Date.parse(left.lastSeen));
        const feedRoot = `/data/brands/${brandSlug(brand.brand)}`;
        for (const language of ["en", "lt"] as const) {
          const path = brandPath(brand.brand, language);
          const alternate = brandPath(brand.brand, language === "en" ? "lt" : "en");
          const data = {
            brand, generatedAt: snapshot.generatedAt, signals: currentSignals,
            history: historyPreview({ ...history, signals: brandHistory }).signals.slice(0, 50),
            historyTotal: brandHistory.length, language,
          };
          const description = language === "lt"
            ? `${brand.brand} vieša HECAVEX Radar aptikimo apimtis, naujausi galimo apsimetimo kandidatai ir pokyčių srautai.`
            : `${brand.brand} public HECAVEX Radar detection scope, recent potential impersonation candidates, and change feeds.`;
          const html = decorate(brandTemplate, {
            title: `${brand.brand} activity · HECAVEX Radar`,
            description,
            canonical: `https://radar.hecavex.com${path}`,
            alternate: `https://radar.hecavex.com${alternate}`,
            alternateLanguage: language === "en" ? "lt" : "en",
            language,
            markup: renderBrandPage(data),
            bootstrap: encodePageBootstrap(data),
            feedRoot: `https://radar.hecavex.com${feedRoot}`,
            feedTitle: `${brand.brand} HECAVEX Radar changes`,
          });
          writeGeneratedPage(`${path.slice(1)}index.html`, html);
          sitemapUrls.add(path);
        }
      }

      const templateDirectory = resolve(outputPath, "templates");
      const templateRelative = relative(resolve(outputPath), templateDirectory);
      if (templateRelative !== "templates" || isAbsolute(templateRelative)) {
        throw new Error("Refusing to remove an unexpected template output directory.");
      }
      rmSync(templateDirectory, { recursive: true, force: false });

      const sitemap = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${[...sitemapUrls].sort().map((path) => `  <url><loc>https://radar.hecavex.com${path}</loc></url>`).join("\n")}\n</urlset>\n`;
      writeGeneratedPage("sitemap.xml", sitemap);
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
