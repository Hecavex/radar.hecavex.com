// Build-time page assembly: route tables, bootstrap attributes, template decoration and
// the sitemap. Pure functions over already-read data; vite.config.ts owns file I/O.
// React rendering is injected (see src/prerender.ts) so Node's test runner can load this
// module without a TSX loader.
import { brandEntries, brandPath, brandSlug, findBrand } from "./lib/brandRegistry.ts";
import { encodeHistoryBootstrap } from "./lib/historyBootstrap.ts";
import { historyPreview } from "./lib/historyPreview.ts";
import { encodePageBootstrap } from "./lib/pageBootstrap.ts";
import type { PeriodOverviewData } from "./lib/periodMetrics.ts";
import { parseRelatedObservations, type RelatedObservations } from "./lib/relatedObservations.ts";
import type { IdnMatchEvidence } from "./lib/idnEvidence.ts";
import { parseSignalDetail } from "./lib/signalDetail.ts";
import { signalPath } from "./lib/signalRoutes.ts";
import { encodeSnapshotBootstrap } from "./lib/snapshotBootstrap.ts";
import {
  encodeStaticPageBootstrap,
  encodeTrendsPageBootstrap,
  parseEventArtifact,
  type StaticPageData,
  type StaticPageKind,
} from "./lib/staticPageBootstrap.ts";
import type {
  PrerenderPage,
  renderBrandPage,
  renderLithuanianPage,
  renderPrerenderedPage,
  renderSignalPage,
  renderStaticPage,
} from "./prerender.ts";
import type { RadarHistory, RadarSignal, RadarSnapshot } from "./types.ts";

type PageLanguage = "en" | "lt";
type LithuanianPage = "radar" | "brands" | "methodology";
type StaticPageRoute = { kind: StaticPageKind; language: PageLanguage };

export type EntryRoute =
  | { type: "page"; page: PrerenderPage; language: PageLanguage }
  | { type: "static"; kind: StaticPageKind; language: PageLanguage }
  | { type: "lithuanian"; page: LithuanianPage };

export type EntryRenderers = {
  renderPrerenderedPage: typeof renderPrerenderedPage;
  renderStaticPage: typeof renderStaticPage;
  renderLithuanianPage: typeof renderLithuanianPage;
};

/** Raw JSON artifacts the static pages (changes, trends, ...) embed. */
export type StaticPageArtifacts = { events: unknown; trends: unknown; quality: unknown; related: unknown };

export type EntryPageData = {
  snapshot: RadarSnapshot;
  history: RadarHistory;
  periodPreview?: PeriodOverviewData;
  artifacts?: StaticPageArtifacts;
};

export type GeneratedPage = { path: string; html: string };

const SITE = "https://radar.hecavex.com";

export const pages: Record<string, PrerenderPage> = {
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

export const staticPages: Record<string, StaticPageRoute> = {
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

export const lithuanianPages: Record<string, LithuanianPage> = {
  "/lt/index.html": "radar",
  "/lt/": "radar",
  "/lt/prekes-zenklai/index.html": "brands",
  "/lt/prekes-zenklai/": "brands",
  "/lt/metodologija/index.html": "methodology",
  "/lt/metodologija/": "methodology",
};

export const fixedSitemapRoutes: readonly string[] = [
  "/", "/changes/", "/history/", "/lt/istorija/", "/brands/", "/trends/", "/associations/", "/tools/",
  "/dataset/", "/methodology/", "/docs/", "/lt/", "/lt/pokyciai/", "/lt/prekes-zenklai/",
  "/lt/tendencijos/", "/lt/sasajos/", "/lt/irankiai/", "/lt/duomenys/", "/lt/metodologija/",
  "/lt/dokumentacija/",
];

/** The prerendered page Vite is serving or building at `path`, if any. */
export function entryRoute(path: string): EntryRoute | undefined {
  const staticPage = staticPages[path];
  if (staticPage) return { type: "static", ...staticPage };
  const lithuanianPage = lithuanianPages[path];
  if (lithuanianPage) return { type: "lithuanian", page: lithuanianPage };
  const page = pages[path];
  if (page) return { type: "page", page, language: path.startsWith("/lt/") ? "lt" : "en" };
  return undefined;
}

/** Whether the route shows the observed-hostname period overview. */
export function needsPeriodPreview(route: EntryRoute): boolean {
  return route.type !== "static" && (route.page === "radar" || route.page === "history");
}

function staticPageData(snapshot: RadarSnapshot, history: RadarHistory, artifacts: StaticPageArtifacts,
  embeddedHistory: RadarHistory, renderedAt: number): StaticPageData {
  const availableSignalIds = new Set([
    ...snapshot.signals.map((signal) => signal.id),
    ...history.signals.map((signal) => signal.id),
  ]);
  return {
    snapshot,
    history: embeddedHistory,
    historyTotal: history.signals.length,
    events: parseEventArtifact(artifacts.events, availableSignalIds),
    trends: artifacts.trends,
    quality: artifacts.quality,
    related: parseRelatedObservations(artifacts.related),
    renderedAt,
  } as StaticPageData;
}

/** Fill an entry page's `<div id="root"></div>` with its prerendered markup and bootstrap attributes. */
export function renderEntryPage(html: string, path: string, route: EntryRoute, data: EntryPageData,
  renderers: EntryRenderers): string {
  const { snapshot, history, periodPreview } = data;
  const isHistory = route.type === "page" && route.page === "history";
  const renderedAt = Date.parse(isHistory ? history.generatedAt : snapshot.lastSuccessfulSyncAt);
  const embeddedHistory = historyPreview(history);
  // The overview shows only the headline count; the bounded record preview belongs to the history page.
  const periodData = periodPreview && !isHistory ? { ...periodPreview, records: [] } : periodPreview;
  let markup: string;
  let bootstrap = "";
  if (route.type === "static") {
    if (!data.artifacts) throw new Error(`Static page artifacts are required to prerender ${path}`);
    const pageData = staticPageData(snapshot, history, data.artifacts, embeddedHistory, renderedAt);
    markup = renderers.renderStaticPage(route.kind, pageData, route.language);
    const encodedData = route.kind === "trends" ? encodeTrendsPageBootstrap(pageData) : encodeStaticPageBootstrap(pageData);
    bootstrap = ` data-page-kind="${route.kind}" data-page-language="${route.language}" data-page-bootstrap="${encodedData}"`;
  } else if (route.type === "lithuanian") {
    markup = renderers.renderLithuanianPage(route.page, snapshot, renderedAt, periodData);
    if (route.page === "radar") bootstrap = ` data-radar-bootstrap="${encodeSnapshotBootstrap(snapshot, renderedAt, periodData)}"`;
  } else {
    const { page, language } = route;
    markup = renderers.renderPrerenderedPage(page, snapshot, renderedAt, embeddedHistory, language, history.signals.length, periodData);
    if (page === "radar") {
      bootstrap = ` data-radar-bootstrap="${encodeSnapshotBootstrap(snapshot, renderedAt, periodData)}"`;
    } else if (page === "history") {
      bootstrap = ` data-history-bootstrap="${encodeHistoryBootstrap(embeddedHistory, renderedAt, history.signals.length, periodData)}"`;
    } else if (page === "documentation") {
      bootstrap = ` data-page-language="${language}"`;
    }
  }
  const root = '<div id="root"></div>';
  if (!html.includes(root)) throw new Error(`Missing static-render root in ${path}`);
  return html.replace(root, () => `<div id="root"${bootstrap}>${markup}</div>`);
}

function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function replacePageRoot(html: string, markup: string, bootstrap: string): string {
  const root = '<div id="root"></div>';
  if (!html.includes(root)) throw new Error("Missing dynamic page root.");
  return html.replace(root, () => `<div id="root" data-page-bootstrap="${bootstrap}">${markup}</div>`);
}

export function decoratePage(template: string, options: {
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
}): string {
  const english = options.language === "en" ? options.canonical : options.alternate;
  const lithuanian = options.language === "lt" ? options.canonical : options.alternate;
  const values: Record<string, string> = {
    TITLE: escapeHtml(options.title),
    DESCRIPTION: escapeHtml(options.description),
    CANONICAL: options.canonical,
    ALTERNATE: options.alternate,
    ALTERNATE_LANG: options.alternateLanguage,
    ENGLISH: english,
    LITHUANIAN: lithuanian,
    LOCALE: options.language === "lt" ? "lt_LT" : "en_GB",
    ALTERNATE_LOCALE: options.language === "lt" ? "en_GB" : "lt_LT",
    IMAGE_ALT: options.language === "lt" ? "HECAVEX Radar vieši tyrimo signalai" : "HECAVEX Radar public research signals",
    FEED_ROOT: options.feedRoot ?? "",
    FEED_TITLE: escapeHtml(options.feedTitle ?? "HECAVEX Radar brand changes"),
  };
  // One pass, before inserting rendered data: substituted values (a title containing
  // "__CANONICAL__" or "$&") are never expanded again. Unknown placeholders stay as-is.
  const filled = template
    .replace('<html lang="en">', () => `<html lang="${options.language}">`)
    .replace(/__([A-Z]+(?:_[A-Z]+)*)__/g, (placeholder, key: string) => Object.hasOwn(values, key) ? values[key] : placeholder);
  return replacePageRoot(filled, options.markup, options.bootstrap);
}

/** Current signals plus history-only records, keyed by id (snapshot entries win). */
export function publishedSignals(snapshot: RadarSnapshot, history: RadarHistory): Map<string, RadarSignal> {
  const allSignals = new Map(snapshot.signals.map((signal) => [signal.id, signal]));
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
  return allSignals;
}

export type SignalPageInputs = {
  template: string;
  snapshot: RadarSnapshot;
  history: RadarHistory;
  allSignals: ReadonlyMap<string, RadarSignal>;
  related: Pick<RelatedObservations, "nodes" | "edges">;
  idnMatches: readonly IdnMatchEvidence[];
  /** The raw signal-detail JSON for a signal, or undefined when none is published. */
  readDetail: (signal: RadarSignal) => unknown;
  sourceRevision: string;
  dataRevision: string | null;
  manifestSha256: () => string;
};

/** EN and LT signal record pages, in signal-id order. Lazy, so callers write one page at a time. */
export function* signalPages(inputs: SignalPageInputs, render: typeof renderSignalPage): Generator<GeneratedPage> {
  const { template, snapshot, history, related } = inputs;
  const idnById = new Map(inputs.idnMatches.map((record) => [record.signalId, record]));
  const currentIds = new Set(snapshot.signals.map((signal) => signal.id));
  const historicalById = new Map(history.signals.map((signal) => [signal.id, signal]));
  const nodesById = new Map(related.nodes.map((node) => [node.signalId, node]));
  for (const signal of [...inputs.allSignals.values()].sort((left, right) => left.id.localeCompare(right.id))) {
    const rawDetail = inputs.readDetail(signal);
    const detail = rawDetail === undefined ? null : parseSignalDetail(rawDetail, signal);
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
          sourceRevision: inputs.sourceRevision,
          dataRevision: inputs.dataRevision,
          manifestSha256: inputs.manifestSha256(),
          recordScope: currentIds.has(signal.id) ? "snapshot" as const : "history" as const,
        },
        history: historicalById.get(signal.id) ?? null,
        detail,
        idnMatch: idnById.get(signal.id) ?? null,
        brand: signal.brand ? findBrand(signal.brand) ?? null : null,
        relatedNodes: attachedNodes,
        relatedEdges: attachedEdges,
        language,
      };
      const description = language === "lt"
        ? `Išsaugotas galimo apsimetimo signalo įrašas: ${signal.domain}. Įrašas galioja viešos istorijos saugojimo laikotarpiu; tai automatinis tyrimo kandidatas, ne kenkėjiškumo verdiktas.`
        : `Durable potential impersonation signal record for ${signal.domain}. Retained under the public history policy; an automated research candidate, not a maliciousness verdict.`;
      const html = decoratePage(template, {
        title: `${signal.domain} · HECAVEX Radar`,
        description,
        canonical: `${SITE}${path}`,
        alternate: `${SITE}${alternate}`,
        alternateLanguage: language === "en" ? "lt" : "en",
        language,
        markup: render(data),
        bootstrap: encodePageBootstrap(data),
      });
      yield { path, html };
    }
  }
}

/** EN and LT brand activity pages, in registry order. */
export function* brandPages(inputs: { template: string; snapshot: RadarSnapshot; history: RadarHistory },
  render: typeof renderBrandPage): Generator<GeneratedPage> {
  const { template, snapshot, history } = inputs;
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
      const html = decoratePage(template, {
        title: `${brand.brand} activity · HECAVEX Radar`,
        description,
        canonical: `${SITE}${path}`,
        alternate: `${SITE}${alternate}`,
        alternateLanguage: language === "en" ? "lt" : "en",
        language,
        markup: render(data),
        bootstrap: encodePageBootstrap(data),
        feedRoot: `${SITE}${feedRoot}`,
        feedTitle: `${brand.brand} HECAVEX Radar changes`,
      });
      yield { path, html };
    }
  }
}

/** sitemap.xml for the fixed routes plus `generatedPaths`, deduplicated and sorted. */
export function buildSitemap(generatedPaths: Iterable<string>): string {
  const urls = [...new Set([...fixedSitemapRoutes, ...generatedPaths])].sort();
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.map((path) => `  <url><loc>${SITE}${path}</loc></url>`).join("\n")}\n</urlset>\n`;
}
