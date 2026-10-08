/** Complete social previews from the page's actual title, description and canonical. */
export function completeSocialMetadata(html: string): string {
  const entities: Record<string, string> = {
    amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", "#39": "'",
  };
  const decode = (value: string) => value.replace(/&(amp|lt|gt|quot|apos|#39);/g, (_match, entity: string) => entities[entity] ?? _match);
  const escape = (value: string) => value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  const attribute = (attributes: string, name: string) => {
    const value = attributes.match(new RegExp(`\\b${name}\\s*=\\s*(["'])(.*?)\\1`, "is"))?.[2];
    return value === undefined ? undefined : decode(value);
  };
  const metadata = new Map<string, string>();
  for (const match of html.matchAll(/<meta\b([^>]*)>/gi)) {
    const key = attribute(match[1], "property") ?? attribute(match[1], "name");
    const content = attribute(match[1], "content");
    if (key && content !== undefined) metadata.set(key, content);
  }
  const canonical = [...html.matchAll(/<link\b([^>]*)>/gi)]
    .find((match) => attribute(match[1], "rel") === "canonical");
  const url = canonical ? attribute(canonical[1], "href") : undefined;
  const title = decode(html.match(/<title\b[^>]*>(.*?)<\/title>/is)?.[1] ?? "").trim();
  const description = metadata.get("description");
  const lithuanian = /<html\b[^>]*lang=["']lt["']/i.test(html);
  const image = metadata.get("og:image") ?? "https://hecavex.com/assets/img/og/hecavex-default-en.png";
  const imageAlt = metadata.get("og:image:alt") ?? (lithuanian ? "HECAVEX Radar vieši tyrimo signalai" : "HECAVEX Radar public research signals");
  const defaults: Record<string, string> = {
    "og:image": image, "og:image:alt": imageAlt,
    "twitter:card": "summary_large_image", "twitter:image": image, "twitter:image:alt": imageAlt,
  };
  if (url) {
    if (!title || !description) throw new Error(`Missing title or description for ${url}.`);
    Object.assign(defaults, {
      "og:type": "website", "og:site_name": "HECAVEX Radar", "og:url": url,
      "og:locale": lithuanian ? "lt_LT" : "en_GB", "og:title": title, "og:description": description,
      "twitter:title": title, "twitter:description": description,
    });
    if (/hreflang=["'](?:en|lt)["']/i.test(html)) defaults["og:locale:alternate"] = lithuanian ? "en_GB" : "lt_LT";
  }
  const tags = Object.entries(defaults).filter(([key]) => !metadata.has(key)).map(([key, value]) =>
    `<meta ${key.startsWith("og:") ? "property" : "name"}="${key}" content="${escape(value)}" />`,
  );
  return tags.length ? html.replace("</head>", `${tags.join("\n")}\n</head>`) : html;
}
