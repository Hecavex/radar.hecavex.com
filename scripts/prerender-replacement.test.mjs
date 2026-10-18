import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { URL } from "node:url";
import { decoratePage } from "../src/prerenderPages.ts";

test("rendered data containing String.replace $ patterns is inserted literally", () => {
  const template = readFileSync(new URL("../templates/signal/index.html", import.meta.url), "utf8");
  const hostile = "Pay $` $' $&";
  const html = decoratePage(template, {
    title: `${hostile} · HECAVEX Radar`,
    description: hostile,
    canonical: "https://radar.hecavex.com/signals/0123456789abcdef0123/",
    alternate: "https://radar.hecavex.com/lt/signalai/0123456789abcdef0123/",
    alternateLanguage: "lt",
    language: "en",
    markup: `<h1>${hostile}</h1><p>__TITLE__ __DESCRIPTION__</p>`,
    bootstrap: "e30",
  });
  assert.equal(html.split('<div id="root"').length - 1, 1);
  assert.equal(html.split("<head>").length - 1, 1);
  assert.ok(html.includes(`<div id="root" data-page-bootstrap="e30"><h1>${hostile}</h1>`));
  // Placeholders are filled before markup insertion, so rendered data is never substituted.
  assert.ok(html.includes("<p>__TITLE__ __DESCRIPTION__</p>"));
  assert.ok(html.includes("<title>Pay $` $' $&amp; · HECAVEX Radar</title>"));
  assert.ok(html.includes(`<meta name="description" content="Pay $\` $' $&amp;" />`));
});

test("a substituted value containing another placeholder name is not substituted again", () => {
  const template = readFileSync(new URL("../templates/signal/index.html", import.meta.url), "utf8");
  const canonical = "https://radar.hecavex.com/signals/0123456789abcdef0123/";
  const html = decoratePage(template, {
    title: "__CANONICAL__ __UNKNOWN__",
    description: "__TITLE__",
    canonical,
    alternate: "https://radar.hecavex.com/lt/signalai/0123456789abcdef0123/",
    alternateLanguage: "lt",
    language: "en",
    markup: "<p>record</p>",
    bootstrap: "e30",
  });
  assert.ok(html.includes("<title>__CANONICAL__ __UNKNOWN__</title>"));
  assert.ok(html.includes('<meta name="description" content="__TITLE__" />'));
  assert.ok(html.includes(`<link rel="canonical" href="${canonical}" />`));
  assert.ok(html.includes('<meta property="og:title" content="__CANONICAL__ __UNKNOWN__" />'));
});
