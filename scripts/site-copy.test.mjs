import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { pluralize } from "../src/lib/format.ts";

registerHooks({ load(url, context, nextLoad) {
  if (url.startsWith("file:") && url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: ts.transpileModule(readFileSync(fileURLToPath(url), "utf8"), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2023 } }).outputText };
  return nextLoad(url, context);
} });
const { SiteHeader } = await import("../src/components/SiteHeader.tsx");
const { windowFromSearch } = await import("../src/pages/ChangesPage.tsx");

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

test("the header language link's accessible name contains its visible text (WCAG 2.5.3)", () => {
  for (const [language, visible] of [["en", "LT"], ["lt", "EN"]]) {
    const html = renderToStaticMarkup(createElement(SiteHeader, { currentPage: "radar", language }));
    const link = html.match(/<a class="language-link"[^>]*aria-label="([^"]+)"[^>]*>([^<]+)<\/a>/);
    assert(link, `${language} header has no labelled language link`);
    assert.equal(link[2].trim(), visible);
    assert(link[1].startsWith(visible), `${language} accessible name "${link[1]}" omits "${visible}"`);
  }
});
