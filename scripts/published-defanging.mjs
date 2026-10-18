// Fail-closed sweep: every string in every published JSON/XML file must be
// defanged unless it sits in an explicitly allowlisted raw field.
import { readFileSync, readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { JSDOM } from "jsdom";

// Mirrors hecavex_radar.safety.DOMAIN_IN_TEXT: whatever the defanger would rewrite is fanged.
const label = String.raw`[^\x00-\x2f\x3a-\x40\x5b-\x60\x7b-\x7f\s\u3002\uff0e\uff61]`;
const fangedHost = new RegExp(String.raw`(?:${label}(?:${label}|-){0,62}[.\u3002\uff0e\uff61])+\p{L}(?:${label}|-){1,62}`, "u");
const liveUrl = /(?<![a-z\d])(?:https?|ftp|wss?):\/\//iu;

const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const matches = (pattern) => (value) => pattern.test(value);
const exact = (...values) => (value) => values.includes(value);
const typed = (type) => (_value, parent) => parent?.type === type;
const any = () => true;
const ownOrigin = matches(/^https:\/\/radar\.hecavex\.com\/[\w./~%-]*$/u);
const ownDataPath = matches(/^\/data\/[\w./-]+$/u);
const partPath = matches(/^(?:\/data\/)?(?:history|observed-hostnames)-parts\/[a-f\d]{64}\.json$/u);
const urlscanReport = matches(new RegExp(`^https://urlscan\\.io/result/${uuid}/$`, "u"));
const urlscanScreenshot = matches(new RegExp(`^https://urlscan\\.io/screenshots/${uuid}\\.png$`, "u"));
const sourceHomepages = ["https://certstream.dev/", "https://urlscan.io/", "https://hecavex.com/"];
const jsonFeedVersion = "https://jsonfeed.org/version/1.1";
const changesPrivacy = "Aggregate counters only; signal-level history remains in history.json.";
// hecavex_radar.passive_context DNS_REFERENCE, RDAP_REFERENCE and URLSCAN_REFERENCE.
const contextReferences = ["https://cloudflare-dns.com/dns-query", "https://data.iana.org/rdap/dns.json", "https://urlscan.io/"];
const stixSpecification = "https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html";

const atomFeed = /^(?:brands\/[a-z0-9-]+\/)?events\.atom\.xml$/u;
const rssFeed = /^(?:brands\/[a-z0-9-]+\/)?events\.rss\.xml$/u;
const jsonFeed = /^(?:brands\/[a-z0-9-]+\/)?events\.feed\.json$/u;
const snapshot = /^(?:radar\.json|radar-shards\/\d{4}\.json)$/u;
const schema = /^schemas\/[a-z0-9-]+\.schema\.json$/u;

// [file relative to the data root, field path, value check]. Every entry exists
// in the current writers; keep it exact rather than allowing whole files.
export const rawFieldAllowlist = [
  [atomFeed, /^feed@xmlns$/u, exact("http://www.w3.org/2005/Atom")],
  [atomFeed, /^feed(?:>entry)?>link@href$/u, ownOrigin],
  [rssFeed, /^rss>channel(?:>item)?>link#text$/u, ownOrigin],
  [jsonFeed, /^\$\.(?:home_page_url|feed_url|items\[\]\.url)$/u, ownOrigin],
  [jsonFeed, /^\$\.version$/u, exact(jsonFeedVersion)],
  [/^brand-feeds\.json$/u, /^\$\.brands\[\]\.(?:atom|rss|jsonFeed)$/u, ownDataPath],
  [/^feed-manifest\.json$/u, /^\$\.artifacts\[\]\.path$/u, ownDataPath],
  [/^feed-manifest\.json$/u, /^\$\.artifacts\[\]\.schema$/u, (value) => ownOrigin(value) || value === stixSpecification],
  [/^radar\.index\.json$/u, /^\$\.shards\[\]\.path$/u, ownDataPath],
  [/^(?:history|observed-hostnames-v1)\.json$/u, /^\$\.partitions\[\]\.path$/u, partPath],
  [/^radar\.json$/u, /^\$\.sources\[\]\.homepage$/u, exact(...sourceHomepages)],
  [snapshot, /^\$\.signals\[\]\.referenceUrl$/u, urlscanReport],
  [snapshot, /^\$\.signals\[\]\.screenshotUrl$/u, urlscanScreenshot],
  [/^signals\/[a-f\d]{2}\/[a-f\d]{20}\.json$/u, /^\$\.contextChanges\[\]\.source\.referenceUrl$/u, (value) => contextReferences.includes(value) || urlscanReport(value)],
  [/^radar\.stix\.json$/u, /^\$\.objects\[\]\.external_references\[\]\.url$/u, urlscanReport],
  [/^radar\.stix\.json$/u, /^\$\.objects\[\]\.value$/u, typed("domain-name")],
  [/^radar-reviewed\.stix\.json$/u, /^\$\.objects\[\]\.(?:name|pattern)$/u, typed("indicator")],
  [new RegExp(`^misp/${uuid}\\.json$`, "u"), /^\$\.Event\.Attribute\[\]\.value$/u, typed("domain")],
  [/^misp-warninglists\/hecavex-official-domains\/list\.json$/u, /^\$\.list\[\]$/u, any],
  [/^pipeline-health\.json$/u, /\.ctSearch\.provider$/u, exact("crt.sh")],
  [/^changes\.json$/u, /^\$\.privacy$/u, exact(changesPrivacy)],
  [schema, /\.\$schema$/u, exact("https://json-schema.org/draft/2020-12/schema")],
  [schema, /\.\$id$/u, ownOrigin],
  [schema, /\.pattern$/u, any],
  [schema, /\.const$/u, exact(jsonFeedVersion, "crt.sh", changesPrivacy, ...sourceHomepages)],
];

const looksFanged = (text) => fangedHost.test(text) || liveUrl.test(text);

function fanged(value, brandNames) {
  if (!/[.:\u3002\uff0e\uff61]/u.test(value) || !looksFanged(value)) return false;
  // Reviewed registry brand names (for example "Skelbiu.lt") are trusted source labels.
  let text = value;
  for (const name of brandNames) text = text.replaceAll(name, " ");
  return looksFanged(text);
}

const defangForLog = (value) => value.slice(0, 120).replace(/[.\u3002\uff0e\uff61]/gu, "[.]").replace(/:\/\//gu, "[:]//");

export function findFangedStrings(dataRoot, brandNames = []) {
  const findings = [];
  const check = (file, path, value, parent) => {
    if (!fanged(value, brandNames)) return;
    if (rawFieldAllowlist.some(([files, fields, allowed]) => files.test(file) && fields.test(path) && allowed(value, parent))) return;
    findings.push(`${file} ${path}: ${defangForLog(value)}`);
  };
  const walkJson = (file, value, path, parent) => {
    if (typeof value === "string") check(file, path, value, parent);
    else if (Array.isArray(value)) for (const item of value) walkJson(file, item, `${path}[]`, value);
    else if (value && typeof value === "object") {
      for (const [key, item] of Object.entries(value)) {
        check(file, `${path}#key`, key, value);
        walkJson(file, item, `${path}.${key}`, value);
      }
    }
  };
  const walkXml = (file, node, path) => {
    for (const attribute of node.attributes ?? []) check(file, `${path}@${attribute.name}`, attribute.value, null);
    for (const child of node.childNodes) {
      if (child.nodeType === child.ELEMENT_NODE) walkXml(file, child, path ? `${path}>${child.localName}` : child.localName);
      else if (child.nodeValue?.trim()) {
        const kind = child.nodeType === child.TEXT_NODE || child.nodeType === child.CDATA_SECTION_NODE ? "text" : "other";
        check(file, `${path}#${kind}`, child.nodeValue, null);
      }
    }
  };
  const parser = new (new JSDOM("").window.DOMParser)();
  const files = readdirSync(dataRoot, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && /\.(?:json|xml)$/u.test(entry.name))
    .map((entry) => join(entry.parentPath, entry.name))
    .sort();
  for (const path of files) {
    const file = relative(dataRoot, path).split(sep).join("/");
    const text = readFileSync(path, "utf8");
    if (file.endsWith(".json")) {
      walkJson(file, JSON.parse(text), "$", null);
    } else {
      const document = parser.parseFromString(text, "text/xml");
      if (document.querySelector("parsererror")) throw new Error(`${file} is not well-formed XML.`);
      walkXml(file, document, "");
    }
  }
  return findings;
}
