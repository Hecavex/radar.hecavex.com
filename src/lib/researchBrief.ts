import { CORROBORATION_METHODS, DISCOVERY_METHODS, EVIDENCE_TIERS, REVIEW_STATES, SIGNAL_STATUSES } from "../types.ts";
import type { SignalPageData } from "./pageBootstrap.ts";

export const researchBriefCopy = {
  en: {
    title: "Research handoff", intro: "A local summary of this published record, not an assessment or a report submission.",
    preview: "Selectable research brief", copy: "Copy brief", download: "Download plain text", copied: "Brief copied.",
    denied: "Clipboard unavailable. Select the preview text or download it.", downloaded: "Plain-text download prepared.",
    unknown: "Not published / unknown", facts: "PUBLISHED FACTS", provenance: "PROVENANCE", questions: "QUESTIONS — NOT FINDINGS",
    signal: "Signal ID", indicator: "Defanged indicator", domain: "Defanged domain", snapshot: "Snapshot UTC",
    first: "First observed UTC", last: "Last observed UTC", status: "Published status", review: "Published review state",
    tier: "Published evidence tier", discovery: "Discovery methods", corroboration: "Corroboration methods",
    observations: "Published passive observations (up to 20; source / UTC)", report: "Existing public report", record: "Canonical record",
    limits: "LIMITS AND UNKNOWNS", collection: "Exact collector listening windows are not part of this signal record. Observation dates do not prove continuous collection.",
    missing: "Unpublished methods, review states and observations remain unknown; no values are inferred from similarity or a provider report.",
    boundary: "A signal is a research lead, not proof of malicious intent, ownership or attribution. Do not visit the candidate. No request is sent by generating, copying or downloading this brief.",
    prompts: ["Does a current public analyst assessment support or contradict this lead?", "Do existing passive records corroborate the same indicator at the same time?", "Could a legitimate brand reference or shared infrastructure explain the observation?", "What evidence is still missing, and should a factual correction be requested?"],
  },
  lt: {
    title: "Tyrimo perdavimas", intro: "Vietinė šio viešo įrašo santrauka, o ne vertinimas ar pranešimo siuntimas.",
    preview: "Pažymimas tyrimo tekstas", copy: "Kopijuoti tekstą", download: "Atsisiųsti tekstą", copied: "Tekstas nukopijuotas.",
    denied: "Iškarpinė nepasiekiama. Pažymėkite tekstą arba atsisiųskite jį.", downloaded: "Teksto atsisiuntimas paruoštas.",
    unknown: "Nepaskelbta / nežinoma", facts: "PASKELBTI FAKTAI", provenance: "KILMĖ", questions: "KLAUSIMAI — NE IŠVADOS",
    signal: "Signalo ID", indicator: "Neutralizuotas indikatorius", domain: "Neutralizuotas domenas", snapshot: "Suvestinė UTC",
    first: "Pirmas stebėjimas UTC", last: "Paskutinis stebėjimas UTC", status: "Paskelbta būsena", review: "Paskelbta peržiūros būsena",
    tier: "Paskelbta įrodymų pakopa", discovery: "Aptikimo būdai", corroboration: "Papildomo pagrindimo būdai",
    observations: "Paskelbti pasyvūs stebėjimai (iki 20; šaltinis / UTC)", report: "Esama vieša ataskaita", record: "Kanoninis įrašas",
    limits: "RIBOS IR NEŽINOMI DUOMENYS", collection: "Tikslių rinktuvo klausymo langų šiame signalo įraše nėra. Stebėjimų datos neįrodo nuolatinio rinkimo.",
    missing: "Nepaskelbti būdai, peržiūros būsenos ir stebėjimai lieka nežinomi; panašumas ar tiekėjo ataskaita jų nenustato.",
    boundary: "Signalas yra tyrimo kryptis, o ne kenkėjiško ketinimo, nuosavybės ar priskyrimo įrodymas. Kandidato neatidarykite. Rengiant, kopijuojant ar atsisiunčiant šį tekstą užklausos nesiunčiamos.",
    prompts: ["Ar dabartinis viešas analitiko vertinimas pagrindžia ar paneigia šią tyrimo kryptį?", "Ar esami pasyvūs įrašai pagrindžia tą patį indikatorių tuo pačiu metu?", "Ar stebėjimą galėtų paaiškinti teisėta prekės ženklo nuoroda ar bendra infrastruktūra?", "Kokių įrodymų dar trūksta ir ar reikėtų prašyti faktinės pataisos?"],
  },
} as const;

function timestamp(value: unknown, unknown: string): string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString() === value ? value : unknown;
}

function indicator(value: unknown, unknown: string): string {
  if (typeof value !== "string" || !value || value.length > 2048 || /[<>`]/.test(value)
    || [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) return unknown;
  return value.replace(/https?:/gi, (scheme) => scheme.toLowerCase() === "https:" ? "hxxps:" : "hxxp:")
    .replace(/\[\.\]/g, ".").replace(/\./g, "[.]").replace(/@/g, "[@]").replace(/\]\(/g, "]（");
}

function published(value: unknown, allowed: readonly string[], unknown: string): string {
  return typeof value === "string" && allowed.includes(value) ? value : unknown;
}

function methods(value: unknown, allowed: readonly string[], unknown: string): string {
  if (!Array.isArray(value) || value.length === 0 || value.length > allowed.length) return unknown;
  return [...new Set(value.map((item) => published(item, allowed, unknown)))].join(", ");
}

export function safeResearchReference(value: unknown): string | null {
  if (typeof value !== "string" || !/^https:\/\/urlscan\.io\/result\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/$/i.test(value)) return null;
  return value;
}

export function researchBriefFilename(data: SignalPageData): string {
  const id = /^[0-9a-f]{20}$/.test(data.signal.id) ? data.signal.id : "unknown";
  return `radar-research-${id}-${data.language}.txt`;
}

export function buildResearchBrief(data: SignalPageData): string {
  const text = researchBriefCopy[data.language];
  const signal = data.signal;
  const id = /^[0-9a-f]{20}$/.test(signal.id) ? signal.id : null;
  const record = id ? `https://radar.hecavex.com/${data.language === "lt" ? "lt/signalai" : "signals"}/${id}/` : text.unknown;
  const observations = data.detail?.signalId === signal.id ? data.detail.observations.slice(0, 20) : [];
  const lines = observations.map((item) => `- ${published(item.source, ["CertStream", "URLScan"], text.unknown)} / ${timestamp(item.observedAt, text.unknown)}`);
  return [
    text.title, text.intro, "", text.facts,
    `${text.signal}: ${id ?? text.unknown}`,
    `${text.domain}: ${indicator(signal.domain, text.unknown)}`,
    `${text.indicator}: ${indicator(signal.url, text.unknown)}`,
    `${text.snapshot}: ${timestamp(data.generatedAt, text.unknown)}`,
    `${text.first}: ${timestamp(signal.firstSeen, text.unknown)}`,
    `${text.last}: ${timestamp(signal.lastSeen, text.unknown)}`,
    `${text.status}: ${published(signal.status, SIGNAL_STATUSES, text.unknown)}`,
    `${text.review}: ${published(signal.reviewState, REVIEW_STATES, text.unknown)}`,
    `${text.tier}: ${published(signal.evidenceTier, EVIDENCE_TIERS, text.unknown)}`,
    `${text.discovery}: ${methods(signal.discoveredVia, DISCOVERY_METHODS, text.unknown)}`,
    `${text.corroboration}: ${methods(signal.corroboratedBy, CORROBORATION_METHODS, text.unknown)}`,
    "", text.observations, ...(lines.length ? lines : [text.unknown]),
    "", text.provenance, `${text.record}: ${record}`,
    `${text.report}: ${safeResearchReference(signal.referenceUrl) ?? text.unknown}`,
    "", text.limits, text.collection, text.missing, text.boundary,
    "", text.questions, ...text.prompts.map((prompt) => `- ${prompt}`), "",
  ].join("\n");
}
