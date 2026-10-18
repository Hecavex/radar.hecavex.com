import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { URL } from "node:url";
import { decoratePage } from "../vite.config.ts";

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
