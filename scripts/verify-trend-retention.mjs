/* global console, structuredClone, URL */
import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

const readJson = async (path) => JSON.parse(await readFile(new URL(path, import.meta.url), "utf8"));
const trends = await readJson("../public/data/daily-trends.json");
const quality = await readJson("../public/data/quality-metrics.json");
const server = await createServer({ configFile: false, plugins: [react()], appType: "custom",
  optimizeDeps: { noDiscovery: true, include: [] },
  server: { middlewareMode: true, watch: null, hmr: false } });
try {
  const { TrendsPage } = await server.ssrLoadModule("/src/pages/TrendsPage.tsx");
  const { encodeTrendsPageBootstrap } = await server.ssrLoadModule("/src/lib/staticPageBootstrap.ts");
  for (const language of ["en", "lt"]) {
    for (const unavailable of [false, true]) {
      const fixture = structuredClone(trends);
      const row = structuredClone(fixture.series.at(-1));
      row.discovery = unavailable ? null : { ...row.discovery, uniqueSignals: 0 };
      row.discoveryBasis = unavailable ? "unknown" : "retained-detail";
      fixture.series = [row];
      const document = new JSDOM(renderToStaticMarkup(createElement(TrendsPage, {
        language, data: { trends: fixture, quality, renderedAt: Date.parse(fixture.generatedAt) },
      }))).window.document;
      const copy = document.querySelector(".trend-signal-count").textContent;
      if (unavailable) {
        assert.equal(document.querySelectorAll(".trend-bars progress.discovery").length, 0);
        assert.equal(copy, language === "lt" ? "Aptikimo duomenys neišliko" : "Discovery history unavailable");
        assert(document.querySelector(".trend-collection-note").textContent.includes(
          language === "lt" ? "Tai nėra nulis" : "does not mean zero"));
      } else {
        assert.equal(document.querySelector(".trend-bars progress.discovery").getAttribute("value"), "0");
        assert.equal(copy, language === "lt" ? "Unikalūs signalai: 0" : "0 unique signals");
      }
      assert.equal(document.querySelectorAll(".trend-bars progress.schedule").length, 1);
    }
  }
  const capacity = structuredClone(trends);
  const representative = capacity.series.reduce((largest, row) =>
    JSON.stringify(row).length > JSON.stringify(largest).length ? row : largest);
  capacity.series = Array.from({ length: 365 }, (_, index) => ({ ...representative,
    date: new Date(Date.parse(capacity.generatedAt) - (364 - index) * 86_400_000).toISOString().slice(0, 10),
    partialDay: index === 364,
  }));
  for (const language of ["en", "lt"]) {
    const data = { trends: capacity, quality, renderedAt: Date.parse(capacity.generatedAt) };
    const html = renderToStaticMarkup(createElement(TrendsPage, { language, data }));
    const bootstrap = encodeTrendsPageBootstrap(data);
    const document = new JSDOM(html).window.document;
    assert.equal(document.querySelectorAll(".trend-row").length, 90);
    assert(document.querySelector(".trend-display-window").textContent.includes("365"));
    assert.equal(JSON.parse(decodeURIComponent(bootstrap)).trends.displayWindow.totalRows, 365);
    assert.equal(capacity.series.length, 365, "The full canonical series must not be mutated.");
    const bytes = Buffer.byteLength(html) + Buffer.byteLength(bootstrap) + 64 * 1024;
    assert(bytes <= 512 * 1024, `${language} 365-day SSR plus bootstrap and 64 KiB page headroom exceeds 512 KiB: ${bytes}`);
    console.log(`Trend 365-date capacity (${language}): ${bytes} bytes including page headroom.`);
  }
  console.log("Trend retention rendering: EN/LT unknown versus actual zero passed.");
} finally {
  await server.close();
}
