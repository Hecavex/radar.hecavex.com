import { ExternalLink, Search, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";

import { SiteFooter } from "./components/SiteFooter.tsx";
import { SiteHeader } from "./components/SiteHeader.tsx";
import { brandEntries as entries, brandPath, brandRegistryReviewedAt, defangDomain } from "./lib/brandRegistry.ts";
import { foldSearchText } from "./lib/searchText.ts";
// Keep prerendering deterministic across Node and browser ICU implementations.
const categories = [...new Set(entries.map((entry) => entry.category))].sort();

export function BrandScopePage() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const filteredEntries = useMemo(() => {
    const normalizedQuery = foldSearchText(query.trim());
    return entries.filter((entry) => {
      const matchesQuery = normalizedQuery.length === 0 || [
        entry.brand,
        entry.category,
        ...entry.aliases,
        ...(entry.fuzzyAliases ?? []),
        ...entry.officialDomains,
      ].some((value) => foldSearchText(value).includes(normalizedQuery));
      return matchesQuery && (category === "all" || entry.category === category);
    });
  }, [category, query]);
  const officialDomainCount = new Set(entries.flatMap((entry) => entry.officialDomains)).size;

  return (
    <div className="site-shell">
      <SiteHeader currentPage="brands" />
      <main className="content-page brand-scope-page" id="main-content">
        <section className="brand-scope-heading" aria-labelledby="brand-scope-title">
          <div>
            <p className="eyebrow"><ShieldCheck aria-hidden="true" /> Public detection scope</p>
            <h1 id="brand-scope-title">Reviewed Lithuanian brand registry</h1>
          </div>
          <p>
            Radar screens certificate names and public scan records against this bounded registry. Inclusion means a
            brand is in detection scope. It does not mean the brand has been attacked, and a matching candidate is not
            automatically malicious.
          </p>
        </section>

        <section className="brand-scope-metrics" aria-label="Registry summary">
          <div><span>Reviewed brands</span><strong>{entries.length}</strong></div>
          <div><span>Official domains</span><strong>{officialDomainCount}</strong></div>
          <div><span>Categories</span><strong>{categories.length}</strong></div>
          <div><span>Registry reviewed</span><strong>{brandRegistryReviewedAt}</strong></div>
        </section>

        <section className="scope-boundaries" aria-labelledby="scope-boundaries-title">
          <div>
            <p className="eyebrow">Interpretation</p>
            <h2 id="scope-boundaries-title">What this registry controls</h2>
          </div>
          <dl>
            <div><dt>Aliases</dt><dd>Exact aliases and separately enabled fuzzy aliases may start a candidate match only when the surrounding hostname also satisfies the detection rules.</dd></div>
            <div><dt>Official domains</dt><dd>Legitimate properties and their subdomains are suppressed before scoring.</dd></div>
            <div><dt>Exclusions</dt><dd>Demonstrated lexical collisions reduce predictable false positives without broadly hiding shared infrastructure.</dd></div>
            <div><dt>Sources</dt><dd>First-party references support brand identity and official-domain coverage. They are not evidence against a candidate.</dd></div>
          </dl>
        </section>

        <section className="brand-registry" aria-labelledby="registry-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Current registry</p>
              <h2 id="registry-title">Brands and official properties</h2>
            </div>
            <p>Showing <strong>{filteredEntries.length}</strong> of {entries.length} brands</p>
          </div>
          <div className="brand-filter-shell">
            <label>
              <Search aria-hidden="true" />
              <span className="sr-only">Search brand registry</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search brand, exact or fuzzy alias, or official domain..."
              />
            </label>
            <label>
              <span className="sr-only">Filter registry category</span>
              <select value={category} onChange={(event) => setCategory(event.target.value)}>
                <option value="all">All categories</option>
                {categories.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          </div>
          <div className="brand-table-scroll" role="region" aria-label="Reviewed brand registry" tabIndex={0}>
            <table className="brand-table">
              <thead><tr><th scope="col">Brand</th><th scope="col">Exact aliases</th><th scope="col">Fuzzy aliases</th><th scope="col">Official domains</th><th scope="col">Reviewed exclusions</th><th scope="col">Reference</th></tr></thead>
              <tbody>
                {filteredEntries.map((entry) => (
                  <tr key={entry.brand}>
                    <td><a className="brand-hub-link" href={brandPath(entry.brand)}>{entry.brand}</a><span>{entry.category}</span></td>
                    <td><div className="registry-values">{entry.aliases.map((alias) => <code key={alias}>{alias}</code>)}</div></td>
                    <td>
                      <div className="registry-values fuzzy-aliases">
                        {(entry.fuzzyAliases ?? []).map((alias) => <code key={alias}>{alias}</code>)}
                        {!entry.fuzzyAliases?.length ? <span>Not enabled</span> : null}
                      </div>
                    </td>
                    <td><div className="registry-values">{entry.officialDomains.map((domain) => <code key={domain}>{defangDomain(domain)}</code>)}</div></td>
                    <td>
                      <div className="registry-values muted">
                        {[...(entry.excludedTerms ?? []), ...(entry.excludedDomains ?? []).map(defangDomain)].map((value) => <code key={value}>{value}</code>)}
                        {!entry.excludedTerms?.length && !entry.excludedDomains?.length ? <span>None recorded</span> : null}
                      </div>
                    </td>
                    <td>
                      <a href={entry.sources[0]} target="_blank" rel="noreferrer noopener">
                        First-party source <ExternalLink aria-hidden="true" />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filteredEntries.length === 0 ? <p className="registry-empty">No registry entry matches this search, so this brand is not in Radar's scope. Brands are added only after review. <a href="mailto:info@hecavex.com?subject=HECAVEX%20Radar%20brand%20scope%20request">Request a brand by email</a>.</p> : null}
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}
