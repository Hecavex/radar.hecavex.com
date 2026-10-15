import type { EvidenceTier, Filters, RadarSignal, RadarSnapshot, ReasonCode } from "../types.ts";
import { foldSearchText } from "./searchText.ts";
import { domainToUnicode } from "./signalComparison.ts";

export const DEFAULT_FILTERS: Filters = {
  query: "",
  status: "all",
  source: "all",
  brand: "all",
  country: "all",
  minimumMatchScore: 0,
  timeRange: "all",
  evidence: "all",
  sort: "last-seen-desc",
};

const CONTROLLED_FILTER_KEYS = ["status", "source", "brand", "country", "score", "time", "evidence", "sort"] as const;
const TIME_RANGES = new Set<Filters["timeRange"]>(["all", "24h", "3d", "7d"]);
const EVIDENCE_FILTERS = new Set<Filters["evidence"]>([
  "all",
  "name-only",
  "corroborated",
  "reviewed",
  "screenshot",
  "urlscan",
  "hashes",
  "certstream-only",
]);
const SORTS = new Set<Filters["sort"]>(["last-seen-desc", "first-seen-desc", "match-score-desc", "brand-asc"]);

export type DashboardLanguage = "en" | "lt";

const REASON_EXPLANATIONS: Record<DashboardLanguage, Record<ReasonCode, string>> = {
  en: {
    "brand-domain-match": "The observed hostname matched a reviewed brand-domain rule.",
    "brand-title-match": "A public page title independently referenced the same brand.",
    "provider-verdict": "A public URLScan result supplied a phishing-related provider assessment.",
    "primary-html-hash-pivot": "The primary HTML hash matched independently observed infrastructure.",
    "brand-exact-token": "The certificate name contained an exact reviewed brand token.",
    "brand-joined-affix": "A reviewed brand token was joined to another hostname term.",
    "brand-split-token": "Separated hostname labels reconstructed a reviewed brand token.",
    "brand-lookalike-edit": "The hostname was within the reviewed edit-distance boundary for the brand.",
    "suspicious-context": "The brand-like term appeared with a reviewed phishing-context word.",
    punycode: "The observed hostname used an internationalized punycode label.",
    "different-tld": "The brand-like hostname used a top-level domain outside the reviewed official set.",
    "multiple-hyphens": "The hostname used repeated separators around brand-like terms.",
    "unicode-confusable": "A UTS #39 comparison skeleton matched a reviewed brand alias.",
    "mixed-script": "The internationalized hostname label mixed Unicode scripts.",
    "restricted-identifier": "The hostname fell outside the conservative reviewed identifier profile.",
    "hecavex-public-export": "A sanitized HECAVEX review export supplied this candidate.",
    "manual-review": "A local analyst review record contributed bounded public provenance.",
    "first-publication": "This is the first retained publication event for the candidate.",
    "source-status-change": "A configured source reported a lifecycle-state change.",
  },
  lt: {
    "brand-domain-match": "Stebėtas domeno vardas atitiko peržiūrėtą prekės ženklo domeno taisyklę.",
    "brand-title-match": "Viešo puslapio antraštėje nepriklausomai paminėtas tas pats prekės ženklas.",
    "provider-verdict": "Viešas URLScan rezultatas pateikė su phishing siejamą paslaugos teikėjo vertinimą.",
    "primary-html-hash-pivot": "Pagrindinio HTML maišos reikšmė sutapo su nepriklausomai stebėta infrastruktūra.",
    "brand-exact-token": "Sertifikato varde buvo tikslus peržiūrėtas prekės ženklo žodis.",
    "brand-joined-affix": "Peržiūrėtas prekės ženklo žodis buvo sujungtas su kitu domeno vardo elementu.",
    "brand-split-token": "Atskiros domeno vardo dalys sudarė peržiūrėtą prekės ženklo žodį.",
    "brand-lookalike-edit": "Domeno vardas pateko į peržiūrėtą prekės ženklo redagavimo atstumo ribą.",
    "suspicious-context": "Į prekės ženklą panašus terminas buvo vartojamas su peržiūrėtu phishing konteksto žodžiu.",
    punycode: "Stebėtame domeno varde naudota tarptautinio domeno Punycode forma.",
    "different-tld": "Į prekės ženklą panašus domenas naudojo aukščiausio lygio domeną už peržiūrėto oficialaus rinkinio ribų.",
    "multiple-hyphens": "Domeno varde aplink į prekės ženklą panašius terminus pakartotinai naudoti brūkšneliai.",
    "unicode-confusable": "UTS #39 palyginimo forma sutapo su peržiūrėtu prekės ženklo pavadinimu.",
    "mixed-script": "Tarptautinio domeno vardo dalyje sumaišytos skirtingos Unicode rašto sistemos.",
    "restricted-identifier": "Domeno vardas nepateko į konservatyvų peržiūrėtų identifikatorių profilį.",
    "hecavex-public-export": "Šį kandidatą pateikė išvalytas viešas HECAVEX peržiūros eksportas.",
    "manual-review": "Ribotą viešą kilmės informaciją papildė vietinis analitiko peržiūros įrašas.",
    "first-publication": "Tai pirmasis išsaugotas kandidato paskelbimo įvykis.",
    "source-status-change": "Sukonfigūruotas šaltinis pranešė apie gyvavimo ciklo būsenos pasikeitimą.",
  },
};

const EVIDENCE_TIER_LABELS: Record<DashboardLanguage, Record<EvidenceTier, string>> = {
  en: { "name-only": "Observed", corroborated: "Corroborated", reviewed: "Reviewed" },
  lt: { "name-only": "Stebėta", corroborated: "Patvirtinta papildomu šaltiniu", reviewed: "Peržiūrėta" },
};

function includes(value: string | null, query: string): boolean {
  return value ? foldSearchText(value).includes(query) : false;
}

function validChoice<Value extends string>(value: string | null, choices: ReadonlySet<Value>, fallback: Value): Value {
  return value && choices.has(value as Value) ? value as Value : fallback;
}

export function signalMatchScore(signal: RadarSignal): number {
  return signal.matchScore ?? signal.confidence ?? 0;
}

export function signalEvidenceTier(signal: RadarSignal): EvidenceTier {
  if (signal.evidenceTier) return signal.evidenceTier;
  if (signal.reviewState === "confirmed-suspicious") return "reviewed";
  const reasonCodes = signal.reasonCodes ?? [];
  const corroborated =
    signal.sources.length > 1 ||
    Boolean(signal.referenceUrl || signal.screenshotUrl || signal.hashes?.length) ||
    reasonCodes.some((reason) =>
      reason === "brand-title-match" || reason === "provider-verdict" || reason === "primary-html-hash-pivot",
    );
  return corroborated ? "corroborated" : "name-only";
}

export function evidenceTierLabel(tier: EvidenceTier, language: DashboardLanguage = "en"): string {
  return EVIDENCE_TIER_LABELS[language][tier];
}

export function explainReasons(signal: RadarSignal, language: DashboardLanguage = "en"): string[] {
  return (signal.reasonCodes ?? []).map((reason) => REASON_EXPLANATIONS[language][reason]);
}

function cutoffForRange(range: Filters["timeRange"], now: number): number | null {
  const durations: Record<Exclude<Filters["timeRange"], "all">, number> = {
    "24h": 24 * 60 * 60 * 1000,
    "3d": 3 * 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
  };
  return range === "all" ? null : now - durations[range];
}

function matchesEvidence(signal: RadarSignal, evidence: Filters["evidence"]): boolean {
  if (evidence === "all") return true;
  if (evidence === "screenshot") return Boolean(signal.screenshotUrl);
  if (evidence === "urlscan") return signal.sources.includes("URLScan") || Boolean(signal.referenceUrl);
  if (evidence === "hashes") return Boolean(signal.hashes?.length);
  if (evidence === "certstream-only") return signal.sources.length === 1 && signal.sources[0] === "CertStream";
  return signalEvidenceTier(signal) === evidence;
}

export function filterSignals(signals: RadarSignal[], filters: Filters, now = Date.now()): RadarSignal[] {
  const query = foldSearchText(filters.query.trim());
  const cutoff = cutoffForRange(filters.timeRange, now);
  return signals.filter((signal) => {
    const unicodeDomain = domainToUnicode(signal.domain);
    const queryMatches =
      query.length === 0 ||
      includes(signal.url, query) ||
      includes(signal.domain, query) ||
      includes(signal.domain.replaceAll("[.]", "."), query) ||
      includes(unicodeDomain, query) ||
      includes(unicodeDomain.replaceAll(".", "[.]"), query) ||
      includes(signal.brand, query) ||
      includes(signal.country, query) ||
      includes(signal.host, query) ||
      signal.sources.some((source) => foldSearchText(source).includes(query));

    return (
      queryMatches &&
      (filters.status === "all" || signal.status === filters.status) &&
      (filters.source === "all" || signal.sources.includes(filters.source)) &&
      (filters.brand === "all" || signal.brand === filters.brand) &&
      (filters.country === "all" || signal.country === filters.country) &&
      signalMatchScore(signal) >= filters.minimumMatchScore &&
      (cutoff === null || Date.parse(signal.lastSeen) >= cutoff) &&
      matchesEvidence(signal, filters.evidence)
    );
  });
}

export function sortSignals(signals: RadarSignal[], sort: Filters["sort"]): RadarSignal[] {
  return [...signals].sort((left, right) => {
    if (sort === "first-seen-desc") return Date.parse(right.firstSeen) - Date.parse(left.firstSeen) || left.id.localeCompare(right.id);
    if (sort === "match-score-desc") {
      return signalMatchScore(right) - signalMatchScore(left) || Date.parse(right.lastSeen) - Date.parse(left.lastSeen) || left.id.localeCompare(right.id);
    }
    if (sort === "brand-asc") {
      return (left.brand ?? "~").localeCompare(right.brand ?? "~") || Date.parse(right.lastSeen) - Date.parse(left.lastSeen) || left.id.localeCompare(right.id);
    }
    return Date.parse(right.lastSeen) - Date.parse(left.lastSeen) || left.id.localeCompare(right.id);
  });
}

export function filtersFromSearch(search: string, signals: RadarSignal[]): Filters {
  const parameters = new URLSearchParams(search);
  const statuses = new Set<Filters["status"]>(["all", "active", "suspected", "offline", "mitigated", "unknown"]);
  const sources = new Set(["all", ...sourceNames(signals)]);
  const brands = new Set(["all", ...uniqueValues(signals, "brand")]);
  const countries = new Set(["all", ...uniqueValues(signals, "country")]);
  const numericScore = Number(parameters.get("score"));
  const minimumMatchScore = [0, 50, 75, 90].includes(numericScore) ? numericScore : 0;

  return {
    ...DEFAULT_FILTERS,
    status: validChoice(parameters.get("status"), statuses, "all"),
    source: validChoice(parameters.get("source"), sources, "all"),
    brand: validChoice(parameters.get("brand"), brands, "all"),
    country: validChoice(parameters.get("country"), countries, "all"),
    minimumMatchScore,
    timeRange: validChoice(parameters.get("time"), TIME_RANGES, "all"),
    evidence: validChoice(parameters.get("evidence"), EVIDENCE_FILTERS, "all"),
    sort: validChoice(parameters.get("sort"), SORTS, "last-seen-desc"),
  };
}

export function controlledFilterSearch(filters: Filters): string {
  const parameters = new URLSearchParams();
  if (filters.status !== "all") parameters.set("status", filters.status);
  if (filters.source !== "all") parameters.set("source", filters.source);
  if (filters.brand !== "all") parameters.set("brand", filters.brand);
  if (filters.country !== "all") parameters.set("country", filters.country);
  if (filters.minimumMatchScore > 0) parameters.set("score", String(filters.minimumMatchScore));
  if (filters.timeRange !== "all") parameters.set("time", filters.timeRange);
  if (filters.evidence !== "all") parameters.set("evidence", filters.evidence);
  if (filters.sort !== "last-seen-desc") parameters.set("sort", filters.sort);
  return parameters.toString();
}

export function hasControlledFilters(search: string): boolean {
  const parameters = new URLSearchParams(search);
  return CONTROLLED_FILTER_KEYS.some((key) => parameters.has(key));
}

export function uniqueValues(signals: RadarSignal[], key: "brand" | "country"): string[] {
  return [...new Set(signals.map((signal) => signal[key]).filter((value): value is string => Boolean(value)))].sort(
    (left, right) => left.localeCompare(right),
  );
}

export function sourceNames(signals: RadarSignal[]): string[] {
  return [...new Set(signals.flatMap((signal) => signal.sources))].sort((left, right) => left.localeCompare(right));
}

export function dashboardMetrics(snapshot: RadarSnapshot) {
  const { signals } = snapshot;
  return {
    total: signals.length,
    active: signals.filter((signal) => signal.status === "active").length,
    highConfidence: signals.filter((signal) => signalMatchScore(signal) >= 80).length,
    brands: new Set(signals.map((signal) => signal.brand).filter(Boolean)).size,
    countries: new Set(signals.map((signal) => signal.country).filter(Boolean)).size,
  };
}
