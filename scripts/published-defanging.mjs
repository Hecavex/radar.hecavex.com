// Fail-closed sweep: every string in every published JSON/XML file must be
// defanged unless it sits in an explicitly allowlisted raw field.
import { readFileSync, readdirSync } from "node:fs";
import { basename, join, relative, sep } from "node:path";
import { JSDOM } from "jsdom";

// Mirrors hecavex_radar.safety.DOMAIN_IN_TEXT (including the 127-label bound that
// keeps matching linear): whatever the defanger would rewrite is fanged. Both are
// held to tests/fixtures/defang-parity.json.
const label = String.raw`[^\x00-\x2f\x3a-\x40\x5b-\x60\x7b-\x7f\s\u3002\uff0e\uff61]`;
const fangedHost = new RegExp(String.raw`(?:${label}(?:${label}|-){0,62}[.\u3002\uff0e\uff61]){1,127}\p{L}(?:${label}|-){1,62}`, "gu");
const liveUrl = /(?<![a-z\d])(?:https?|ftp|wss?):\/\//iu;

export function containsFangedHost(text, brandNames = new Set()) {
  // A reviewed registry brand name (for example "Skelbiu.lt") is allowed only as a whole match.
  for (const match of text.matchAll(fangedHost)) if (!brandNames.has(match[0])) return true;
  return false;
}

const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const dataPath = String.raw`/data/(?:[a-z0-9-]+/)*[a-z0-9-]+(?:\.(?:atom|rss|feed|stix|index|schema))?\.(?:json|xml)`;
const schemaPath = String.raw`^\$(?:\.\$defs\.[\w-]+|\.items|\.properties\.[\w-]+|\.allOf\[\]\.then)*`;
const matches = (pattern) => (value) => pattern.test(value);
const exact = (...values) => (value) => values.includes(value);
const typed = (type, check = () => true) => (value, parent) => parent?.type === type && check(value);
const ownOrigin = matches(new RegExp(String.raw`^https://radar\.hecavex\.com(?:/|/changes/|/brands/[a-z0-9-]+/|/signals/[a-f\d]{20}/|${dataPath})$`, "u"));
const ownDataPath = matches(new RegExp(`^${dataPath}$`, "u"));
const partPath = matches(/^(?:\/data\/)?(?:history|observed-hostnames)-parts\/[a-f\d]{64}\.json$/u);
const bareHostname = matches(/^(?:[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?\.)+(?:[a-z]{2,63}|xn--[a-z\d-]{1,59})$/u);
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
  [/^radar\.stix\.json$/u, /^\$\.objects\[\]\.value$/u, typed("domain-name", bareHostname)],
  [/^radar-reviewed\.stix\.json$/u, /^\$\.objects\[\]\.(?:name|pattern)$/u, typed("indicator")],
  [new RegExp(`^misp/${uuid}\\.json$`, "u"), /^\$\.Event\.Attribute\[\]\.value$/u, typed("domain", bareHostname)],
  [/^misp-warninglists\/hecavex-official-domains\/list\.json$/u, /^\$\.list\[\]$/u, (value, _parent, context) => context.officialDomains.has(value)],
  [/^pipeline-health\.json$/u, /\.ctSearch\.provider$/u, exact("crt.sh")],
  [/^changes\.json$/u, /^\$\.privacy$/u, exact(changesPrivacy)],
  [schema, new RegExp(String.raw`${schemaPath}\.\$schema$`, "u"), exact("https://json-schema.org/draft/2020-12/schema")],
  [schema, new RegExp(String.raw`${schemaPath}\.\$id$`, "u"), ownOrigin],
  [schema, new RegExp(String.raw`${schemaPath}\.pattern$`, "u"), (_value, parent) => [parent?.type].flat().includes("string")],
  [schema, new RegExp(String.raw`${schemaPath}\.const$`, "u"), exact(jsonFeedVersion, "crt.sh", changesPrivacy, ...sourceHomepages)],
];

const defangForLog = (value) => value.slice(0, 120).replace(/[.\u3002\uff0e\uff61]/gu, "[.]").replace(/:\/\//gu, "[:]//");

export function findFangedStrings(dataRoot, { brandNames = [], officialDomains = [] } = {}) {
  const context = { brandNames: new Set(brandNames), officialDomains: new Set(officialDomains) };
  const findings = [];
  const check = (file, path, value, parent) => {
    if (!/[.:\u3002\uff0e\uff61]/u.test(value)) return;
    if (!containsFangedHost(value, context.brandNames) && !liveUrl.test(value)) return;
    if (rawFieldAllowlist.some(([files, fields, allowed]) => files.test(file) && fields.test(path) && allowed(value, parent, context))) return;
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
    for (const attribute of node.attributes ?? []) {
      check(file, `${path}#attribute-name`, attribute.name, null);
      check(file, `${path}@${attribute.name}`, attribute.value, null);
    }
    for (const child of node.childNodes) {
      if (child.nodeType === child.DOCUMENT_TYPE_NODE) {
        findings.push(`${file}: DOCTYPE is not allowed in published XML.`);
      } else if (child.nodeType === child.ELEMENT_NODE) {
        check(file, `${path}#element-name`, child.nodeName, null);
        walkXml(file, child, path ? `${path}>${child.localName}` : child.localName);
      } else if (child.nodeValue?.trim()) {
        const kind = child.nodeType === child.TEXT_NODE || child.nodeType === child.CDATA_SECTION_NODE ? "text" : "other";
        check(file, `${path}#${kind}`, child.nodeValue, null);
      }
    }
  };
  const parser = new (new JSDOM("").window.DOMParser)();
  const files = readdirSync(dataRoot, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => join(entry.parentPath, entry.name))
    .sort();
  for (const path of files) {
    const file = relative(dataRoot, path).split(sep).join("/");
    const text = readFileSync(path, "utf8");
    if (file.endsWith(".json")) {
      walkJson(file, JSON.parse(text), "$", null);
    } else if (file.endsWith(".xml")) {
      const document = parser.parseFromString(text, "text/xml");
      if (document.querySelector("parsererror")) throw new Error(`${file} is not well-formed XML.`);
      walkXml(file, document, "");
    } else if (file.endsWith(".sha256")) {
      // A checksum sidecar holds exactly "<sha256>  <sibling file name>".
      if (!new RegExp(`^[a-f\\d]{64}  ${basename(file, ".sha256").replace(/[.]/gu, "\\.")}\\r?\\n?$`, "u").test(text)) {
        findings.push(`${file}: unexpected checksum sidecar content.`);
      }
    } else {
      findings.push(`${file}: file type is not understood by the defanging sweep.`);
    }
  }
  return findings;
}
