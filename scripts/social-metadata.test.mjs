import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { completeSocialMetadata } from "../src/lib/socialMetadata.ts";

test("minimal Lithuanian route gains its actual canonical and escaped preview text", () => {
  const source = '<html lang="lt"><head><title>Ženklai &amp; įrodymai</title><meta name="description" content="&quot;Šaltinis&quot; &lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;" /><link rel="canonical" href="https://radar.hecavex.com/lt/prekes-zenklai/" /><link rel="alternate" hreflang="en" href="https://radar.hecavex.com/brands/" /></head><body></body></html>';
  const result = completeSocialMetadata(source);
  const document = new JSDOM(result).window.document;
  const meta = (key) => document.querySelector(`meta[property="${key}"],meta[name="${key}"]`)?.content;
  assert.equal(meta("og:url"), "https://radar.hecavex.com/lt/prekes-zenklai/");
  assert.equal(meta("og:title"), "Ženklai & įrodymai");
  assert.equal(meta("og:description"), '"Šaltinis" </script><script>alert(1)</script>');
  assert.equal(document.querySelectorAll("script").length, 0, "Encoded preview text cannot introduce script elements");
  assert.equal(meta("og:locale"), "lt_LT");
  assert.equal(meta("og:locale:alternate"), "en_GB");
  assert.equal(meta("twitter:image"), meta("og:image"));
  assert.ok(meta("twitter:image:alt"));
  assert.equal(completeSocialMetadata(result), result, "Completing a head twice introduces no duplicate tags");
});

test("explicit route preview overrides are retained", () => {
  const source = '<html lang="en"><head><title>Route</title><meta name="description" content="Source bounds" /><link rel="canonical" href="https://radar.hecavex.com/" /><meta property="og:image" content="https://example.org/preview.png" /><meta property="og:image:alt" content="Specific evidence preview" /><meta name="twitter:title" content="Specific title" /></head></html>';
  const document = new JSDOM(completeSocialMetadata(source)).window.document;
  assert.equal(document.querySelector('meta[name="twitter:title"]').content, "Specific title");
  assert.equal(document.querySelector('meta[name="twitter:image"]').content, "https://example.org/preview.png");
  assert.equal(document.querySelector('meta[name="twitter:image:alt"]').content, "Specific evidence preview");
  assert.equal(document.querySelectorAll('meta[property="og:image"]').length, 1);
});
