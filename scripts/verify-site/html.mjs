/* global URL */

// Built HTML: every static route's structure, metadata, links, bootstrap payloads and localized parity.

import { deepStrictEqual } from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { JSDOM } from "jsdom";
import { portfolioNavigationFor, productNavigationForPath, verifySharedTypeAndPalette } from "./identity.mjs";
import {
  analyticsToken,
  assert,
  collectReleasedDocuments,
  output,
  outputPath,
  pages,
  parseFile,
  publicOrigin,
  releaseDocument,
  root,
  routeForFile,
  walk,
} from "./shared.mjs";
import { verifyCrawlerPolicy, verifySitemap } from "./topology.mjs";

function readableTextFromHtml(markup) {
  const fragment = JSDOM.fragment(markup);
  for (const hiddenContent of fragment.querySelectorAll("script, style, template")) {
    hiddenContent.remove();
  }
  return fragment.textContent ?? "";
}

export function verifyBuiltHtml() {
  assert(
    readableTextFromHtml('<span>Signal &amp; details</span>') === "Signal & details" &&
      readableTextFromHtml('<script>not a label</script><style>not a label</style>').trim() === "",
    "HTML text extraction no longer follows parsed, non-executable text semantics.",
  );
  verifyCrawlerPolicy();

  // The reviewed-evidence pack is an intentionally isolated, non-hydrated utility
  // with its own CSP and verifier. It is not a portfolio-shell route.
  const htmlFiles = walk(output).filter(
    (path) => path.endsWith(".html") && !relative(output, path).startsWith(`reporting${sep}`),
  );
  const snapshot = JSON.parse(readFileSync(join(output, "data", "radar.json"), "utf8"));
  const history = JSON.parse(readFileSync(join(output, "data", "history.json"), "utf8"));
  if (history.partitionFormat === "hecavex-history-partitions-v1") {
    history.signals = history.partitions.flatMap((part) => {
      assert(/^history-parts\/[a-f0-9]{64}\.json$/u.test(part.path), "Unsafe history partition path.");
      const bytes = readFileSync(join(output, "data", part.path));
      assert(bytes.length === part.bytes && createHash("sha256").update(bytes).digest("hex") === part.sha256,
        "History partition integrity failure.");
      return JSON.parse(bytes.toString("utf8"));
    });
    assert(history.signals.length === history.signalCount, "History partition completeness failure.");
  }
  const brands = JSON.parse(readFileSync(join(root, "data", "brands-lt.json"), "utf8"));
  const signalIds = new Set([...snapshot.signals, ...history.signals].map((signal) => signal.id));
  const fragmentIdsByPath = new Map();
  const fragmentIdsFor = (path) => {
    const cached = fragmentIdsByPath.get(path);
    if (cached) return cached;
    let targetDocument = parseFile(path);
    const ids = new Set([...targetDocument.querySelectorAll("[id]")].map((element) => element.id));
    releaseDocument(targetDocument);
    targetDocument = null;
    collectReleasedDocuments();
    fragmentIdsByPath.set(path, ids);
    return ids;
  };
  const expectedHtmlCount = 21 + (signalIds.size * 2) + (brands.entries.length * 2);
  assert(htmlFiles.length === expectedHtmlCount, `Expected ${expectedHtmlCount} static HTML entries, found ${htmlFiles.length}.`);
  assert(!htmlFiles.some((path) => relative(output, path).startsWith(`templates${sep}`)), "Build output still exposes route templates.");
  assert(!existsSync(join(output, "signals", "index.html")), "Build output creates a soft-404 landing page at /signals/.");

  const isDynamicRoute = (route) =>
    route.startsWith("/signals/") ||
    route.startsWith("/lt/signalai/") ||
    (route.startsWith("/brands/") && route !== "/brands/") ||
    (route.startsWith("/lt/prekes-zenklai/") && route !== "/lt/prekes-zenklai/");
  const dynamicHtmlFiles = htmlFiles.filter((path) => isDynamicRoute(routeForFile(path)));
  const representativePrefixes = ["/signals/", "/lt/signalai/", "/brands/", "/lt/prekes-zenklai/"];
  const representativeDynamicFiles = representativePrefixes
    .map((prefix) => dynamicHtmlFiles.find((path) => routeForFile(path).startsWith(prefix)))
    .filter(Boolean);
  const representativeDynamicFileSet = new Set(representativeDynamicFiles);
  const fullDomHtmlFiles = htmlFiles.filter(
    (path) => !isDynamicRoute(routeForFile(path)) || representativeDynamicFileSet.has(path),
  );
  const readTagAttribute = (tag, name) =>
    tag?.match(new RegExp(`(?:^|\\s)${name}="([^"]*)"`, "u"))?.[1] ?? null;
  const localizedStaticRoutePairs = [
    ["/", "/lt/"],
    ["/history/", "/lt/istorija/"],
    ["/changes/", "/lt/pokyciai/"],
    ["/brands/", "/lt/prekes-zenklai/"],
    ["/trends/", "/lt/tendencijos/"],
    ["/associations/", "/lt/sasajos/"],
    ["/tools/", "/lt/irankiai/"],
    ["/dataset/", "/lt/duomenys/"],
    ["/methodology/", "/lt/metodologija/"],
    ["/docs/", "/lt/dokumentacija/"],
  ];
  const slugForBrand = (brand) => String(brand)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/gu, "-")
    .replace(/^-+|-+$/gu, "");
  const localizedRoutePairs = [
    ...localizedStaticRoutePairs,
    ...[...signalIds].sort().map((id) => [`/signals/${id}/`, `/lt/signalai/${id}/`]),
    ...brands.entries.map((entry) => {
      const slug = slugForBrand(entry.brand);
      return [`/brands/${slug}/`, `/lt/prekes-zenklai/${slug}/`];
    }),
  ];
  const semanticTags = [
    "main", "section", "nav", "aside", "h2", "dl", "dt", "dd", "table", "form", "input", "select", "textarea", "button",
  ];
  const coreSemanticClasses = new Set([
    "activity-strip", "artifact-hero", "brand-candidates", "brand-history", "brand-hub-grid", "brand-profile-hero",
    "brand-registry", "brand-scope-heading", "brand-scope-metrics", "brand-sources", "collection-disclosure",
    "dataset-explanation", "dataset-summary", "docs-content", "docs-section", "docs-table", "download-grid", "event-section",
    "feed-strip", "methodology-section", "metric-card", "metric-grid", "profile-aside", "profile-hero", "profile-layout",
    "profile-main", "profile-summary", "quality-facets", "quality-grid", "radar-association-explorer",
    "radar-association-summary", "radar-hero", "radar-ioc-checker", "radar-route-grid", "radar-tool",
    "radar-tool-summary", "radar-tool-table", "related-route-card", "scope-boundaries", "signal-section", "trend-boundary",
    "trend-section",
  ]);
  const htmlTagCount = (html, tag) => (html.match(new RegExp(`<${tag}\\b`, "gu")) ?? []).length;
  const semanticSignature = (html, route) => {
    const coreClassCounts = [...html.matchAll(/\sclass="([^"]*)"/gu)]
      .flatMap((match) => match[1].split(/\s+/u).filter((name) => coreSemanticClasses.has(name)));
    const countedCoreClasses = Object.fromEntries(
      [...coreSemanticClasses]
        .map((name) => [name, coreClassCounts.filter((candidate) => candidate === name).length])
        .filter(([, count]) => count > 0),
    );
    const machineLinks = new Set();
    for (const match of html.matchAll(/<a\b([^>]*)>[\s\S]*?<\/a>/gu)) {
      const href = readTagAttribute(`<a${match[1]}>`, "href");
      if (!href) continue;
      const url = new URL(href, new URL(route, publicOrigin));
      if (url.origin === publicOrigin && (url.pathname.startsWith("/data/") || url.pathname.startsWith("/feeds/"))) {
        machineLinks.add(`anchor:${url.pathname}${url.search}${url.hash}`);
      }
    }
    for (const match of html.matchAll(/<link\b[^>]*>/gu)) {
      const tag = match[0];
      if (readTagAttribute(tag, "rel") !== "alternate" || !readTagAttribute(tag, "type")) continue;
      const href = readTagAttribute(tag, "href");
      assert(href, `${route} has a typed machine alternate without an href.`);
      const url = new URL(href, new URL(route, publicOrigin));
      machineLinks.add(`alternate:${readTagAttribute(tag, "type")}:${url.href}`);
    }
    return JSON.stringify({
      coreClassCounts: countedCoreClasses,
      tagCounts: Object.fromEntries(semanticTags.map((tag) => [tag, htmlTagCount(html, tag)])),
      machineLinks: [...machineLinks].sort(),
    });
  };
  const verifyLocalizedParity = () => {
    assert(
      new Set(localizedRoutePairs.flat()).size === localizedRoutePairs.length * 2,
      "Localized parity route pairs contain a duplicate route.",
    );
    for (const [englishRoute, lithuanianRoute] of localizedRoutePairs) {
      const englishPath = outputPath(englishRoute);
      const lithuanianPath = outputPath(lithuanianRoute);
      assert(existsSync(englishPath), `Localized parity is missing ${englishRoute}.`);
      assert(existsSync(lithuanianPath), `Localized parity is missing ${lithuanianRoute}.`);
      const englishHtml = readFileSync(englishPath, "utf8");
      const lithuanianHtml = readFileSync(lithuanianPath, "utf8");
      const editions = [
        [englishRoute, englishHtml, "en"],
        [lithuanianRoute, lithuanianHtml, "lt"],
      ];
      for (const [route, html, language] of editions) {
        const documentElementTag = html.match(/<html\b[^>]*>/u)?.[0];
        const linkTags = [...html.matchAll(/<link\b[^>]*>/gu)].map((match) => match[0]);
        const canonicalTags = linkTags.filter((tag) => readTagAttribute(tag, "rel") === "canonical");
        const languageAlternates = linkTags.filter(
          (tag) => readTagAttribute(tag, "rel") === "alternate" && readTagAttribute(tag, "hreflang"),
        );
        const alternateHref = (hreflang) => readTagAttribute(
          languageAlternates.find((tag) => readTagAttribute(tag, "hreflang") === hreflang),
          "href",
        );
        assert(readTagAttribute(documentElementTag, "lang") === language, `${route} has the wrong localized document language.`);
        assert(
          canonicalTags.length === 1 && readTagAttribute(canonicalTags[0], "href") === `${publicOrigin}${route}`,
          `${route} does not canonicalize its localized route exactly once.`,
        );
        assert(languageAlternates.length === 3, `${route} does not expose exactly three language alternates.`);
        assert(alternateHref("en") === `${publicOrigin}${englishRoute}`, `${route} has the wrong English alternate.`);
        assert(alternateHref("lt") === `${publicOrigin}${lithuanianRoute}`, `${route} has the wrong Lithuanian alternate.`);
        assert(alternateHref("x-default") === `${publicOrigin}${englishRoute}`, `${route} has the wrong x-default alternate.`);
      }
      assert(
        semanticSignature(englishHtml, englishRoute) === semanticSignature(lithuanianHtml, lithuanianRoute),
        `${englishRoute} and ${lithuanianRoute} no longer share core sections, metrics, tools, or machine links.`,
      );
    }
  };

  for (const path of dynamicHtmlFiles) {
    const html = readFileSync(path, "utf8");
    const route = routeForFile(path);
    const lithuanian = route.startsWith("/lt/");
    const ids = [...html.matchAll(/\sid="([^"]+)"/gu)].map((match) => match[1]);
    const linkTags = [...html.matchAll(/<link\b[^>]*>/gu)].map((match) => match[0]);
    const metaTags = [...html.matchAll(/<meta\b[^>]*>/gu)].map((match) => match[0]);
    const canonicalTags = linkTags.filter((tag) => readTagAttribute(tag, "rel") === "canonical");
    const canonicalHref = readTagAttribute(canonicalTags[0], "href");
    const descriptionTag = metaTags.find((tag) => readTagAttribute(tag, "name") === "description");
    const openGraphImageTag = metaTags.find((tag) => readTagAttribute(tag, "property") === "og:image");
    const twitterCardTag = metaTags.find((tag) => readTagAttribute(tag, "name") === "twitter:card");
    const contentSecurityPolicyTag = metaTags.find(
      (tag) => readTagAttribute(tag, "http-equiv") === "Content-Security-Policy",
    );
    const contentSecurityPolicy = readTagAttribute(contentSecurityPolicyTag, "content");
    const documentElementTag = html.match(/<html\b[^>]*>/u)?.[0];
    assert(new Set(ids).size === ids.length, `${route} contains duplicate IDs.`);
    assert(
      readTagAttribute(documentElementTag, "lang") === (lithuanian ? "lt" : "en"),
      `${route} has the wrong document language.`,
    );
    assert((html.match(/<main\b/gu) ?? []).length === 1, `${route} must contain exactly one main element.`);
    assert((html.match(/<h1\b/gu) ?? []).length === 1, `${route} must contain exactly one h1.`);
    assert(html.includes('class="skip-link" href="#main-content"'), `${route} has no usable skip link.`);
    assert(html.includes('data-portfolio-shell="v2"'), `${route} has no shared portfolio shell marker.`);
    assert(
      canonicalTags.length === 1 && canonicalHref === `${publicOrigin}${route}`,
      `${route} has no exact matching canonical URL.`,
    );
    assert(
      linkTags.some((tag) => readTagAttribute(tag, "rel") === "icon" && readTagAttribute(tag, "href") === "/favicon.svg") &&
        linkTags.some((tag) => readTagAttribute(tag, "rel") === "icon" && readTagAttribute(tag, "href") === "/favicon.ico") &&
        linkTags.some((tag) => readTagAttribute(tag, "rel") === "apple-touch-icon" && readTagAttribute(tag, "href") === "/apple-touch-icon.png") &&
        linkTags.some((tag) => readTagAttribute(tag, "rel") === "manifest" && readTagAttribute(tag, "href") === "/site.webmanifest"),
      `${route} has an incomplete shared icon or manifest set.`,
    );
    assert(readTagAttribute(descriptionTag, "content"), `${route} has no description.`);
    assert(readTagAttribute(openGraphImageTag, "content"), `${route} has no Open Graph image.`);
    assert(readTagAttribute(twitterCardTag, "content"), `${route} has no Twitter card.`);

    const jsonLdMatch = html.match(/<script\b[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/u);
    if (jsonLdMatch) {
      const jsonLd = jsonLdMatch[1];
      const jsonLdHash = createHash("sha256").update(jsonLd, "utf8").digest("base64");
      assert(contentSecurityPolicy?.includes(`'sha256-${jsonLdHash}'`), `${route} Content Security Policy does not authorize its exact JSON-LD payload.`);
      JSON.parse(jsonLd);
    }

    const bootstrap = html.match(/data-page-bootstrap="([^"]+)"/u)?.[1];
    assert(bootstrap, `${route} has no permanent page bootstrap.`);
    assert(!/[<>&"]/u.test(bootstrap), `${route} page bootstrap is not safely attribute-encoded.`);
    const payload = JSON.parse(decodeURIComponent(bootstrap));
    const routeKey = route.split("/").filter(Boolean).at(-1);
    if (route.startsWith("/signals/") || route.startsWith("/lt/signalai/")) {
      assert(payload?.signal?.id === routeKey && payload?.generatedAt, `${route} embeds invalid signal data.`);
    } else {
      const brandSlug = slugForBrand(payload?.brand?.brand ?? "");
      assert(brandSlug === routeKey && Array.isArray(payload?.signals), `${route} embeds invalid brand data.`);
    }

    for (const imageTag of html.match(/<img\b[^>]*>/gu) ?? []) {
      assert(readTagAttribute(imageTag, "alt") !== null, `${route} contains an image without an alt attribute.`);
    }

    const anchorMatches = [...html.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/gu)];
    assert(anchorMatches.length === htmlTagCount(html, "a"), `${route} contains an anchor that cannot be inspected.`);
    for (const match of anchorMatches) {
      const openingTag = `<a${match[1]}>`;
      const href = readTagAttribute(openingTag, "href");
      const accessibleLabel =
        readTagAttribute(openingTag, "aria-label") ??
        readableTextFromHtml(match[2])
          .replace(/&(?:#\d+|#x[\da-f]+|[a-z][\w-]*);/giu, "x")
          .replace(/\s+/gu, " ")
          .trim();
      assert(accessibleLabel, `${route} contains an unlabelled link: ${openingTag}`);
      if (!href) continue;
      const url = new URL(href, new URL(route, publicOrigin));
      if (url.origin !== publicOrigin) continue;
      const target = outputPath(url.pathname);
      assert(existsSync(target), `${route} links to missing local target ${url.pathname}.`);
      if (url.hash && target.endsWith(".html")) {
        const fragment = decodeURIComponent(url.hash.slice(1));
        if (url.pathname === route) {
          assert(ids.includes(fragment), `${route} links to missing fragment ${url.hash}.`);
        } else {
          assert(fragmentIdsFor(target).has(fragment), `${route} links to missing fragment ${url.pathname}${url.hash}.`);
        }
      }
    }

    const localAssets = [
      ...[...html.matchAll(/<script\b[^>]*\ssrc="([^"]+)"[^>]*>/gu)].map((match) => match[1]),
      ...linkTags
        .filter((tag) => readTagAttribute(tag, "rel") === "stylesheet")
        .map((tag) => readTagAttribute(tag, "href")),
      ...[...html.matchAll(/<img\b[^>]*\ssrc="([^"]+)"[^>]*>/gu)].map((match) => match[1]),
    ].filter(Boolean);
    for (const raw of localAssets) {
      const url = new URL(raw, new URL(route, publicOrigin));
      if (url.origin === publicOrigin) {
        assert(existsSync(outputPath(url.pathname)), `${route} references missing asset ${url.pathname}.`);
      }
    }
  }

  verifyLocalizedParity();

  for (const path of fullDomHtmlFiles) {
    let document = parseFile(path);
    const route = routeForFile(path);
    const notFound = route === "/404.html";
    const ids = [...document.querySelectorAll("[id]")].map((element) => element.id);
    assert(new Set(ids).size === ids.length, `${route} contains duplicate IDs.`);
    const lithuanian = route.startsWith("/lt/");
    assert(document.documentElement.lang === (lithuanian ? "lt" : "en"), `${route} has the wrong document language.`);
    assert(document.querySelectorAll("main").length === 1, `${route} must contain exactly one main element.`);
    assert(document.querySelectorAll("h1").length === 1, `${route} must contain exactly one h1.`);
    assert(document.querySelector('.skip-link[href="#main-content"]'), `${route} has no usable skip link.`);
    assert(document.querySelector('link[rel="icon"][href="/favicon.svg"]'), `${route} has no shared SVG favicon.`);
    assert(document.querySelector('link[rel="icon"][href="/favicon.ico"]'), `${route} has no ICO fallback favicon.`);
    assert(document.querySelector('link[rel="apple-touch-icon"][href="/apple-touch-icon.png"]'), `${route} has no shared Apple touch icon.`);
    assert(document.querySelector('link[rel="manifest"][href="/site.webmanifest"]'), `${route} has no origin web manifest.`);
    assert(document.querySelector('header.site-header[data-portfolio-shell="v2"]'), `${route} has no shared portfolio shell marker.`);
    const brandLink = document.querySelector(`.brand[href="https://hecavex.com/${lithuanian ? "lt" : "en"}/"]`);
    assert(brandLink, `${route} does not link the HECAVEX brand to the correct Research edition.`);
    const visibleBrandName = brandLink.textContent.replace(/\s+/g, " ").trim();
    const accessibleBrandName = (brandLink.getAttribute("aria-label") ?? visibleBrandName).replace(/\s+/g, " ").trim();
    assert(visibleBrandName && accessibleBrandName.includes(visibleBrandName), `${route} brand link accessible name omits its visible text.`);
    assert(document.querySelector(`.product-identity[href="${lithuanian ? "/lt/" : "/"}"]`), `${route} does not link the Radar identity to its localized overview.`);
    assert(
      document.querySelectorAll(".portfolio-navigation a").length === portfolioNavigationFor(route).length,
      `${route} does not expose the complete portfolio navigation.`,
    );
    assert(document.querySelectorAll(".product-navigation a").length === productNavigationForPath(route).length, `${route} exposes the wrong Radar navigation set.`);
    assert(document.querySelector(".header-utility .source-link"), `${route} has no fixed Source utility.`);
    const analyticsLoaders = [...document.querySelectorAll("script:not([src])")].filter((script) =>
      script.textContent.includes("https://static.cloudflareinsights.com/beacon.min.js"),
    );
    assert(
      analyticsLoaders.length === (analyticsToken ? 1 : 0),
      `${route} does not match the configured Cloudflare Web Analytics state.`,
    );
    if (analyticsToken) {
      assert(
        analyticsLoaders[0].textContent.includes('navigator.doNotTrack==="1"') &&
          analyticsLoaders[0].textContent.includes('window.doNotTrack==="1"') &&
          analyticsLoaders[0].getAttribute("data-hecavex-analytics-token") === analyticsToken,
        `${route} has an unexpected Cloudflare Web Analytics configuration.`,
      );
    }
    const portfolioLabels = [...document.querySelectorAll(".portfolio-navigation a")].map((anchor) => anchor.textContent?.trim());
    const productLabels = [...document.querySelectorAll(".product-navigation a")].map((anchor) => anchor.textContent?.trim());
    assert(JSON.stringify(portfolioLabels) === JSON.stringify(portfolioNavigationFor(route)), `${route} changes the portfolio navigation order.`);
    const expectedProductNavigation = productNavigationForPath(route);
    assert(JSON.stringify(productLabels) === JSON.stringify(expectedProductNavigation), `${route} changes the Radar navigation order.`);
    const expectedLocalPage = new Map([
      ["/", "Overview"],
      ["/lt/", "Apžvalga"],
      ["/history/", "Changes"],
      ["/lt/istorija/", "Pokyčiai"],
      ["/changes/", "Changes"],
      ["/lt/pokyciai/", "Pokyčiai"],
      ["/brands/", "Brands"],
      ["/lt/prekes-zenklai/", "Prekių ženklai"],
      ["/trends/", "Trends"],
      ["/lt/tendencijos/", "Tendencijos"],
      ["/associations/", "Associations"],
      ["/lt/sasajos/", "Sąsajos"],
      ["/tools/", "Tools"],
      ["/lt/irankiai/", "Įrankiai"],
      ["/dataset/", "Dataset"],
      ["/lt/duomenys/", "Duomenys"],
      ["/methodology/", "Methodology"],
      ["/lt/metodologija/", "Metodologija"],
      ["/docs/", "Docs"],
      ["/lt/dokumentacija/", "Dokumentacija"],
    ]).get(route) ?? (
      route.startsWith("/signals/")
        ? "Overview"
        : route.startsWith("/lt/signalai/")
          ? "Apžvalga"
          : route.startsWith("/brands/")
            ? "Brands"
            : route.startsWith("/lt/prekes-zenklai/")
              ? "Prekių ženklai"
              : undefined
    );
    assert(
      document.querySelector('.portfolio-navigation a[aria-current="page"]')?.textContent?.trim() === portfolioNavigationFor(route)[1],
      `${route} does not identify Radar as the active portfolio product.`,
    );
    if (!notFound) assert(document.querySelector('.product-navigation a[aria-current="page"]')?.textContent?.trim() === expectedLocalPage, `${route} does not identify ${expectedLocalPage} as the active Radar page.`);
    assert(document.querySelector('meta[name="description"]')?.content, `${route} has no description.`);
    if (notFound) {
      assert(document.querySelector('meta[name="robots"]')?.content === "noindex, follow", "Custom 404 page must remain noindex, follow.");
      assert(!document.querySelector('link[rel="canonical"]'), "Custom 404 page must not canonicalize missing routes to a valid page.");
      assert(!document.querySelector('.product-navigation a[aria-current="page"]'), "Custom 404 page must not identify a nonexistent local section as current.");
    } else {
      assert(document.querySelector('link[rel="canonical"]')?.href, `${route} has no canonical URL.`);
    }
    assert(document.querySelector('meta[property="og:image"]')?.content, `${route} has no Open Graph image.`);
    if (
      route === "/" ||
      route === "/lt/" ||
      route.startsWith("/signals/") ||
      route.startsWith("/lt/signalai/") ||
      route.startsWith("/brands/") ||
      route.startsWith("/lt/prekes-zenklai/")
    ) {
      assert(document.querySelector('meta[name="twitter:card"]')?.content, `${route} has no Twitter card.`);
    }
    const jsonLd = document.querySelector('script[type="application/ld+json"]')?.textContent;
    if (notFound) assert(!jsonLd, "Custom 404 page must not publish structured data for a nonexistent resource.");
    const contentSecurityPolicy = document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.content;
    let structuredData = null;
    if (jsonLd) {
      const jsonLdHash = createHash("sha256").update(jsonLd, "utf8").digest("base64");
      assert(contentSecurityPolicy?.includes(`'sha256-${jsonLdHash}'`), `${route} Content Security Policy does not authorize its exact JSON-LD payload.`);
      structuredData = JSON.parse(jsonLd);
    }
    if (route === "/") {
      assert(
        document.querySelector('link[rel="alternate"][type="application/stix+json;version=2.1"][href="https://radar.hecavex.com/data/radar.stix.json"]'),
        "Radar overview does not advertise the STIX 2.1 alternate distribution.",
      );
      assert(
        document.querySelector('link[rel="alternate"][type="application/stix+json;version=2.1"][href="https://radar.hecavex.com/data/radar-reviewed.stix.json"]'),
        "Radar overview does not advertise the reviewed STIX 2.1 alternate distribution.",
      );
      assert(structuredData, "Radar overview has no Dataset JSON-LD.");
      const dataset = structuredData["@graph"]?.find((node) => node["@type"] === "Dataset");
      deepStrictEqual(dataset?.creator, {
        "@id": "https://hecavex.com/#organization",
        "@type": "Organization",
        name: "HECAVEX",
        url: "https://hecavex.com/",
      }, "Radar Dataset creator must declare the established typed, named HECAVEX identity locally.");
      const serializedStructuredData = JSON.stringify(structuredData);
      assert(
        serializedStructuredData.includes("application/stix+json;version=2.1") &&
          serializedStructuredData.includes("https://radar.hecavex.com/data/radar.stix.json") &&
          serializedStructuredData.includes("https://radar.hecavex.com/data/radar-reviewed.stix.json") &&
          serializedStructuredData.includes("https://radar.hecavex.com/data/radar.index.json") &&
          serializedStructuredData.includes("https://radar.hecavex.com/data/feed-manifest.json") &&
          serializedStructuredData.includes("checkpointed crt.sh keyword search") &&
          serializedStructuredData.includes("DNS-over-HTTPS and RDAP context"),
        "Radar Dataset metadata omits a declared collection method or machine-readable distribution.",
      );
    }
    if (["/", "/lt/", "/history/", "/lt/istorija/"].includes(route)) {
      const periodMetricsPath = join(output, "data", "period-metrics-v1.json");
      // The overview carries only the headline; the history page owns the complete inventory, search and exports.
      const overview = route === "/" || route === "/lt/";
      const primary = document.querySelector(overview ? ".observed-summary [data-period-count]" : ".period-overview [data-period-count]");
      assert(primary, `${route} omits the recorded-hostname primary metric.`);
      if (existsSync(periodMetricsPath)) {
        const metrics = JSON.parse(readFileSync(periodMetricsPath, "utf8"));
        const defaultPeriod = metrics.windows.find((window) => window.key === "30d");
        assert(primary.getAttribute("data-period-count") === String(defaultPeriod.uniqueHostnames), `${route} uses a preview or shortlist count for the authoritative period headline.`);
        if (!overview) assert(document.querySelector(".period-overview noscript"), `${route} omits authoritative period totals for readers without JavaScript.`);
      } else {
        assert(primary.getAttribute("data-period-count") === "unknown", `${route} turns an unavailable period inventory into zero.`);
      }
      if (overview) {
        const shortlist = document.querySelector(".signal-section");
        const summary = document.querySelector(".observed-summary");
        // 4 = Node.DOCUMENT_POSITION_FOLLOWING: the summary must come after the shortlist.
        assert(shortlist && summary && (shortlist.compareDocumentPosition(summary) & 4), `${route} places the observed-hostname summary before the candidate shortlist.`);
        assert(summary.querySelector(`a[href="${lithuanian ? "/lt/istorija/" : "/history/"}#observed-hostnames"]`), `${route} summary does not link to the complete hostname inventory.`);
        assert(!document.querySelector(".period-overview, .period-table"), `${route} still embeds the complete observed-hostname table.`);
      } else {
        assert([...document.querySelectorAll(".period-overview .export-actions button")].every((button) => button.disabled), `${route} enables complete exports before verifying all hostname parts.`);
      }
    }
    if (route === "/" || route === "/lt/") {
      const signalPrefix = lithuanian ? "/lt/signalai/" : "/signals/";
      const privacyMarker = lithuanian ? "nėra pridedamas prie bendrinamo URL" : "never added to the shared URL";
      assert(document.querySelector(".hero.radar-hero"), `${route} omits the shared Radar hero.`);
      assert(document.querySelector(".activity-strip"), `${route} omits the compact activity strip.`);
      assert(document.querySelector(".filter-shell"), `${route} omits the shared candidate filters.`);
      assert(document.querySelector(".signal-table"), `${route} omits the shared signal table.`);
      assert(document.querySelector(".export-actions"), `${route} omits defanged filtered-view exports.`);
      assert(
        document.querySelector(".filter-privacy-note")?.textContent?.includes(privacyMarker),
        `${route} does not disclose local-only free-text search.`,
      );
      assert(
        document.querySelector(`tbody tr[id^="signal-"] .signal-deep-link[href^="${signalPrefix}"]`),
        `${route} omits localized durable per-signal links.`,
      );
      assert(
        document.querySelector('tbody tr[id^="signal-"] button[aria-haspopup="dialog"]'),
        `${route} omits in-page signal detail controls.`,
      );
      assert(document.querySelector(".radar-route-grid"), `${route} omits dedicated exploration routes.`);
      assert(document.querySelector(".collection-disclosure"), `${route} omits the collection disclosure.`);
    }
    if (route === "/brands/") {
      assert(document.querySelectorAll(".brand-table tbody tr").length >= 40, "Detection scope does not prerender the reviewed brand registry.");
      assert(document.querySelector(".scope-boundaries"), "Detection scope omits registry interpretation boundaries.");
      assert(document.querySelector('.brand-hub-link[href^="/brands/"]'), "Detection scope omits per-brand activity links.");
    }

    const root = document.getElementById("root");
    assert(root, `${route} has no application root.`);
    const bootstrap = root.getAttribute("data-radar-bootstrap");
    const historyBootstrap = root.getAttribute("data-history-bootstrap");
    const staticBootstrap = root.getAttribute("data-page-bootstrap");
    const pageLanguage = root.getAttribute("data-page-language");
    if (route === "/" || route === "/lt/") {
      assert(bootstrap, `${route} has no embedded hydration snapshot.`);
      assert(!/[<>&"]/u.test(bootstrap), `${route} hydration snapshot is not safely attribute-encoded.`);
      const payload = JSON.parse(decodeURIComponent(bootstrap));
      assert(payload?.snapshot?.dataset === "live", `${route} hydration snapshot is not the live public dataset.`);
      assert(Number.isInteger(payload?.renderedAt), `${route} hydration snapshot has no stable render timestamp.`);
      assert(!historyBootstrap, `${route} embeds history data in the live dashboard.`);
    } else if (route === "/history/" || route === "/lt/istorija/") {
      assert(historyBootstrap, `${route} has no embedded history artifact.`);
      assert(!/[<>&"]/u.test(historyBootstrap), `${route} history artifact is not safely attribute-encoded.`);
      const payload = JSON.parse(decodeURIComponent(historyBootstrap));
      assert(payload?.history?.dataset === "history", `${route} does not embed the public history dataset.`);
      assert(Number.isInteger(payload?.renderedAt), `${route} history artifact has no stable render timestamp.`);
      assert(!bootstrap, `${route} embeds the live dashboard snapshot.`);
    } else if ([
      "/changes/", "/lt/pokyciai/", "/trends/", "/associations/", "/tools/", "/dataset/",
      "/lt/tendencijos/", "/lt/sasajos/", "/lt/irankiai/", "/lt/duomenys/",
    ].includes(route)) {
      assert(staticBootstrap, `${route} has no embedded static artifact bootstrap.`);
      assert(pageLanguage === (route.startsWith("/lt/") ? "lt" : "en"), `${route} embeds the wrong static-page language.`);
      const payload = JSON.parse(decodeURIComponent(staticBootstrap));
      if (route === "/trends/" || route === "/lt/tendencijos/") {
        assert(Object.keys(payload).sort().join(",") === "quality,renderedAt,trends", `${route} embeds unrelated candidate or event records.`);
        assert(payload.trends?.dataset === "radar-daily-trends" && payload.quality?.dataset === "radar-quality-metrics", `${route} embeds the wrong trends data.`);
        assert(Number.isInteger(payload.renderedAt), `${route} has no stable trends render timestamp.`);
        assert(statSync(outputPath(route)).size <= 512 * 1024, `${route} exceeds the live publication's 512 KiB raw HTML limit.`);
      } else {
        assert(payload?.snapshot?.dataset === "live" && payload?.history?.dataset === "history", `${route} embeds the wrong static data.`);
      }
      if (route === "/changes/" || route === "/lt/pokyciai/") {
        assert(payload?.events?.dataset === "radar-events" && payload.events.schemaVersion === 1, `${route} does not embed the canonical event v1 record.`);
        assert(document.querySelector(".artifact-hero"), `${route} omits the shared changes hero.`);
        assert(document.querySelectorAll(".feed-strip > a").length === 4, `${route} omits a changes feed link.`);
        assert(document.querySelector(".event-section"), `${route} omits the shared event log.`);
        assert(document.querySelector(".related-route-card"), `${route} omits the retained-history route.`);
        const signalPrefix = route.startsWith("/lt/") ? "/lt/signalai/" : "/signals/";
        for (const event of payload.events.events) {
          assert(signalIds.has(event.signalId), `${route} exposes an event outside the emitted signal-route set.`);
          assert(event.signalPath === `/signals/${event.signalId}/`, `${route} embeds an invalid signal path.`);
        }
        assert(
          Boolean(document.querySelector(`.event-list a[href^="${signalPrefix}"]`)) === (payload.events.events.length > 0),
          `${route} uses the wrong localized signal-route projection.`,
        );
      }
      if (route === "/trends/" || route === "/lt/tendencijos/") {
        assert(payload?.trends?.dataset === "radar-daily-trends", `${route} does not embed the canonical daily trends artifact.`);
        assert(document.querySelector(".trend-method-note"), `${route} omits the schedule and listening explanation.`);
        const cutoff = document.querySelector(".trend-cutoff time");
        assert(cutoff?.getAttribute("datetime") === payload.trends.generatedAt, `${route} omits its precise data cutoff.`);
        assert(cutoff?.textContent?.includes("UTC"), `${route} does not label the cutoff timezone.`);
        const trendRows = [...document.querySelectorAll(".trend-row")];
        assert(trendRows.length === payload.trends.series.length, `${route} does not render every daily trend row.`);
        const isLithuanian = route.startsWith("/lt/");
        for (const [index, row] of trendRows.entries()) {
          const trend = payload.trends.series[index];
          const bars = row.querySelector(".trend-bars");
          const progressBars = [...row.querySelectorAll("progress")];
          assert(bars?.getAttribute("aria-hidden") === "true", `${route} exposes duplicate visual trend bars to assistive technology.`);
          assert(progressBars.length === (trend.discovery === null ? 1 : 2) && progressBars.every((progress) => !progress.textContent), `${route} invents an unknown bar or duplicates trend values inside progress fallback text.`);
          const signalCopy = row.querySelector(".trend-signal-count")?.textContent ?? "";
          const signalLabel = trend.discovery === null
            ? (isLithuanian ? "Aptikimo duomenys neišliko" : "Discovery history unavailable")
            : (isLithuanian ? "Unikalūs signalai" : "unique signals");
          assert(signalCopy.includes(signalLabel), `${route} trend signal value is not self-describing.`);
          const scheduleCopy = row.querySelector(".trend-metrics > span")?.textContent ?? "";
          assert(scheduleCopy.includes(isLithuanian ? "interval" : "scheduled slots"), `${route} trend schedule value is not self-describing.`);
          assert(scheduleCopy.includes("/"), `${route} trend schedule omits its recorded and expected attempt counts.`);
          const listeningLines = [...row.querySelectorAll(".trend-metrics small")];
          assert(listeningLines.length === 2, `${route} must separate actual listening from its planned ceiling.`);
          const listeningCopy = listeningLines.map((line) => line.textContent).join(" ");
          const listeningLabel = trend.collectorCoverage.listeningCoveragePercent === null
            ? (isLithuanian ? "Faktinis klausymosi laikas" : "Wall-clock listening")
            : trend.collectorCoverage.coverageBounds
              ? (isLithuanian ? "Klausymosi aprėpties ribos" : "Wall-clock listening bounds")
              : (isLithuanian ? "Ankstesnis klausymosi įvertis" : "Legacy listening estimate");
          assert(listeningCopy.includes(listeningLabel), `${route} trend row mislabels bounded or legacy listening.`);
          assert(listeningCopy.includes(isLithuanian ? "planinė riba" : "planned ceiling"), `${route} trend row omits the planned listening ceiling.`);
          assert(row.classList.contains("trend-row--partial") === trend.partialDay, `${route} trend row misstates partial UTC-day status.`);
          assert(Boolean(row.querySelector(".trend-date span")) === trend.partialDay, `${route} trend row omits its visible partial UTC-day label.`);
          const renderDate = new Date(payload.renderedAt).toISOString().slice(0, 10);
          const dayState = !trend.partialDay ? "complete" : trend.date === renderDate ? "partial" : "incomplete";
          assert(row.getAttribute("data-day-state") === dayState, `${route} confuses the saved partial day with the current UTC day.`);
          const { recordedAttempts, scheduledSlots } = trend.collectorCoverage;
          const collectionState = scheduledSlots <= 0 ? "unavailable" : recordedAttempts === 0 ? "not-recorded" : recordedAttempts * 2 < scheduledSlots ? "limited" : "recorded";
          assert(row.getAttribute("data-collection-state") === collectionState, `${route} misstates the recorded collection gap.`);
          assert(Boolean(row.querySelector(".trend-collection-note")) === (trend.discovery === null || ["limited", "not-recorded"].includes(collectionState)), `${route} does not label missing history or limited collection beside its signal count.`);
          const additionalAttempts = Math.max(0, trend.collectorCoverage.recordedAttempts - trend.collectorCoverage.scheduledSlots);
          assert(Boolean(row.querySelector(".trend-metrics em")) === (additionalAttempts > 0), `${route} trend row misstates additional collection attempts.`);
          if (trend.collectorCoverage.recordedSchedulePercent === null) {
            assert(scheduleCopy.toLowerCase().includes(isLithuanian ? "nėra duomenų" : "unavailable"), `${route} turns unavailable schedule coverage into a numeric value.`);
          }
          if (trend.collectorCoverage.listeningCoveragePercent === null || trend.collectorCoverage.scheduledListeningCeilingPercent === null) {
            assert(listeningCopy.toLowerCase().includes(isLithuanian ? "nėra duomenų" : "unavailable"), `${route} turns unavailable listening coverage into a numeric value.`);
          }
        }
      }
    } else if (route === "/docs/" || route === "/lt/dokumentacija/") {
      assert(pageLanguage === (route.startsWith("/lt/") ? "lt" : "en"), `${route} embeds the wrong documentation language.`);
    } else if (route.startsWith("/signals/") || route.startsWith("/lt/signalai/")) {
      assert(staticBootstrap, `${route} has no permanent signal bootstrap.`);
      const payload = JSON.parse(decodeURIComponent(staticBootstrap));
      assert(payload?.signal?.id && payload?.generatedAt, `${route} embeds invalid signal data.`);
    } else if ((route.startsWith("/brands/") && route !== "/brands/") || (route.startsWith("/lt/prekes-zenklai/") && route !== "/lt/prekes-zenklai/")) {
      assert(staticBootstrap, `${route} has no brand activity bootstrap.`);
      const payload = JSON.parse(decodeURIComponent(staticBootstrap));
      assert(payload?.brand?.brand && Array.isArray(payload?.signals), `${route} embeds invalid brand data.`);
    } else {
      assert(!bootstrap, `${route} embeds dashboard data outside the dashboard.`);
      assert(!historyBootstrap, `${route} embeds history data outside the history page.`);
    }

    for (const image of document.querySelectorAll("img")) {
      assert(image.hasAttribute("alt"), `${route} contains an image without an alt attribute.`);
    }

    for (const anchor of document.querySelectorAll("a[href]")) {
      const label = (anchor.textContent ?? "").trim() || anchor.getAttribute("aria-label");
      assert(label, `${route} contains an unlabelled link: ${anchor.outerHTML}`);
      const url = new URL(anchor.getAttribute("href"), document.baseURI);
      if (url.origin !== publicOrigin) continue;
      const target = outputPath(url.pathname);
      assert(existsSync(target), `${route} links to missing local target ${url.pathname}.`);
      if (url.hash && target.endsWith(".html")) {
        const fragment = decodeURIComponent(url.hash.slice(1));
        assert(fragmentIdsFor(target).has(fragment), `${route} links to missing fragment ${url.pathname}${url.hash}.`);
      }
    }

    for (const element of document.querySelectorAll('script[src], link[rel="stylesheet"][href], img[src]')) {
      const raw = element.getAttribute("src") ?? element.getAttribute("href");
      const url = new URL(raw, document.baseURI);
      if (url.origin === publicOrigin) {
        assert(existsSync(outputPath(url.pathname)), `${route} references missing asset ${url.pathname}.`);
      }
    }
    releaseDocument(document);
    document = null;
    collectReleasedDocuments();
  }

  let englishChanges = parseFile(outputPath("/changes/"));
  let lithuanianChanges = parseFile(outputPath("/lt/pokyciai/"));
  assert(
    englishChanges.querySelectorAll(".event-list > li").length === lithuanianChanges.querySelectorAll(".event-list > li").length,
    "English and Lithuanian changes pages expose different event counts.",
  );
  assert(
    [...englishChanges.querySelectorAll("main > *")].map((element) => element.className).join("|") ===
      [...lithuanianChanges.querySelectorAll("main > *")].map((element) => element.className).join("|"),
    "English and Lithuanian changes pages no longer share the same section structure.",
  );
  releaseDocument(englishChanges);
  releaseDocument(lithuanianChanges);
  englishChanges = null;
  lithuanianChanges = null;
  collectReleasedDocuments();

  for (const page of pages) {
    const html = readFileSync(outputPath(page.path), "utf8");
    assert(html.includes(page.marker), `${page.path} is missing its meaningful prerendered content.`);
    assert(!html.includes("Enable JavaScript"), `${page.path} still uses an enable-JavaScript placeholder.`);
  }

  verifySitemap(htmlFiles);

  verifySharedTypeAndPalette();
}

export function verifyReportingEvidencePack() {
  const reportingRoot = join(output, "reporting");
  const htmlPath = join(reportingRoot, "index.html");
  const scriptPath = join(reportingRoot, "app.js");
  const stylePath = join(reportingRoot, "styles.css");
  assert(existsSync(htmlPath) && existsSync(scriptPath) && existsSync(stylePath), "Local reporting pack files are missing.");
  const html = readFileSync(htmlPath, "utf8");
  const script = readFileSync(scriptPath, "utf8");
  assert(
    html.includes("connect-src 'none'") &&
      html.includes("form-action 'none'") &&
      html.includes("object-src 'none'") &&
      html.includes('id="pack-form"') &&
      !/<form[^>]+action=/iu.test(html),
    "Local reporting pack no longer enforces its non-sending browser boundary.",
  );
  for (const forbidden of ["fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource"] ) {
    assert(!script.includes(forbidden), `Local reporting pack contains forbidden network primitive ${forbidden}.`);
  }
  assert(
    script.includes('crypto.subtle.digest("SHA-256"') &&
      script.includes("MAX_FILES = 20") &&
      script.includes("MAX_TOTAL_BYTES = 25 * 1024 * 1024") &&
      script.includes("preview.textContent") &&
      !script.includes("innerHTML"),
    "Local reporting pack hashing, size caps, or safe text rendering drifted.",
  );
}
