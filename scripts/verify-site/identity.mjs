// Portfolio identity: shared navigation labels, layout tokens, fonts, palette and icon assets.

import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";

import navigation from "../../src/lib/navigation.json" with { type: "json" };
import { assert, output, root, walk } from "./shared.mjs";

// Canonical portfolio identity outputs. These fingerprints keep binary fallbacks
// aligned with the reviewed graphite/mineral-teal SVG instead of allowing an old
// cached favicon set to return unnoticed.
const identityAssetDigests = new Map([
  ["favicon.ico", "833ad6e58527cee2b60cced56349822615735f5133be19a8e4502c53b533082a"],
  ["apple-touch-icon.png", "7494c7531ce9e205350cf4130b5f8e0103e1f10f74257d3437220c8a9e16da89"],
  ["icon-192.png", "1d1bf844cd5705bd02248ea31853c06ca0279cf0c99db5a759169f34badacd47"],
  ["icon-512.png", "fc6f38b8599104ba47aa86ddd12a295d9f2252f912ab1ed99057241632f9d47c"],
]);

const languageOf = (path) => (path.startsWith("/lt/") ? "lt" : "en");
export const portfolioNavigationFor = (path) => navigation.portfolio[languageOf(path)].map((item) => item.label);
const sourceLabelFor = (path) => navigation.sourceLabel[languageOf(path)];

export function productNavigationForPath(path) {
  return navigation.product[languageOf(path)].map((item) => item.label);
}

export function mobileNavigationForPath(path) {
  return [
    ...productNavigationForPath(path),
    path.startsWith("/lt/") ? "English" : "Lietuviškai",
    sourceLabelFor(path),
    ...portfolioNavigationFor(path),
  ];
}

function readStylesheetSource(file, ancestors = new Set()) {
  const resolved = resolve(file);
  assert(!ancestors.has(resolved), `Cyclic stylesheet import: ${relative(root, resolved)}`);
  const next = new Set([...ancestors, resolved]);
  return readFileSync(resolved, "utf8").replace(/^@import "([^"]+)";$/gm,
    (_, imported) => readStylesheetSource(resolve(dirname(resolved), imported), next));
}

export function verifyLayoutSourceContract() {
  const stylesheet = readStylesheetSource(join(root, "src", "styles.css"));
  for (const declaration of [
    "--page-frame-start: clamp(2rem, 3vw, 3rem);",
    "--page-frame-end: clamp(4rem, 8vw, 8rem);",
    "--frame-product-hero: 20rem;",
    "--page-title-size: clamp(2.4rem, 3.6vw, 3.25rem);",
    "--page-title-line-height: 1.08;",
    "--section-title-line-height: 1.1;",
  ]) {
    assert(stylesheet.includes(declaration), `Radar layout source omits shared declaration ${declaration}`);
  }
  assert(
    stylesheet.includes("main:not(.state-page)") &&
      stylesheet.includes("padding-top: var(--page-frame-start);") &&
      stylesheet.includes("padding: 0 clamp(1rem, 3.5vw, 3.5rem) var(--page-frame-end);"),
    "Radar page frames no longer consume the shared block-spacing tokens.",
  );
  for (const selector of [
    ".hero",
    ".methodology-heading",
    ".docs-heading",
    ".brand-scope-heading",
    ".profile-hero",
    ".artifact-hero",
    ".not-found-copy",
  ]) {
    assert(stylesheet.includes(selector), `Radar page-title contract omits ${selector}.`);
  }
  assert(
    stylesheet.includes("font-size: var(--page-title-size);") &&
      stylesheet.includes("line-height: var(--page-title-line-height);"),
    "Radar top-level headings no longer consume the shared title tokens.",
  );
  const radarHeroBlocks = [...stylesheet.matchAll(/\.radar-hero\s*\{([^}]*)\}/gs)].map((match) => match[1]);
  const desktopRadarHero = radarHeroBlocks[0] ?? "";
  for (const declaration of [
    "grid-template-columns: minmax(0, 1.7fr) minmax(18rem, .6fr);",
    "gap: clamp(2rem, 4vw, 4rem);",
    "min-height: var(--frame-product-hero);",
    "padding: 1rem 0 2rem;",
    "border: 0;",
    "border-bottom: 1px solid var(--line);",
    "background: transparent;",
    "overflow: visible;",
  ]) {
    assert(desktopRadarHero.includes(declaration), `Radar home hero omits shared declaration ${declaration}`);
  }
  assert(
    radarHeroBlocks.some((block) =>
      block.includes("grid-template-columns: minmax(0, 1fr);") &&
      block.includes("min-height: auto;") &&
      block.includes("padding: .5rem 0 2rem;")),
    "Radar mobile home hero no longer uses the shared open single-column contract.",
  );
  for (const breakpoint of [1160, 900, 680]) {
    assert(stylesheet.includes(`@media (max-width: ${breakpoint}px)`), `Radar layout omits the shared ${breakpoint}px breakpoint.`);
  }
  assert(
    stylesheet.includes("@media (max-width: 760px)") && stylesheet.includes(".table-scroll table"),
    "Radar lost its product-specific 760px table accessibility transformation.",
  );
  assert(
    !stylesheet.includes("@media (max-width: 1120px)") && !stylesheet.includes("@media (max-width: 560px)"),
    "Radar still contains retired broad presentation breakpoints.",
  );
}

const fontFiles = [
  "space-grotesk/space-grotesk-latin-wght-normal.woff2",
  "space-grotesk/space-grotesk-latin-ext-wght-normal.woff2",
  "inter/inter-latin-400-normal.woff2",
  "inter/inter-latin-ext-400-normal.woff2",
  "inter/inter-latin-400-italic.woff2",
  "inter/inter-latin-ext-400-italic.woff2",
  "inter/inter-latin-500-normal.woff2",
  "inter/inter-latin-ext-500-normal.woff2",
  "inter/inter-latin-600-normal.woff2",
  "inter/inter-latin-ext-600-normal.woff2",
  "inter/inter-latin-700-normal.woff2",
  "inter/inter-latin-ext-700-normal.woff2",
  "ibm-plex-mono/ibm-plex-mono-latin-400-normal.woff2",
  "ibm-plex-mono/ibm-plex-mono-latin-ext-400-normal.woff2",
  "ibm-plex-mono/ibm-plex-mono-latin-500-normal.woff2",
  "ibm-plex-mono/ibm-plex-mono-latin-ext-500-normal.woff2",
  "ibm-plex-mono/ibm-plex-mono-latin-600-normal.woff2",
  "ibm-plex-mono/ibm-plex-mono-latin-ext-600-normal.woff2",
  "ibm-plex-mono/ibm-plex-mono-latin-700-normal.woff2",
  "ibm-plex-mono/ibm-plex-mono-latin-ext-700-normal.woff2",
];

export function verifyIdentityArtwork() {
  for (const path of [join(root, "public", "hecavex-mark.svg"), join(output, "hecavex-mark.svg"), join(root, "public", "favicon.svg"), join(output, "favicon.svg")]) {
    const mark = readFileSync(path, "utf8").toLowerCase();
    assert(mark.includes("#55b9b1"), `${relative(root, path)} is missing shared mineral teal #55b9b1.`);
    assert(mark.includes("#ece9e1"), `${relative(root, path)} is missing shared warm white #ece9e1.`);
    assert(!mark.includes("#d06c65"), `${relative(root, path)} must reserve semantic danger red #d06c65 for status UI.`);
  }
  for (const name of ["favicon.ico", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "site.webmanifest"]) {
    assert(existsSync(join(root, "public", name)), `public/${name} is missing from the shared identity kit.`);
    assert(existsSync(join(output, name)), `dist/${name} is missing from the shared identity kit.`);
  }
  for (const [name, expectedDigest] of identityAssetDigests) {
    for (const base of [join(root, "public"), output]) {
      const assetPath = join(base, name);
      if (!existsSync(assetPath)) continue;
      const actualDigest = createHash("sha256").update(readFileSync(assetPath)).digest("hex");
      assert(actualDigest === expectedDigest, `${relative(root, assetPath)} must match the canonical HECAVEX identity asset.`);
    }
  }
  const manifest = JSON.parse(readFileSync(join(output, "site.webmanifest"), "utf8"));
  assert(manifest.name === "HECAVEX Radar" && manifest.id === "/" && manifest.scope === "/", "Radar manifest identity or scope is invalid.");
  assert(Array.isArray(manifest.icons) && manifest.icons.some((icon) => icon.src === "/icon-192.png") && manifest.icons.some((icon) => icon.src === "/icon-512.png"), "Radar manifest omits required application icons.");
}

export function verifySharedTypeAndPalette() {
  for (const fontFile of fontFiles) {
    const path = join(output, "fonts", fontFile);
    assert(existsSync(path), `Production output is missing self-hosted font ${fontFile}.`);
    assert(statSync(path).size > 5_000, `Self-hosted font ${fontFile} is unexpectedly small.`);
  }
  const css = walk(output)
    .filter((path) => path.endsWith(".css"))
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
  assert(css.includes("IBM Plex Mono") && css.includes("inter-latin-ext-400-normal.woff2"), "Built CSS does not advertise the shared HECAVEX interface fonts.");
  for (const colour of ["#111416", "#171b1d", "#1d2326", "#30383b", "#ece9e1", "#8d969a", "#55b9b1", "#86b77e", "#d2aa62", "#d06c65"]) {
    assert(css.includes(colour), `Built CSS is missing shared HECAVEX operational colour ${colour}.`);
  }
  assert(!/fonts\.(googleapis|gstatic)\.com/u.test(css), "Built CSS must not depend on remote font services.");
  assert(
    !/#(?:05080b|0b1117|101923|1c2123|1e3440|f2f8fb|b6c6cf|c9c5bc|8397a3|44c7dc|a2da68|ffc857|ff6b6b|080c11|0d131a|17212d|24303d|344455|6db18a|dda94f)|rgb\((?:5 8 11|11 17 23|16 25 35|30 52 64|68 199 220|162 218 104|255 200 87|255 107 107|8 12 17|13 19 26|23 33 45|36 48 61|52 68 85|109 177 138|221 169 79)/iu.test(css),
    "Built CSS still contains a retired HECAVEX palette value.",
  );
}
