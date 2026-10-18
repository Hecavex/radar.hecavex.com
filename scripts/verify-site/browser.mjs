/* global URL, document, getComputedStyle, navigator, process, setTimeout, window */

// Browser pass: Vite preview + Chromium (Playwright) responsive, keyboard, CSP and axe checks.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import axe from "axe-core";
import { chromium } from "playwright-core";
import { preview } from "vite";
import { mobileNavigationForPath, portfolioNavigationFor, productNavigationForPath } from "./identity.mjs";
import { analyticsToken, assert, output, pages, root, widths } from "./shared.mjs";

const exactLabel = (label) => new RegExp(`^\\s*${label}\\s*$`, "u");

async function focusWithTab(page, locator, limit = 12) {
  for (let attempt = 0; attempt < limit; attempt += 1) {
    if (await locator.evaluate((element) => document.activeElement === element)) return true;
    await page.keyboard.press("Tab");
  }
  return locator.evaluate((element) => document.activeElement === element);
}

async function verifyMobileKeyboardNavigation(page, entry, width) {
  const expectedNavigation = mobileNavigationForPath(entry.path);
  const summary = page.locator(".mobile-navigation summary");
  assert(await focusWithTab(page, summary), `${entry.path} mobile menu cannot be reached with Tab at ${width}px.`);
  const summaryFocus = await summary.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
  });
  assert(
    summaryFocus.outlineStyle !== "none" && parseFloat(summaryFocus.outlineWidth) >= 2,
    `${entry.path} mobile menu has no visible keyboard focus at ${width}px.`,
  );

  await page.keyboard.press("Enter");
  assert(await page.locator(".mobile-navigation").evaluate((element) => element.hasAttribute("open")), `${entry.path} mobile menu does not open with Enter at ${width}px.`);

  for (const label of expectedNavigation) {
    await page.keyboard.press("Tab");
    const active = await page.evaluate(() => ({
      label: document.activeElement?.textContent?.replace(/\s+/gu, " ").trim(),
      outlineStyle: document.activeElement ? getComputedStyle(document.activeElement).outlineStyle : "none",
      outlineWidth: document.activeElement ? getComputedStyle(document.activeElement).outlineWidth : "0",
    }));
    assert(active.label === label, `${entry.path} keyboard navigation expected ${label}, reached ${active.label ?? "nothing"} at ${width}px.`);
    assert(
      active.outlineStyle !== "none" && parseFloat(active.outlineWidth) >= 2,
      `${entry.path} ${label} link has no visible keyboard focus at ${width}px.`,
    );
  }

  await summary.focus();
  await page.keyboard.press("Space");
  assert(!(await page.locator(".mobile-navigation").evaluate((element) => element.hasAttribute("open"))), `${entry.path} mobile menu does not close with Space at ${width}px.`);
}

async function fulfillAnalyticsScript(route) {
  await route.fulfill({
    contentType: "application/javascript",
    headers: { "access-control-allow-origin": "*" },
    body: "",
  });
}

async function verifyIndexedCtHealth(browser, origin) {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 }, bypassCSP: true });
  const page = await context.newPage();
  const health = JSON.parse(readFileSync(join(output, "data", "pipeline-health.json"), "utf8"));
  health.current.ctSearch = {
    latestRun: { outcome: "deferred-backoff" },
    providerHealth: { lastAttemptAt: "2026-09-07T09:00:00.000Z", lastSuccessAt: "2026-09-06T08:00:00.000Z",
      nextAttemptAt: "2026-09-07T13:00:00.000Z", consecutiveFailures: 6 },
  };
  await page.route("https://static.cloudflareinsights.com/beacon.min.js", fulfillAnalyticsScript);
  await page.route("**/data/pipeline-health.json", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(health) }));
  try {
    for (const [path, label, explanation] of [
      ["/", "Indexed CT search: Deferred during backoff", "No network request was made in this run."],
      ["/lt/", "Indeksuota CT paieška: Atidėta iki pakartotinio bandymo", "Šiuo paleidimu tinklo užklausa neatlikta."],
    ]) {
      await page.goto(`${origin}${path}`, { waitUntil: "networkidle" });
      await page.locator(".collection-health-disclosure > summary").click();
      const details = page.locator(".indexed-ct-health");
      assert(await details.locator("summary").textContent() === label, `${path} mislabels a no-request backoff run.`);
      await details.locator("summary").click();
      assert((await details.innerText()).includes(explanation), `${path} omits the localized no-network explanation.`);
      assert(await details.locator("time").count() === 3, `${path} hides actual attempt, success or cooldown timing.`);
      assert(await details.locator("dd").last().textContent() === "6", `${path} changes the actual failure streak.`);
      assert(await details.evaluate((node) => node.scrollWidth <= node.clientWidth + 1), `${path} overflows indexed CT telemetry on mobile.`);
      await page.addScriptTag({ content: axe.source });
      const violations = await page.evaluate(async () => (await globalThis.axe.run(".indexed-ct-health", {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
      })).violations.filter((item) => ["serious", "critical"].includes(item.impact)).map((item) => item.id));
      assert(violations.length === 0, `${path} CT telemetry accessibility failures: ${violations.join(", ")}`);
    }
  } finally {
    await context.close();
  }
}

async function verifyTrendCutoff(browser, origin) {
  const trends = JSON.parse(readFileSync(join(output, "data", "daily-trends.json"), "utf8"));
  const context = await browser.newContext({ viewport: { width: 390, height: 900 }, timezoneId: "Pacific/Auckland" });
  const page = await context.newPage();
  await page.route("https://static.cloudflareinsights.com/beacon.min.js", fulfillAnalyticsScript);
  try {
    for (const [path, incompleteLabel, delayedLabel] of [
      ["/trends/", "Incomplete at cutoff", "Update delayed."],
      ["/lt/tendencijos/", "Nepilna suvestinės diena", "Atnaujinimas vėluoja."],
    ]) {
      await page.clock.setFixedTime(Date.parse(trends.generatedAt));
      await page.goto(`${origin}${path}`, { waitUntil: "networkidle" });
      await page.locator(".trend-cutoff--current").waitFor();
      const metricsAtCutoff = await page.locator(".trend-metrics").allTextContents();
      const countsAtCutoff = await page.locator(".trend-signal-count").allTextContents();
      const datesAtCutoff = await page.locator(".trend-date time").allTextContents();

      await page.clock.setFixedTime(Date.parse(trends.generatedAt) + 2 * 86_400_000);
      await page.reload({ waitUntil: "networkidle" });
      await page.locator(".trend-cutoff--delayed").waitFor();
      assert((await page.locator(".trend-cutoff").textContent()).includes(delayedLabel), `${path} hides a stale artifact behind the original render time.`);
      assert(await page.locator(".trend-cutoff time").getAttribute("datetime") === trends.generatedAt, `${path} replaces the data cutoff with browser time.`);
      const partialRows = page.locator(".trend-row--partial");
      for (const row of await partialRows.all()) {
        assert(await row.getAttribute("data-day-state") === "incomplete", `${path} calls a historical cutoff the current partial UTC day.`);
        assert(await row.locator(".trend-date span").textContent() === incompleteLabel, `${path} omits the localized historical partial-day warning.`);
      }
      assert(JSON.stringify(await page.locator(".trend-metrics").allTextContents()) === JSON.stringify(metricsAtCutoff), `${path} rewrites saved denominators or coverage as the artifact ages.`);
      assert(JSON.stringify(await page.locator(".trend-signal-count").allTextContents()) === JSON.stringify(countsAtCutoff), `${path} invents discovery counts after the cutoff.`);
      assert(JSON.stringify(await page.locator(".trend-date time").allTextContents()) === JSON.stringify(datesAtCutoff), `${path} invents zero-day rows after the cutoff.`);
    }
  } finally {
    await context.close();
  }
}

async function verifyCountryFacetTargets(browser, origin) {
  // One bounded in-memory fixture covers a field absent from the current first
  // page. Never change the published snapshot to exercise a country action.
  const fixture = JSON.parse(readFileSync(join(output, "data", "radar.json"), "utf8"));
  assert(fixture.signals.length > 0, "Country target verification requires a published-schema fixture.");
  fixture.signals[0].country = "LT";
  const context = await browser.newContext({ viewport: { width: 320, height: 900 } });
  const page = await context.newPage();
  await page.route("https://static.cloudflareinsights.com/beacon.min.js", fulfillAnalyticsScript);
  await page.route("**/data/radar.json", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(fixture) }));
  try {
    for (const path of ["/", "/lt/"]) {
      await page.goto(`${origin}${path}?country=LT`, { waitUntil: "networkidle" });
      const country = page.locator(".signal-table .facet-button.country", { hasText: "LT" }).first();
      await country.waitFor({ state: "visible" });
      const dimensions = await country.evaluate((button) => {
        const rect = button.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      });
      assert(dimensions.width >= 43.5 && dimensions.height >= 43.5,
        `${path} country action is ${dimensions.width}x${dimensions.height}px at320px; expected at least44x44px.`);
    }
  } finally {
    await context.close();
  }
}

async function verifyAccessibility(browser, origin, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, bypassCSP: true });
  const page = await context.newPage();
  await page.route("https://static.cloudflareinsights.com/beacon.min.js", fulfillAnalyticsScript);
  try {
    for (const entry of pages) {
      await page.goto(`${origin}${entry.path}`, { waitUntil: "networkidle" });
      await page.addScriptTag({ content: axe.source });
      const result = await page.evaluate(async () => {
        const report = await globalThis.axe.run(document, {
          resultTypes: ["violations"],
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
        });
        return report.violations
          .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
          .map((violation) => ({ id: violation.id, impact: violation.impact, targets: violation.nodes.map((node) => node.target) }));
      });
      assert(result.length === 0, `${entry.path} has serious accessibility violations at ${width}px: ${JSON.stringify(result)}`);
    }
  } finally {
    await context.close();
  }
}

async function verifySignalDialog(browser, origin, width, language) {
  const rootPath = language === "lt" ? "/lt/" : "/";
  const permanentPrefix = language === "lt" ? "/lt/signalai/" : "/signals/";
  const closeLabel = language === "lt" ? "Užverti signalo informaciją" : "Close signal details";
  const context = await browser.newContext({ viewport: { width, height: 900 }, bypassCSP: true });
  const page = await context.newPage();
  await page.route("https://static.cloudflareinsights.com/beacon.min.js", fulfillAnalyticsScript);
  try {
    await page.goto(`${origin}${rootPath}`, { waitUntil: "networkidle" });
    const firstRow = page.locator('.signal-table tbody tr[id^="signal-"]').first();
    const candidateTrigger = firstRow.locator("button.candidate-link");
    const timelineTrigger = firstRow.locator("button.record-link");
    const permanentPath = await firstRow.locator("a.signal-deep-link").getAttribute("href");
    assert(
      permanentPath?.startsWith(permanentPrefix),
      `${rootPath} signal has no localized permanent record path at ${width}px.`,
    );

    await candidateTrigger.click();
    const dialog = page.locator('[role="dialog"]');
    assert(await dialog.isVisible(), `${rootPath} candidate control did not open a signal dialog at ${width}px.`);
    const closeButton = dialog.locator(`button[aria-label="${closeLabel}"]`);
    assert(await closeButton.count() === 1, `${rootPath} signal dialog does not expose its localized close label at ${width}px.`);
    assert(
      await closeButton.evaluate((element) => element === document.activeElement),
      `${rootPath} signal dialog did not place focus on its localized Close control at ${width}px.`,
    );
    const relevanceRow = dialog.locator(".candidate-provenance-full");
    assert(await relevanceRow.count() === 1, `${rootPath} signal dialog has no full-width Lithuanian relevance row at ${width}px.`);
    const relevanceLayout = await relevanceRow.evaluate((element) => {
      const row = element.getBoundingClientRect();
      const grid = element.parentElement?.getBoundingClientRect();
      return grid ? { rowLeft: row.left, rowRight: row.right, gridLeft: grid.left, gridRight: grid.right } : null;
    });
    assert(
      relevanceLayout &&
        Math.abs(relevanceLayout.rowLeft - relevanceLayout.gridLeft) <= 2 &&
        Math.abs(relevanceLayout.rowRight - relevanceLayout.gridRight) <= 2,
      `${rootPath} Lithuanian relevance does not span the provenance grid at ${width}px: ${JSON.stringify(relevanceLayout)}.`,
    );
    assert(
      await dialog.locator("a.permanent-record-link").getAttribute("href") === permanentPath,
      `${rootPath} signal dialog does not preserve its permanent record path at ${width}px.`,
    );
    if (await dialog.locator(".signal-intelligence").count()) {
      await dialog.locator(".detail-observations, .detail-state.error").first().waitFor({ state: "visible" });
      assert(!(await dialog.locator(".detail-state.error").count()), `${rootPath} signal detail sidecar failed to load at ${width}px.`);
    }

    await page.addScriptTag({ content: axe.source });
    const violations = await page.evaluate(async () => {
      const report = await globalThis.axe.run(document, {
        resultTypes: ["violations"],
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
      });
      return report.violations
        .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
        .map((violation) => ({ id: violation.id, impact: violation.impact, targets: violation.nodes.map((node) => node.target) }));
    });
    assert(violations.length === 0, `${rootPath} open signal dialog has serious accessibility violations at ${width}px: ${JSON.stringify(violations)}`);

    await page.keyboard.press("Escape");
    assert(!(await dialog.count()), `${rootPath} signal dialog did not close with Escape at ${width}px.`);
    assert(await candidateTrigger.evaluate((element) => element === document.activeElement), `${rootPath} signal dialog did not restore candidate focus at ${width}px.`);

    await timelineTrigger.click();
    const reopenedDialog = page.locator('[role="dialog"]');
    assert(await reopenedDialog.isVisible(), `${rootPath} timeline control did not open a signal dialog at ${width}px.`);
    await reopenedDialog.locator(`button[aria-label="${closeLabel}"]`).click();
    assert(!(await reopenedDialog.count()), `${rootPath} signal dialog did not close from its localized Close control at ${width}px.`);
    assert(await timelineTrigger.evaluate((element) => element === document.activeElement), `${rootPath} signal dialog did not restore timeline focus at ${width}px.`);
  } finally {
    await context.close();
  }
}

async function verifyResearchBrief(browser, origin, width, language) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  const unexpectedRequests = [];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === origin) return route.continue();
    if (url.href === "https://static.cloudflareinsights.com/beacon.min.js") return fulfillAnalyticsScript(route);
    unexpectedRequests.push(url.href);
    return route.abort();
  });
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
      writeText: async () => { throw new Error("Synthetic clipboard denial"); },
    } });
  });
  try {
    const snapshot = JSON.parse(readFileSync(join(output, "data/radar.json"), "utf8"));
    const signal = snapshot.signals[0];
    const path = `${language === "lt" ? "/lt/signalai" : "/signals"}/${signal.id}/`;
    await page.goto(`${origin}${path}`, { waitUntil: "networkidle" });
    const brief = page.locator("#research-brief-preview");
    const value = await brief.inputValue();
    assert(value.includes(signal.id) && value.includes(snapshot.generatedAt), "Research handoff lost signal provenance.");
    assert(value.includes(`https://radar.hecavex.com${path}`), "Research handoff has no canonical localized citation.");
    assert(await brief.getAttribute("readonly") !== null, "Research preview must not collect private editable input.");
    await brief.focus();
    await page.keyboard.press("ControlOrMeta+A");
    assert(await brief.evaluate((element) => element.selectionEnd === element.value.length), "Preview cannot be selected.");
    await page.keyboard.press("Tab");
    const copy = page.getByRole("button", { name: language === "lt" ? "Kopijuoti tekstą" : "Copy brief", exact: true });
    assert(await copy.evaluate((element) => element === document.activeElement), "Preview does not tab to Copy.");
    await page.keyboard.press("Enter");
    await page.getByRole("status").filter({ hasText: language === "lt" ? "Iškarpinė nepasiekiama" : "Clipboard unavailable" }).waitFor();
    const copied = [];
    await page.exposeFunction("captureResearchClipboard", (text) => copied.push(text));
    await page.evaluate(() => {
      Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
        writeText: async (text) => globalThis.captureResearchClipboard(text),
      } });
    });
    await copy.click();
    await page.getByRole("status").filter({ hasText: language === "lt" ? "Tekstas nukopijuotas" : "Brief copied" }).waitFor();
    assert(copied[0] === value, "Copied brief differs from visible preview.");
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: language === "lt" ? "Atsisiųsti tekstą" : "Download plain text", exact: true }).click();
    const download = await downloadPromise;
    assert(download.suggestedFilename() === `radar-research-${signal.id}-${language}.txt`, "Unsafe research filename.");
    assert(readFileSync(await download.path(), "utf8") === value, "Downloaded brief differs from preview.");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), "Research brief overflows viewport.");
    assert(unexpectedRequests.length === 0, `Research brief sent unexpected external requests: ${unexpectedRequests.join(", ")}`);
    const noScriptContext = await browser.newContext({ viewport: { width, height: 900 }, javaScriptEnabled: false });
    try {
      const noScriptPage = await noScriptContext.newPage();
      await noScriptPage.goto(`${origin}${path}`, { waitUntil: "networkidle" });
      assert(await noScriptPage.locator("#research-brief-preview").inputValue() === value, "No-JS preview lost published facts.");
      assert(await noScriptPage.locator(".research-brief noscript").isVisible(), "No-JS selection guidance is missing.");
      assert(!(await noScriptPage.locator(".research-brief-actions").isVisible()), "No-JS page advertises inert action controls.");
    } finally {
      await noScriptContext.close();
    }
    if (process.env.RADAR_RESEARCH_SCREENSHOT_DIR) {
      await page.locator(".research-brief").evaluate((element) => {
        window.scrollTo(0, window.scrollY + element.getBoundingClientRect().top - 140);
      });
      await page.locator(".research-brief").screenshot({ path: join(process.env.RADAR_RESEARCH_SCREENSHOT_DIR, `radar-research-${language}-${width}.png`) });
    }
  } finally {
    await context.close();
  }
}

function chromeExecutable() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].filter(Boolean);
  return candidates.find((path) => existsSync(path));
}

export async function verifyInBrowser(healthOnly = false, researchOnly = false) {
  const executablePath = chromeExecutable();
  assert(executablePath, "Chrome or Chromium is required for responsive and accessibility verification.");

  const server = await preview({
    root,
    configFile: false,
    preview: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  const address = server.httpServer.address();
  assert(address && typeof address !== "string", "Vite preview did not expose a TCP address.");
  const origin = `http://127.0.0.1:${address.port}`;
  const browser = await chromium.launch({ executablePath, headless: true, args: ["--no-sandbox"] });

  try {
    if (researchOnly) {
      for (const width of [320, 1440]) {
        for (const language of ["en", "lt"]) await verifyResearchBrief(browser, origin, width, language);
      }
      return;
    }
    await verifyIndexedCtHealth(browser, origin);
    if (healthOnly) return;
    await verifyCountryFacetTargets(browser, origin);
    await verifyTrendCutoff(browser, origin);
    for (const width of widths) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      let analyticsRequests = 0;
      let verifiedPageLoads = 0;
      await page.route("https://static.cloudflareinsights.com/beacon.min.js", async (route) => {
        analyticsRequests += 1;
        await fulfillAnalyticsScript(route);
      });
      for (const entry of pages) {
        const browserErrors = [];
        const onConsole = (message) => {
          if (message.type() === "error") browserErrors.push(`console: ${message.text()}`);
        };
        const onPageError = (error) => browserErrors.push(`page: ${error.message}`);
        page.on("console", onConsole);
        page.on("pageerror", onPageError);
        await page.goto(`${origin}${entry.path}`, { waitUntil: "networkidle" });
        verifiedPageLoads += 1;
        assert(await page.locator("#root").getAttribute("data-hydrated") === "true", `${entry.path} did not hydrate under its production CSP at ${width}px.`);
        const layout = await page.evaluate(() => {
          const main = document.querySelector("main");
          const mainRect = main?.getBoundingClientRect();
          const mainStyle = main ? getComputedStyle(main) : null;
          const firstMainBlock = main?.firstElementChild?.getBoundingClientRect();
          const heading = document.querySelector("main h1")?.getBoundingClientRect();
          const headingStyle = document.querySelector("main h1") ? getComputedStyle(document.querySelector("main h1")) : null;
          const brandMark = document.querySelector(".brand img")?.getBoundingClientRect();
          const sectionTitle = document.querySelector("main h2");
          const sectionTitleStyle = sectionTitle ? getComputedStyle(sectionTitle) : null;
          const networkBar = document.querySelector(".network-bar")?.getBoundingClientRect();
          const productBar = document.querySelector(".product-bar")?.getBoundingClientRect();
          const heroElement = document.querySelector(".hero");
          const hero = heroElement?.getBoundingClientRect();
          const heroStyle = heroElement ? getComputedStyle(heroElement) : null;
          const heroIntro = document.querySelector(".hero-intro");
          const heroIntroStyle = heroIntro ? getComputedStyle(heroIntro) : null;
          const radarHeroCopy = document.querySelector(".radar-hero .hero-copy")?.getBoundingClientRect();
          const radarFreshness = document.querySelector(".radar-hero .freshness-card")?.getBoundingClientRect();
          const metricGrid = document.querySelector(".activity-strip")?.getBoundingClientRect();
          const contentToc = document.querySelector(".methodology-toc, .docs-toc");
          const contentTocStyle = contentToc ? getComputedStyle(contentToc) : null;
          const longFormCopy = document.querySelector(".methodology-heading > p, .docs-heading > p");
          const longFormStyle = longFormCopy ? getComputedStyle(longFormCopy) : null;
          const docsTableCell = document.querySelector(".docs-table td");
          const docsTableCellStyle = docsTableCell ? getComputedStyle(docsTableCell) : null;
          const methodologyFieldList = document.querySelector(".methodology-field-list");
          const methodologyFields = methodologyFieldList ? [...methodologyFieldList.children] : [];
          const methodologyFieldListRect = methodologyFieldList?.getBoundingClientRect();
          const finalMethodologyFieldRect = methodologyFields.at(-1)?.getBoundingClientRect();
          const penultimateMethodologyFieldRect = methodologyFields.at(-2)?.getBoundingClientRect();
          const candidateCell = document.querySelector(".signal-table .indicator-cell");
          const candidateInner = candidateCell?.querySelector(":scope > div");
          const candidateCellRect = candidateCell?.getBoundingClientRect();
          const candidateControls = candidateInner ? [...candidateInner.querySelectorAll("button, a")] : [];
          const candidateControlsFit = candidateCellRect
            ? candidateControls.every((control) => {
                const rect = control.getBoundingClientRect();
                return rect.width > 0 && rect.left >= candidateCellRect.left - 1 && rect.right <= candidateCellRect.right + 1;
              })
            : true;
          const signalTable = document.querySelector(".signal-table");
          const signalTableRect = signalTable?.getBoundingClientRect();
          const hostNames = [...document.querySelectorAll(".signal-table .host-name, .signal-table .hosting-unknown")];
          const longestHost = hostNames.sort((left, right) => (right.textContent?.length ?? 0) - (left.textContent?.length ?? 0))[0];
          const hostingCellRect = longestHost?.closest("td")?.getBoundingClientRect();
          const hostStyle = longestHost ? getComputedStyle(longestHost) : null;
          const overviewBlocks = [
            ["hero", ".radar-hero"],
            ["activity", ".activity-strip"],
            ["filters", ".filter-shell"],
            ["table", ".table-panel"],
            ["exports", ".export-actions"],
            ["recorded hostnames", ".observed-summary"],
            ["routes", ".radar-route-grid"],
            ["disclosure", ".collection-disclosure"],
          ].map(([name, selector]) => {
            const rect = document.querySelector(selector)?.getBoundingClientRect();
            return rect
              ? { name, width: rect.width, height: rect.height, left: rect.left, right: rect.right }
              : { name, width: 0, height: 0, left: 0, right: 0 };
          });
          return {
            clientWidth: document.documentElement.clientWidth,
            documentWidth: document.documentElement.scrollWidth,
            bodyWidth: document.body.scrollWidth,
            headingHeight: heading?.height ?? 0,
            headingRight: heading?.right ?? 0,
            headingFontSize: headingStyle ? parseFloat(headingStyle.fontSize) : 0,
            headingLineHeight: headingStyle ? parseFloat(headingStyle.lineHeight) : 0,
            headingFontWeight: headingStyle?.fontWeight ?? "",
            headingLetterSpacing: headingStyle ? parseFloat(headingStyle.letterSpacing) : 0,
            headingFontFamily: headingStyle?.fontFamily ?? "",
            brandMarkWidth: brandMark?.width ?? 0,
            sectionTitleFontSize: sectionTitleStyle ? parseFloat(sectionTitleStyle.fontSize) : 0,
            sectionTitleLineHeight: sectionTitleStyle ? parseFloat(sectionTitleStyle.lineHeight) : 0,
            frameTop: mainRect?.top ?? 0,
            framePaddingTop: mainStyle ? parseFloat(mainStyle.paddingTop) : 0,
            framePaddingBottom: mainStyle ? parseFloat(mainStyle.paddingBottom) : 0,
            firstMainBlockTop: firstMainBlock?.top ?? 0,
            networkHeight: networkBar?.height ?? 0,
            productHeight: productBar?.height ?? 0,
            headerUtilityHeights: [...document.querySelectorAll(".product-bar .header-utility a")]
              .map((element) => element.getBoundingClientRect().height),
            heroHeight: hero?.height ?? 0,
            heroBorderTop: heroStyle ? parseFloat(heroStyle.borderTopWidth) : 0,
            heroBorderLeft: heroStyle ? parseFloat(heroStyle.borderLeftWidth) : 0,
            heroBorderBottom: heroStyle ? parseFloat(heroStyle.borderBottomWidth) : 0,
            heroPaddingLeft: heroStyle ? parseFloat(heroStyle.paddingLeft) : 0,
            heroContentWidth: heroElement && heroStyle
              ? heroElement.clientWidth - parseFloat(heroStyle.paddingLeft) - parseFloat(heroStyle.paddingRight)
              : 0,
            heroIntroFontSize: heroIntroStyle ? parseFloat(heroIntroStyle.fontSize) : 0,
            heroIntroLineHeight: heroIntroStyle ? parseFloat(heroIntroStyle.lineHeight) : 0,
            radarHeroCopyWidth: radarHeroCopy?.width ?? 0,
            radarHeroCopyBottom: radarHeroCopy?.bottom ?? 0,
            radarFreshnessTop: radarFreshness?.top ?? 0,
            radarFreshnessWidth: radarFreshness?.width ?? 0,
            metricTop: metricGrid?.top ?? 0,
            contentTocBorderTop: contentTocStyle?.borderTop ?? "",
            contentTocBorderBottom: contentTocStyle?.borderBottom ?? "",
            longFormAlign: longFormStyle?.textAlign ?? "",
            longFormAlignLast: longFormStyle?.textAlignLast ?? "",
            longFormHyphens: longFormStyle?.hyphens ?? "",
            docsTableCellAlign: docsTableCellStyle?.textAlign ?? "",
            methodologyFieldCount: methodologyFields.length,
            methodologyFieldListLeft: methodologyFieldListRect?.left ?? 0,
            methodologyFieldListRight: methodologyFieldListRect?.right ?? 0,
            finalMethodologyFieldLeft: finalMethodologyFieldRect?.left ?? 0,
            finalMethodologyFieldRight: finalMethodologyFieldRect?.right ?? 0,
            penultimateMethodologyFieldLeft: penultimateMethodologyFieldRect?.left ?? 0,
            penultimateMethodologyFieldRight: penultimateMethodologyFieldRect?.right ?? 0,
            candidateControlCount: candidateControls.length,
            candidateControlsFit,
            candidateInnerClientWidth: candidateInner?.clientWidth ?? 0,
            candidateInnerScrollWidth: candidateInner?.scrollWidth ?? 0,
            hostingColumnRatio: signalTableRect && hostingCellRect ? hostingCellRect.width / signalTableRect.width : 0,
            hostOverflowX: hostStyle?.overflowX ?? "",
            hostOverflowY: hostStyle?.overflowY ?? "",
            hostClientHeight: longestHost?.clientHeight ?? 0,
            hostScrollHeight: longestHost?.scrollHeight ?? 0,
            overviewBlocks,
          };
        });
        const overview = entry.path === "/" || entry.path === "/lt/";
        assert(
          layout.documentWidth <= layout.clientWidth + 1 && layout.bodyWidth <= layout.clientWidth + 1,
          `${entry.path} overflows horizontally at ${width}px (${layout.documentWidth}/${layout.bodyWidth} > ${layout.clientWidth}).`,
        );
        assert(layout.headingHeight > 0 && layout.headingHeight < 540, `${entry.path} has an oversized h1 at ${width}px.`);
        assert(layout.headingFontSize <= 64.1, `${entry.path} exceeds the 64px display-heading ceiling at ${width}px.`);
        assert(layout.headingFontFamily.includes("Space Grotesk"), `${entry.path} omits the shared display face at ${width}px.`);
        assert(layout.headingRight <= layout.clientWidth + 1, `${entry.path} h1 escapes the viewport at ${width}px.`);
        const expectedPageTitle = Math.min(52, Math.max(38.4, width * .036));
        const expectedFrameStart = Math.min(48, Math.max(32, width * .03));
        const expectedFrameEnd = Math.min(128, Math.max(64, width * .08));
        assert(
          Math.abs(layout.headingFontSize - expectedPageTitle) <= .25 &&
            Math.abs(layout.headingLineHeight - layout.headingFontSize * 1.08) <= .25,
          `${entry.path} page title is ${layout.headingFontSize}/${layout.headingLineHeight}px at ${width}px; ` +
            `expected ${expectedPageTitle.toFixed(2)}px with 1.08 line-height.`,
        );
        assert(
          layout.headingFontWeight === "600" &&
            Math.abs(layout.headingLetterSpacing - (layout.headingFontSize * -.04)) <= .08,
          `${entry.path} standard title uses weight/tracking ${layout.headingFontWeight}/${layout.headingLetterSpacing}px at ${width}px; ` +
            "expected 600/-0.04em.",
        );
        if (layout.sectionTitleFontSize > 0) {
          assert(
            Math.abs(layout.sectionTitleLineHeight - (layout.sectionTitleFontSize * 1.1)) <= .3,
            `${entry.path} section title is ${layout.sectionTitleFontSize}/${layout.sectionTitleLineHeight}px at ${width}px; ` +
              "expected a 1.1 line-height.",
          );
        }
        assert(
          Math.abs(layout.framePaddingTop - expectedFrameStart) <= .25 &&
            Math.abs(layout.framePaddingBottom - expectedFrameEnd) <= .25 &&
            Math.abs(layout.firstMainBlockTop - (layout.frameTop + layout.framePaddingTop)) <= 1,
          `${entry.path} frame rhythm is ${layout.framePaddingTop}/${layout.framePaddingBottom}px at ${width}px; ` +
            `expected ${expectedFrameStart.toFixed(2)}/${expectedFrameEnd.toFixed(2)}px.`,
        );
        assert(Math.abs(layout.networkHeight - 64) <= 1, `${entry.path} network row is ${layout.networkHeight}px at ${width}px, expected 64px.`);
        if (width <= 1160) {
          assert(Math.abs(layout.brandMarkWidth - 36) <= .25, `${entry.path} mobile brand mark is ${layout.brandMarkWidth}px at ${width}px, expected 36px.`);
        }

        if (width > 1160) {
          assert(Math.abs(layout.productHeight - 52) <= 1, `${entry.path} product row is ${layout.productHeight}px at ${width}px, expected 52px.`);
          assert(layout.headerUtilityHeights.length > 0 && layout.headerUtilityHeights.every((height) => Math.abs(height - 44) <= .25),
            `${entry.path} header utilities are not consistently 44px tall at ${width}px.`);
        } else {
          assert(layout.productHeight === 0, `${entry.path} exposes the desktop product row at ${width}px.`);
        }
        if (overview) {
          assert(layout.heroBorderTop === 0 && layout.heroBorderLeft === 0 && layout.heroBorderBottom === 1 && layout.heroPaddingLeft === 0,
            `${entry.path} lost its open, inner-edge-aligned hero composition at ${width}px.`);
          for (const block of layout.overviewBlocks) {
            assert(
              block.width > 0 && block.height > 0,
              `${entry.path} ${block.name} block has no rendered geometry at ${width}px.`,
            );
            assert(
              block.left >= -1 && block.right <= layout.clientWidth + 1,
              `${entry.path} ${block.name} block escapes the viewport at ${width}px (${block.left}-${block.right}).`,
            );
          }
        }
        if (width === 1440 && overview) {
          assert(layout.heroHeight >= 320 && layout.heroHeight <= 430, `Radar hero is ${layout.heroHeight}px at 1440x900; expected 320–430px.`);
          assert(Math.abs(layout.heroIntroFontSize - 20) <= .1 && Math.abs(layout.heroIntroLineHeight - 29) <= .1,
            `Radar home lead is ${layout.heroIntroFontSize}/${layout.heroIntroLineHeight}px at 1440px, expected the shared 20/29px role.`);
          assert(layout.metricTop > 0 && layout.metricTop < 760, `Radar summary starts below useful 1440x900 content at ${layout.metricTop}px.`);
          assert(
            layout.hostingColumnRatio >= 0.21 && layout.hostingColumnRatio <= 0.23,
            `Radar hosting column uses ${(layout.hostingColumnRatio * 100).toFixed(1)}% of the table at 1440px instead of 22%.`,
          );
          assert(
            layout.hostOverflowX !== "hidden" &&
              layout.hostOverflowY !== "hidden" &&
              layout.hostScrollHeight <= layout.hostClientHeight + 1,
            "Radar hosting evidence is clipped instead of visibly wrapped.",
          );
        }
        if (width <= 760 && overview) {
          assert(
            layout.radarHeroCopyWidth >= layout.heroContentWidth - 1,
            `Radar hero copy is squeezed to ${layout.radarHeroCopyWidth}px inside a ${layout.heroContentWidth}px content box at ${width}px.`,
          );
          assert(
            layout.radarFreshnessWidth >= layout.heroContentWidth - 1,
            `Radar freshness card is squeezed to ${layout.radarFreshnessWidth}px inside a ${layout.heroContentWidth}px content box at ${width}px.`,
          );
          assert(
            layout.radarFreshnessTop >= layout.radarHeroCopyBottom - 1,
            `Radar freshness card overlaps the hero copy at ${width}px.`,
          );
          assert(
            layout.candidateControlCount === 3 &&
              layout.candidateControlsFit &&
              layout.candidateInnerScrollWidth <= layout.candidateInnerClientWidth + 1,
            `Radar candidate controls overflow their mobile card at ${width}px.`,
          );
        }
        if (["/methodology/", "/lt/metodologija/", "/docs/", "/lt/dokumentacija/"].includes(entry.path)) {
          assert(
            layout.contentTocBorderTop === layout.contentTocBorderBottom && layout.contentTocBorderTop.startsWith("1px solid "),
            `${entry.path} content navigation dividers are not a matching 1px pair at ${width}px ` +
              `(${layout.contentTocBorderTop || "none"}/${layout.contentTocBorderBottom || "none"}).`,
          );
          const expectedLongFormAlign = width <= 680 ? "left" : "justify";
          const expectedLongFormAlignLast = width <= 680 ? "auto" : "left";
          assert(
            layout.longFormAlign === expectedLongFormAlign &&
              layout.longFormAlignLast === expectedLongFormAlignLast &&
              layout.longFormHyphens === "auto",
            `${entry.path} long-form prose alignment drifted at ${width}px ` +
              `(${layout.longFormAlign}/${layout.longFormAlignLast}/${layout.longFormHyphens}); ` +
              `expected ${expectedLongFormAlign}/${expectedLongFormAlignLast}/auto.`,
          );
          if (entry.path === "/docs/" || entry.path === "/lt/dokumentacija/") {
            assert(layout.docsTableCellAlign !== "justify", `Documentation table cells inherited prose justification at ${width}px.`);
          }
        }
        if (entry.path === "/methodology/" || entry.path === "/lt/metodologija/") {
          assert(layout.methodologyFieldCount === 8, `Methodology field reference has ${layout.methodologyFieldCount} entries instead of 8.`);
          if (width <= 760) {
            assert(
              Math.abs(layout.finalMethodologyFieldLeft - (layout.methodologyFieldListLeft + 1)) <= 1 &&
                Math.abs(layout.finalMethodologyFieldRight - (layout.methodologyFieldListRight - 1)) <= 1,
              `Methodology field grid exposes an empty final cell at ${width}px.`,
            );
          } else {
            assert(
              Math.abs(layout.penultimateMethodologyFieldLeft - (layout.methodologyFieldListLeft + 1)) <= 1 &&
                Math.abs(layout.finalMethodologyFieldRight - (layout.methodologyFieldListRight - 1)) <= 1 &&
                Math.abs(layout.finalMethodologyFieldLeft - layout.penultimateMethodologyFieldRight) <= 2,
              `Methodology field grid does not fill its final two-column row at ${width}px.`,
            );
          }
        }

        await page.keyboard.press("Tab");
        const focus = await page.evaluate(() => {
          const active = document.activeElement;
          const rect = active?.getBoundingClientRect();
          const style = active ? getComputedStyle(active) : null;
          return {
            className: active?.className,
            top: rect?.top,
            outlineStyle: style?.outlineStyle,
            outlineWidth: style?.outlineWidth,
          };
        });
        assert(focus.className === "skip-link" && (focus.top ?? -1) >= 0, `${entry.path} skip link is not first and visible.`);
        assert(
          focus.outlineStyle !== "none" && parseFloat(focus.outlineWidth ?? "0") >= 2,
          `${entry.path} focused skip link has no visible outline.`,
        );

        if (width <= 1160) {
          const expectedMobileNavigation = mobileNavigationForPath(entry.path);
          const summary = page.locator(".mobile-navigation summary");
          assert(await summary.isVisible(), `${entry.path} mobile menu is not reachable at ${width}px.`);
          await verifyMobileKeyboardNavigation(page, entry, width);
          await summary.click();
          for (const label of expectedMobileNavigation) {
            assert(
              await page.locator(".mobile-navigation-panel a", { hasText: exactLabel(label) }).isVisible(),
              `${entry.path} mobile navigation hides ${label} at ${width}px.`,
            );
          }
          await summary.click();
        } else {
          for (const label of portfolioNavigationFor(entry.path)) {
            assert(
              await page.locator(".portfolio-navigation a", { hasText: exactLabel(label) }).isVisible(),
              `${entry.path} desktop portfolio navigation hides ${label} at ${width}px.`,
            );
          }
          for (const label of productNavigationForPath(entry.path)) {
            assert(
              await page.locator(".product-navigation a", { hasText: exactLabel(label) }).isVisible(),
              `${entry.path} desktop product navigation hides ${label} at ${width}px.`,
            );
          }
          assert(await page.locator(".header-utility .source-link").isVisible(), `${entry.path} desktop Source utility is hidden at ${width}px.`);
        }

        if ((width === 390 || width === 1440) && overview) {
          const sourceLabel = entry.path === "/lt/" ? "Šaltinis" : "Source";
          const advanced = page.locator(".advanced-filter-shell");
          assert(!(await advanced.evaluate((element) => element.open)), `${entry.path} default advanced controls are not collapsed.`);
          await page.locator("#signal-search").fill("private local search");
          assert(!page.url().includes("private") && !page.url().includes("query="), `${entry.path} free-text signal search leaked into the URL.`);
          assert(!(await advanced.evaluate((element) => element.open)), `${entry.path} ordinary typing opened advanced controls.`);
          await page.getByRole("button", { name: entry.path === "/lt/" ? "3 d." : "3 days", exact: true }).click();
          assert(!(await advanced.evaluate((element) => element.open)), `${entry.path} a time-window change opened advanced controls.`);
          const resetAll = page.locator(".filter-actions .reset-button");
          assert(await resetAll.isVisible(), `${entry.path} search/time reset is hidden inside advanced controls.`);
          await resetAll.click();
          assert((await page.locator("#signal-search").inputValue()) === "", `${entry.path} reset did not clear the local query.`);
          assert(await page.locator("#signal-search").evaluate((element) => element === document.activeElement), `${entry.path} reset did not return focus to search.`);
          assert(new URL(page.url()).search === "", `${entry.path} reset did not clear controlled URL state.`);
          await advanced.locator("summary").click();
          await page.locator(`select[aria-label="${sourceLabel}"]`).selectOption("CertStream");
          assert(
            page.url().includes("source=CertStream") && !page.url().includes("private"),
            `${entry.path} controlled source filter did not produce a safe shareable URL.`,
          );
          assert(
            await page.locator(".signal-section .export-actions button", { hasText: "CSV" }).isVisible(),
            `${entry.path} defanged CSV export is not visible.`,
          );
          await advanced.locator("summary").click();
          assert(!(await advanced.evaluate((element) => element.open)), `${entry.path} advanced controls could not be manually collapsed.`);
          await page.locator("#signal-search").fill("private local search");
          assert(!(await advanced.evaluate((element) => element.open)), `${entry.path} typing reopened manually collapsed advanced controls.`);
          assert(await advanced.locator("summary span").isVisible(), `${entry.path} collapsed controls hide their active-filter count.`);
          if (width === 390) {
            await page.evaluate(() => Object.defineProperty(navigator, "clipboard", {
              configurable: true,
              value: { writeText: async () => { throw new Error("Clipboard denied for recovery check"); } },
            }));
            await page.locator(".share-filter-button").click();
            const fallback = page.locator(".filter-copy-fallback input");
            assert(await fallback.isVisible(), `${entry.path} clipboard denial has no manual recovery.`);
            const sharedUrl = await fallback.inputValue();
            assert(sharedUrl.includes("source=CertStream") && !sharedUrl.includes("private"),
              `${entry.path} clipboard recovery does not preserve the controlled-only sharing boundary.`);
          }
          await page.goto(new URL(`${entry.path}?source=CertStream`, origin).href, { waitUntil: "networkidle" });
          verifiedPageLoads += 1;
          assert((await page.locator(`select[aria-label="${sourceLabel}"]`).inputValue()) === "CertStream", `${entry.path} controlled source URL did not restore.`);
          assert(await advanced.evaluate((element) => element.open), `${entry.path} restored advanced criteria did not reveal their controls.`);
          await page.locator(".filter-actions .reset-button").click();
          assert(!page.url().includes("source="), `${entry.path} reset did not remove controlled URL criteria.`);
          assert(await page.locator("#signal-search").evaluate((element) => element === document.activeElement), `${entry.path} controlled-view reset did not return focus to search.`);
          assert(await advanced.evaluate((element) => element.open), `${entry.path} reset unexpectedly collapsed the reader's open controls.`);
        }

        if ((width === 390 || width === 1440) && ["/history/", "/lt/istorija/"].includes(entry.path) && existsSync(join(output, "data", "period-metrics-v1.json"))) {
          const metrics = JSON.parse(readFileSync(join(output, "data", "period-metrics-v1.json"), "utf8"));
          const period = page.locator(".period-overview");
          await page.waitForFunction(() => document.querySelector(".period-overview .export-actions button")?.disabled === false);
          await period.getByRole("button", { name: entry.path.startsWith("/lt/") ? "Visa išsaugota istorija" : "All recorded", exact: true }).click();
          assert(await period.locator("[data-period-count]").getAttribute("data-period-count") === String(metrics.windows.find((window) => window.key === "all").uniqueHostnames), `${entry.path} does not select the complete recorded hostname period.`);
          await period.locator('input[type="search"]').fill("private inventory query");
          assert(!page.url().includes("private") && !page.url().includes("query="), `${entry.path} inventory search leaked into the URL.`);
          assert(await period.locator("tbody tr").count() === 0, `${entry.path} inventory search does not filter the selected population.`);
          assert(await period.locator("[data-period-count]").getAttribute("data-period-count") === String(metrics.windows.find((window) => window.key === "all").uniqueHostnames), `${entry.path} search overwrote the authoritative period headline.`);
          await period.locator('input[type="search"]').fill("");
          await period.getByRole("button", { name: entry.path.startsWith("/lt/") ? "30 dienų" : "30 days", exact: true }).click();
          await period.evaluate((element) => element.scrollIntoView({ block: "start", behavior: "instant" }));
          const primaryPlacement = await page.evaluate(() => ({
            headerBottom: document.querySelector(".site-header").getBoundingClientRect().bottom,
            titleTop: document.querySelector("#observed-hostnames-title").getBoundingClientRect().top,
            countTop: document.querySelector(".period-primary").getBoundingClientRect().top,
          }));
          assert(primaryPlacement.titleTop >= primaryPlacement.headerBottom && primaryPlacement.countTop >= primaryPlacement.headerBottom,
            `${entry.path} sticky header covers the anchored primary metric at ${width}px: ${JSON.stringify(primaryPlacement)}`);
        }

        if ((width === 390 || width === 1440) && ["/changes/", "/lt/pokyciai/"].includes(entry.path)) {
          const existingEvents = await page.locator(".event-list li").count();
          if (existingEvents > 0) {
            await page.locator('.event-filters input[type="date"]').fill("9999-12-31");
            assert(await page.locator(".event-list li").count() === 0, `${entry.path} does not apply the event date filter.`);
            const reset = page.locator(".empty-copy button");
            assert(await reset.isVisible(), `${entry.path} filtered empty state omits recovery.`);
            await reset.click();
            assert(await page.locator(".event-list li").count() === existingEvents, `${entry.path} clear filters does not restore events.`);
          }
        }

        assert(browserErrors.length === 0, `${entry.path} failed its CSP-enforced browser smoke check at ${width}px: ${browserErrors.join(" | ")}`);
        page.off("console", onConsole);
        page.off("pageerror", onPageError);
      }
      assert(
        analyticsRequests === (analyticsToken ? verifiedPageLoads : 0),
        `Cloudflare Web Analytics loaded ${analyticsRequests} times for ${verifiedPageLoads} page loads at ${width}px.`,
      );
      await context.close();
      if (width === 390 || width === 1024) {
        await verifyAccessibility(browser, origin, width);
        await verifySignalDialog(browser, origin, width, "en");
        await verifySignalDialog(browser, origin, width, "lt");
      }
      if (width === 320 || width === 1440) {
        await verifyResearchBrief(browser, origin, width, "en");
        await verifyResearchBrief(browser, origin, width, "lt");
      }
    }

    const delayedContext = await browser.newContext({ viewport: { width: 390, height: 900 } });
    const delayedPage = await delayedContext.newPage();
    await delayedPage.route("https://static.cloudflareinsights.com/beacon.min.js", fulfillAnalyticsScript);
    await delayedPage.route("**/data/radar.json", async (route) => {
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 750));
      await route.continue();
    });
    await delayedPage.goto(`${origin}/`, { waitUntil: "domcontentloaded" });
    const delayedText = await delayedPage.locator("#root").innerText();
    assert(delayedText.includes("Sampled discovery, not continuous monitoring"), "Radar discards prerendered content while refreshing its snapshot.");
    assert(!delayedText.includes("Loading recent signals"), "Radar replaces prerendered content with a loading state during hydration.");
    assert(await delayedPage.locator("#root").getAttribute("data-hydrated") === "true", "Radar did not hydrate its embedded snapshot before refresh.");
    await delayedPage.waitForLoadState("networkidle");
    await delayedContext.close();

    for (const fallback of [
      {
        path: "/",
        marker: "Sampled discovery, not continuous monitoring",
        warning: "Refresh unavailable · showing embedded snapshot",
      },
      {
        path: "/lt/",
        marker: "Atrankinis aptikimas, o ne nuolatinė stebėsena",
        warning: "Atnaujinimas nepasiekiamas · rodoma įterpta suvestinė",
      },
    ]) {
      const fallbackContext = await browser.newContext({ viewport: { width: 390, height: 900 } });
      const fallbackPage = await fallbackContext.newPage();
      await fallbackPage.route("https://static.cloudflareinsights.com/beacon.min.js", fulfillAnalyticsScript);
      await fallbackPage.route("**/data/radar.json", (route) => route.fulfill({
        status: 503,
        contentType: "application/json",
        body: '{"error":"temporary"}',
      }));
      await fallbackPage.goto(`${origin}${fallback.path}`, { waitUntil: "networkidle" });
      await fallbackPage.getByText(fallback.warning, { exact: true }).waitFor();
      const fallbackText = await fallbackPage.locator("#root").innerText();
      const normalizedFallbackText = fallbackText.replace(/\s+/gu, " ");
      assert(normalizedFallbackText.includes(fallback.marker), `${fallback.path} discards its embedded snapshot after a refresh failure.`);
      assert(!normalizedFallbackText.includes("snapshot could not be loaded") && !normalizedFallbackText.includes("Nepavyko įkelti radaro suvestinės"), `${fallback.path} replaces last-known-good data with a fatal refresh error.`);
      assert(await fallbackPage.locator("#root").getAttribute("data-hydrated") === "true", `${fallback.path} did not hydrate its fallback snapshot.`);
      await fallbackContext.close();
    }

    const dntContext = await browser.newContext({ viewport: { width: 390, height: 900 } });
    await dntContext.addInitScript(() => {
      Object.defineProperty(navigator, "doNotTrack", { configurable: true, get: () => "1" });
      Object.defineProperty(window, "doNotTrack", { configurable: true, value: "1" });
    });
    const dntPage = await dntContext.newPage();
    let dntAnalyticsRequests = 0;
    await dntPage.route("https://static.cloudflareinsights.com/beacon.min.js", async (route) => {
      dntAnalyticsRequests += 1;
      await route.abort();
    });
    for (const entry of pages) {
      await dntPage.goto(`${origin}${entry.path}`, { waitUntil: "networkidle" });
    }
    assert(dntAnalyticsRequests === 0, "Cloudflare Web Analytics loaded despite the browser's Do Not Track signal.");
    await dntContext.close();

    const noScriptContext = await browser.newContext({ viewport: { width: 390, height: 900 }, javaScriptEnabled: false });
    const noScriptPage = await noScriptContext.newPage();
    for (const entry of pages) {
      await noScriptPage.goto(`${origin}${entry.path}`, { waitUntil: "load" });
      assert(await noScriptPage.locator("main#main-content").isVisible(), `${entry.path} has no visible no-JS main content.`);
      assert((await noScriptPage.locator("body").innerText()).includes(entry.marker), `${entry.path} loses core content without JavaScript.`);
      const summary = noScriptPage.locator(".mobile-navigation summary");
      await summary.click();
      const methodologyLabel = entry.path.startsWith("/lt/") ? "Metodologija" : "Methodology";
      assert(await noScriptPage.locator(".mobile-navigation-panel a", { hasText: methodologyLabel }).isVisible(), `${entry.path} no-JS menu does not open.`);
    }
    await noScriptContext.close();
  } finally {
    await browser.close();
    await new Promise((resolveClose, rejectClose) => {
      server.httpServer.close((error) => (error ? rejectClose(error) : resolveClose()));
    });
  }
}
