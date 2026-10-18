import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { fileURLToPath } from "node:url";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import ts from "typescript";
import { pluralize } from "../src/lib/format.ts";

registerHooks({ load(url, context, nextLoad) {
  if (url.startsWith("file:") && url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: ts.transpileModule(readFileSync(fileURLToPath(url), "utf8"), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2023 } }).outputText };
  return nextLoad(url, context);
} });
const { SiteHeader } = await import("../src/components/SiteHeader.tsx");
const { ChangesPage, windowFromSearch } = await import("../src/pages/ChangesPage.tsx");

test("observation counts use CLDR plural forms in EN and LT", () => {
  const en = { one: "observation", other: "observations" };
  const lt = { one: "stebėjimas", few: "stebėjimai", other: "stebėjimų" };
  assert.deepEqual([1, 2, 0].map((count) => pluralize(count, "en", en)), ["observation", "observations", "observations"]);
  assert.deepEqual([1, 2, 9, 10, 11, 21, 0].map((count) => pluralize(count, "lt", lt)), ["stebėjimas", "stebėjimai", "stebėjimai", "stebėjimų", "stebėjimų", "stebėjimas", "stebėjimų"]);
});

test("the Changes window comes only from controlled values and defaults to 30 days", () => {
  assert.equal(windowFromSearch("?window=7d"), "7d");
  assert.equal(windowFromSearch("?window=24h&brand=x"), "24h");
  for (const search of ["", "?window=30d", "?window=1y", "?window=", "?window=7D"]) assert.equal(windowFromSearch(search), "30d", search);
});

test("re-selecting the current Changes window adds no history entry, even with other encoded parameters", async () => {
  // A shared link whose other parameter the URL API would re-serialise (%20 -> +).
  const dom = new JSDOM('<div id="root"></div>', { url: "https://radar.hecavex.com/changes/?utm=a%20b&window=7d" });
  const saved = Object.fromEntries(["window", "document", "navigator", "IS_REACT_ACT_ENVIRONMENT"].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.defineProperties(globalThis, { window: { value: dom.window, configurable: true }, document: { value: dom.window.document, configurable: true }, navigator: { value: dom.window.navigator, configurable: true }, IS_REACT_ACT_ENVIRONMENT: { value: true, configurable: true } });
  const data = { events: { generatedAt: "2026-10-18T00:00:00.000Z", window: { days: 30 }, events: [], totalAvailable: 0, truncated: false } };
  try {
    const root = createRoot(dom.window.document.getElementById("root"));
    await act(async () => root.render(createElement(ChangesPage, { data, language: "en" })));
    const chip = (label) => [...dom.window.document.querySelectorAll("button")].find((button) => button.textContent === label);
    const entries = dom.window.history.length;
    await act(async () => chip("7 days").click());
    assert.equal(dom.window.history.length, entries, "re-selecting the restored window added a dead Back entry");
    await act(async () => chip("24 hours").click());
    assert.equal(dom.window.history.length, entries + 1);
    assert.match(dom.window.location.search, /window=24h/);
    await act(async () => chip("24 hours").click());
    assert.equal(dom.window.history.length, entries + 1);
    await act(async () => root.unmount());
  } finally {
    for (const [key, descriptor] of Object.entries(saved)) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key]; }
    dom.window.close();
  }
});

test("the header language link's accessible name contains its visible text (WCAG 2.5.3)", () => {
  for (const [language, visible] of [["en", "LT"], ["lt", "EN"]]) {
    const html = renderToStaticMarkup(createElement(SiteHeader, { currentPage: "radar", language }));
    const link = html.match(/<a class="language-link"[^>]*aria-label="([^"]+)"[^>]*>([^<]+)<\/a>/);
    assert(link, `${language} header has no labelled language link`);
    assert.equal(link[2].trim(), visible);
    assert(link[1].startsWith(visible), `${language} accessible name "${link[1]}" omits "${visible}"`);
  }
});
