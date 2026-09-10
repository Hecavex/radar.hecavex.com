import {
  Download,
  ExternalLink,
  FilterX,
  GitCompareArrows,
  Network,
  Search,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  RELATION_EVIDENCE_TYPES,
  loadRelatedObservations,
  type RelatedObservationEdge,
  type RelatedObservationEvidence,
  type RelatedObservationNode,
  type RelatedObservations,
  type RelationEvidenceType,
  type RelationStrength,
} from "../lib/relatedObservations.ts";
import { formatDateTime } from "../lib/format.ts";
import { foldSearchText } from "../lib/searchText.ts";
import { formatDateTimeLt, statusLt } from "../lt/formatLt.ts";
import type { RadarSignal } from "../types.ts";

const PAGE_SIZE = 25;

const evidenceLabels: Record<"en" | "lt", Record<RelationEvidenceType, string>> = {
  en: {
    "primary-html-sha256": "Primary HTML SHA-256",
    "certificate-sha256": "Certificate SHA-256",
    "certificate-san": "Certificate name",
    "redirect-domain": "Redirect destination",
    "ip-address": "Observed IP address",
    asn: "Observed ASN",
    "dns-a": "DNS A answer",
    "dns-aaaa": "DNS AAAA answer",
    "dns-cname": "DNS CNAME answer",
    "dns-ns": "DNS nameserver",
    "dns-mx": "DNS mail exchanger",
  },
  lt: {
    "primary-html-sha256": "Pagrindinio HTML SHA-256",
    "certificate-sha256": "Sertifikato SHA-256",
    "certificate-san": "Sertifikato vardas",
    "redirect-domain": "Peradresavimo paskirties domenas",
    "ip-address": "Stebėtas IP adresas",
    asn: "Stebėtas ASN",
    "dns-a": "DNS A atsakymas",
    "dns-aaaa": "DNS AAAA atsakymas",
    "dns-cname": "DNS CNAME atsakymas",
    "dns-ns": "DNS vardų serveris",
    "dns-mx": "DNS pašto serveris",
  },
};

type ExplorerState =
  | { status: "loading" }
  | { status: "unavailable" }
  | { status: "ready"; artifact: RelatedObservations };

type ExplorerSort = "strength" | "evidence" | "domain" | "cluster";

export type AssociationExplorerProps = {
  signals: readonly RadarSignal[];
  /** Omit to load Radar's public artifact; pass null to render an unavailable state. */
  artifact?: RelatedObservations | null;
  signalHref?: (signalId: string) => string;
  language?: "en" | "lt";
};

function SignalEndpoint({
  node,
  signal,
  signalHref,
  language,
}: {
  node: RelatedObservationNode;
  signal: RadarSignal | undefined;
  signalHref: (signalId: string) => string;
  language: "en" | "lt";
}) {
  const lt = language === "lt";
  return (
    <a className="radar-association-endpoint" href={signalHref(node.signalId)}>
      <code>{node.domain}</code>
      <span>{signal?.brand ?? (lt ? "Dabartinio įrašo nėra" : "Current row unavailable")}</span>
      <small>{signal ? `${lt ? statusLt[signal.status] : signal.status} · ${lt ? "balas" : "score"} ${signal.matchScore ?? signal.confidence ?? 0}/100` : `${lt ? "Signalas" : "Signal"} ${node.signalId}`}</small>
      <ExternalLink aria-hidden="true" />
    </a>
  );
}

function EvidenceList({ evidence, language }: { evidence: RelatedObservationEvidence[]; language: "en" | "lt" }) {
  return (
    <ul className="radar-association-evidence" aria-label={language === "lt" ? "Šios poros bendri įrodymai" : "Evidence shared by this pair"}>
      {evidence.map((item) => (
        <li key={`${item.type}:${item.value}`}>
          <span>{evidenceLabels[language][item.type]}</span>
          <code title={item.value}>{item.value}</code>
        </li>
      ))}
    </ul>
  );
}

function edgeStrengthRank(edge: RelatedObservationEdge): number {
  return edge.strength === "strong" ? 0 : 1;
}

export function AssociationExplorer({
  signals,
  artifact,
  signalHref = (signalId) => `/signals/${signalId}/`,
  language = "en",
}: AssociationExplorerProps) {
  const lt = language === "lt";
  const [state, setState] = useState<ExplorerState>(() => artifact === undefined
    ? { status: "loading" }
    : artifact === null
      ? { status: "unavailable" }
      : { status: "ready", artifact });
  const [query, setQuery] = useState("");
  const [evidenceType, setEvidenceType] = useState<RelationEvidenceType | "all">("all");
  const [strength, setStrength] = useState<RelationStrength | "all">("all");
  const [brand, setBrand] = useState("all");
  const [cluster, setCluster] = useState("all");
  const [sort, setSort] = useState<ExplorerSort>("strength");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (artifact !== undefined) {
      setState(artifact === null ? { status: "unavailable" } : { status: "ready", artifact });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    void loadRelatedObservations(controller.signal).then((loaded) => {
      if (!controller.signal.aborted) setState(loaded ? { status: "ready", artifact: loaded } : { status: "unavailable" });
    });
    return () => controller.abort();
  }, [artifact]);

  const activeArtifact = state.status === "ready" ? state.artifact : null;
  const signalsById = useMemo(() => new Map(signals.map((signal) => [signal.id, signal])), [signals]);
  const nodesById = useMemo(
    () => new Map((activeArtifact?.nodes ?? []).map((node) => [node.signalId, node])),
    [activeArtifact],
  );

  const evidenceCounts = useMemo(() => {
    const counts = new Map<RelationEvidenceType, number>(RELATION_EVIDENCE_TYPES.map((type) => [type, 0]));
    for (const edge of activeArtifact?.edges ?? []) {
      for (const type of new Set(edge.evidence.map((item) => item.type))) {
        counts.set(type, (counts.get(type) ?? 0) + 1);
      }
    }
    return counts;
  }, [activeArtifact]);

  const brandOptions = useMemo(() => {
    const values = new Set<string>();
    for (const node of activeArtifact?.nodes ?? []) {
      const value = signalsById.get(node.signalId)?.brand;
      if (value) values.add(value);
    }
    return [...values].sort((left, right) => left.localeCompare(right));
  }, [activeArtifact, signalsById]);

  const clusterOptions = useMemo(() => {
    const nodeCounts = new Map<string, number>();
    for (const node of activeArtifact?.nodes ?? []) nodeCounts.set(node.clusterId, (nodeCounts.get(node.clusterId) ?? 0) + 1);
    return [...nodeCounts].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
  }, [activeArtifact]);

  const filteredEdges = useMemo(() => {
    const needle = foldSearchText(query.trim(), language);
    const edges = (activeArtifact?.edges ?? []).filter((edge) => {
      const source = nodesById.get(edge.source);
      const target = nodesById.get(edge.target);
      if (!source || !target) return false;
      const sourceBrand = signalsById.get(edge.source)?.brand ?? "";
      const targetBrand = signalsById.get(edge.target)?.brand ?? "";
      if (strength !== "all" && edge.strength !== strength) return false;
      if (evidenceType !== "all" && !edge.evidence.some((item) => item.type === evidenceType)) return false;
      if (brand !== "all" && sourceBrand !== brand && targetBrand !== brand) return false;
      if (cluster !== "all" && source.clusterId !== cluster) return false;
      if (!needle) return true;
      return [
        source.domain,
        target.domain,
        sourceBrand,
        targetBrand,
        edge.id,
        ...edge.evidence.flatMap((item) => [item.type, evidenceLabels[language][item.type], item.value]),
      ].some((value) => foldSearchText(value, language).includes(needle));
    });

    return edges.sort((left, right) => {
      const leftSource = nodesById.get(left.source);
      const rightSource = nodesById.get(right.source);
      if (sort === "evidence") return right.evidence.length - left.evidence.length || left.id.localeCompare(right.id);
      if (sort === "domain") return (leftSource?.domain ?? "").localeCompare(rightSource?.domain ?? "") || left.id.localeCompare(right.id);
      if (sort === "cluster") return (leftSource?.clusterId ?? "").localeCompare(rightSource?.clusterId ?? "") || left.id.localeCompare(right.id);
      return edgeStrengthRank(left) - edgeStrengthRank(right) || right.evidence.length - left.evidence.length || left.id.localeCompare(right.id);
    });
  }, [activeArtifact, brand, cluster, evidenceType, language, nodesById, query, signalsById, sort, strength]);

  const filteredClusterCount = useMemo(() => new Set(filteredEdges.map((edge) => nodesById.get(edge.source)?.clusterId).filter(Boolean)).size, [filteredEdges, nodesById]);
  const pageCount = Math.max(1, Math.ceil(filteredEdges.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const visibleEdges = filteredEdges.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const hasFilters = Boolean(query) || evidenceType !== "all" || strength !== "all" || brand !== "all" || cluster !== "all" || sort !== "strength";

  const resetFilters = () => {
    setQuery("");
    setEvidenceType("all");
    setStrength("all");
    setBrand("all");
    setCluster("all");
    setSort("strength");
    setPage(1);
  };

  const selectEvidence = (value: RelationEvidenceType | "all") => {
    setEvidenceType(value);
    setPage(1);
  };

  return (
    <section className="radar-tool radar-association-explorer" aria-labelledby="association-explorer-title">
      <header className="radar-tool-heading">
        <div>
          <p className="eyebrow"><Network aria-hidden="true" /> {lt ? "Infrastruktūros sąsajos" : "Infrastructure associations"}</p>
          <h2 id="association-explorer-title">{lt ? "Tyrinėkite bendrus viešus įrodymus" : "Explore shared public evidence"}</h2>
        </div>
        <p>
          {lt
            ? "Peržiūrėkite visas ribotame viešame grafe išsaugotas sąsajas. Filtruokite pagal įrodymus, jų stiprumą, prekių ženklą ar klasterį, nepaversdami techninio sutapimo priskyrimo teiginiu."
            : "Inspect every association retained in the bounded public graph. Filter by evidence, strength, brand, or cluster without turning technical overlap into an attribution claim."}
        </p>
      </header>

      <div className="radar-tool-notice radar-tool-notice--warning" role="note">
        <TriangleAlert aria-hidden="true" />
        <div>
          <strong>{lt ? "Sąsaja nėra priskyrimas" : "Association is not attribution"}</strong>
          <p>
            {lt
              ? "Bendra priegloba, sertifikatai, DNS, peradresavimai ir kodas gali turėti teisėtą arba trečiosios šalies paaiškinimą. Klasteris nenustato kampanijos, operatoriaus, savininko, kenkėjiškos programos šeimos ar grėsmės veikėjo."
              : "Shared hosting, certificates, DNS, redirects, and code can have benign or third-party explanations. A cluster does not identify a campaign, operator, owner, malware family, or threat actor."}
          </p>
        </div>
      </div>

      {state.status === "loading" ? (
        <div className="radar-tool-empty" aria-live="polite">{lt ? "Įkeliamas ribotas sąsajų duomenų rinkinys." : "Loading the bounded association artifact."}</div>
      ) : state.status === "unavailable" ? (
        <div className="radar-tool-empty" role="status">
          {lt ? "Sąsajų duomenys laikinai nepasiekiami. Kandidatų ir istorijos duomenų rinkiniai nepakito." : "Association data is temporarily unavailable. Candidate and history datasets remain unaffected."}
        </div>
      ) : activeArtifact && activeArtifact.edges.length === 0 ? (
        <div className="radar-tool-empty" role="status">
          {lt ? "Nė viena kandidatų pora neatitinka dabartinių bendrų įrodymų skelbimo taisyklių." : "No candidate pair meets the current shared-evidence publication rules."}
        </div>
      ) : activeArtifact ? (
        <>
          <div className="radar-tool-summary radar-association-summary" aria-label={lt ? "Sąsajų duomenų suvestinė" : "Association artifact summary"}>
            <div><span>{lt ? "Paskelbtos poros" : "Published pairs"}</span><strong>{activeArtifact.edges.length}</strong></div>
            <div><span>{lt ? "Susieti signalai" : "Signals linked"}</span><strong>{activeArtifact.nodes.length}</strong></div>
            <div><span>{lt ? "Įrodymų klasteriai" : "Evidence clusters"}</span><strong>{clusterOptions.length}</strong></div>
            <div>
              <span>{lt ? "Sugeneruota" : "Generated"}</span>
              <time dateTime={activeArtifact.generatedAt}>{lt ? `${formatDateTimeLt(activeArtifact.generatedAt)} Lietuvos laiku` : `${formatDateTime(activeArtifact.generatedAt)} UTC`}</time>
            </div>
          </div>

          <div className="radar-association-facets" aria-label={lt ? "Įrodymų rūšys" : "Evidence facets"}>
            <button type="button" className={evidenceType === "all" ? "active" : ""} onClick={() => selectEvidence("all")}>
              <span>{lt ? "Visi įrodymai" : "All evidence"}</span><strong>{activeArtifact.edges.length}</strong>
            </button>
            {RELATION_EVIDENCE_TYPES.filter((type) => (evidenceCounts.get(type) ?? 0) > 0).map((type) => (
              <button type="button" className={evidenceType === type ? "active" : ""} onClick={() => selectEvidence(type)} key={type}>
                <span>{evidenceLabels[language][type]}</span><strong>{evidenceCounts.get(type)}</strong>
              </button>
            ))}
          </div>

          <div className="radar-association-filters">
            <label className="radar-tool-search">
              <span>{lt ? "Ieškoti sąsajų" : "Search associations"}</span>
              <span><Search aria-hidden="true" /><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={lt ? "Domenas, įrodymas, prekių ženklas…" : "Domain, evidence, brand…"} /></span>
            </label>
            <label>
              <span>{lt ? "Įrodymų stiprumas" : "Evidence strength"}</span>
              <select value={strength} onChange={(event) => { setStrength(event.target.value as RelationStrength | "all"); setPage(1); }}>
                <option value="all">{lt ? "Visi stiprumo lygiai" : "All strengths"}</option>
                <option value="strong">{lt ? "Tikslūs stiprūs įrodymai" : "Exact strong evidence"}</option>
                <option value="shared-context">{lt ? "Bendras kontekstas" : "Shared context"}</option>
                <option value="corroborated-supporting">{lt ? "Ankstesnio formato kontekstas" : "Legacy supporting context"}</option>
              </select>
            </label>
            <label>
              <span>{lt ? "Galimas prekių ženklo atitikmuo" : "Potential brand match"}</span>
              <select value={brand} onChange={(event) => { setBrand(event.target.value); setPage(1); }}>
                <option value="all">{lt ? "Visi prekių ženklai" : "All brand matches"}</option>
                {brandOptions.map((value) => <option value={value} key={value}>{value}</option>)}
              </select>
            </label>
            <label>
              <span>{lt ? "Įrodymų klasteris" : "Evidence cluster"}</span>
              <select value={cluster} onChange={(event) => { setCluster(event.target.value); setPage(1); }}>
                <option value="all">{lt ? "Visi klasteriai" : "All clusters"}</option>
                {clusterOptions.map(([value, count]) => <option value={value} key={value}>{value} · {count} {lt ? "signalai" : "signals"}</option>)}
              </select>
            </label>
            <label>
              <span>{lt ? "Rikiavimas" : "Order"}</span>
              <select value={sort} onChange={(event) => { setSort(event.target.value as ExplorerSort); setPage(1); }}>
                <option value="strength">{lt ? "Stipriausi įrodymai" : "Strongest evidence"}</option>
                <option value="evidence">{lt ? "Daugiausia įrodymų" : "Most evidence"}</option>
                <option value="domain">{lt ? "Domenas" : "Domain"}</option>
                <option value="cluster">{lt ? "Klasteris" : "Cluster"}</option>
              </select>
            </label>
            <button type="button" className="radar-tool-button" onClick={resetFilters} disabled={!hasFilters}>
              <FilterX aria-hidden="true" /> {lt ? "Atkurti filtrus" : "Reset filters"}
            </button>
          </div>

          <div className="radar-association-result-heading">
            <p><strong>{filteredEdges.length}</strong> {lt ? "atitinkančios sąsajos" : "matching associations"} · <strong>{filteredClusterCount}</strong> {lt ? "klasteriai" : "clusters"}</p>
            <a href="/data/related-observations.json" download><Download aria-hidden="true" /> {lt ? "Atsisiųsti paskelbtą JSON" : "Download published JSON"}</a>
          </div>

          {visibleEdges.length === 0 ? (
            <div className="radar-tool-empty">{lt ? "Nė viena paskelbta sąsaja neatitinka šių filtrų." : "No published association matches these filters."}</div>
          ) : (
            <ol className="radar-association-list">
              {visibleEdges.map((edge) => {
                const source = nodesById.get(edge.source);
                const target = nodesById.get(edge.target);
                if (!source || !target) return null;
                return (
                  <li key={edge.id}>
                    <div className="radar-association-meta">
                      <span className={`radar-association-strength radar-association-strength--${edge.strength}`}>
                        {edge.strength === "strong" ? (lt ? "Tikslūs stiprūs įrodymai" : "Exact strong evidence") : (lt ? "Bendras kontekstas — nepriklausomumas nenustatytas" : "Shared context — independence not established")}
                      </span>
                      <span>{lt ? "Klasteris" : "Cluster"} {source.clusterId}</span>
                      <span>{edge.evidence.length} {lt ? "įrodymų elementai" : `evidence item${edge.evidence.length === 1 ? "" : "s"}`}</span>
                    </div>
                    <div className="radar-association-pair">
                      <SignalEndpoint node={source} signal={signalsById.get(source.signalId)} signalHref={signalHref} language={language} />
                      <GitCompareArrows aria-hidden="true" />
                      <SignalEndpoint node={target} signal={signalsById.get(target.signalId)} signalHref={signalHref} language={language} />
                    </div>
                    <EvidenceList evidence={edge.evidence} language={language} />
                    {edge.strength !== "strong" ? <p>{lt
                      ? "DNS ir tinklo reikšmės gali priklausyti tai pačiai bendrai paslaugai. Retumas šiame rinkinyje nereiškia retumo internete."
                      : "DNS and network values may come from the same shared service. Rarity in this sample does not establish rarity across the Internet."}</p> : null}
                  </li>
                );
              })}
            </ol>
          )}

          {pageCount > 1 ? (
            <nav className="radar-tool-pagination" aria-label={lt ? "Sąsajų rezultatų puslapiai" : "Association result pages"}>
              <button type="button" onClick={() => setPage(Math.max(1, safePage - 1))} disabled={safePage === 1}>{lt ? "Ankstesnis" : "Previous"}</button>
              <span>{lt ? "Puslapis" : "Page"} {safePage} {lt ? "iš" : "of"} {pageCount}</span>
              <button type="button" onClick={() => setPage(Math.min(pageCount, safePage + 1))} disabled={safePage === pageCount}>{lt ? "Kitas" : "Next"}</button>
            </nav>
          ) : null}

          <footer className="radar-association-boundary">
            <p>{activeArtifact.semantics}</p>
            <span>
              {lt ? "Prieš skelbimą atmesta" : "Suppressed before publication"}: {activeArtifact.suppressedEvidence.highFanoutValues} {lt ? "per dažnai pasikartojančių reikšmių" : "high-fanout values"},
              {" "}{activeArtifact.suppressedEvidence.temporalPairs} {lt ? "vien laiku pagrįstų porų. Viešų briaunų riba" : "temporal pairs. Public edge limit"}:
              {" "}{activeArtifact.suppressedEvidence.edgeLimit}.
            </span>
            <a href={lt ? "/lt/metodologija/#skelbimas" : "/methodology/#publication"}>{lt ? "Skaityti skelbimo ribas" : "Read the publication boundaries"}</a>
          </footer>
        </>
      ) : null}
    </section>
  );
}
