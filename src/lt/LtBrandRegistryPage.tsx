import { ExternalLink, Search, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";

import { SiteHeader } from "../components/SiteHeader.tsx";
import { brandEntries, brandPath, brandRegistryReviewedAt, defangDomain } from "../lib/brandRegistry.ts";
import { foldSearchText } from "../lib/searchText.ts";
import { LtFooter } from "./LtFooter.tsx";
import { categoryLt, formatNumberLt } from "./formatLt.ts";

const categories = [...new Set(brandEntries.map((entry) => entry.category))].sort();

export function LtBrandRegistryPage() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const filteredEntries = useMemo(() => {
    const normalizedQuery = foldSearchText(query.trim(), "lt");
    return brandEntries.filter((entry) => {
      const matchesQuery = normalizedQuery.length === 0 || [
        entry.brand,
        entry.category,
        ...entry.aliases,
        ...(entry.fuzzyAliases ?? []),
        ...entry.officialDomains,
      ].some((value) => foldSearchText(value, "lt").includes(normalizedQuery));
      return matchesQuery && (category === "all" || entry.category === category);
    });
  }, [category, query]);
  const officialDomainCount = new Set(brandEntries.flatMap((entry) => entry.officialDomains)).size;

  return (
    <div className="site-shell">
      <SiteHeader currentPage="brands" language="lt" alternateHref="/brands/" />
      <main className="content-page brand-scope-page" id="main-content">
        <section className="brand-scope-heading" aria-labelledby="brand-scope-title">
          <div>
            <p className="eyebrow"><ShieldCheck aria-hidden="true" /> Vieša aptikimo aprėptis</p>
            <h1 id="brand-scope-title">Peržiūrėtas Lietuvos prekių ženklų registras</h1>
          </div>
          <p>
            Radaras lygina sertifikatų vardus ir viešų nuskaitymų duomenis su šiuo ribotos aprėpties
            registru. Įtrauktas prekės ženklas patenka į aptikimo aprėptį, tačiau tai nereiškia, kad jis
            buvo atakuotas ar kad atitinkantis kandidatas savaime yra kenkėjiškas.
          </p>
        </section>

        <section className="brand-scope-metrics" aria-label="Registro suvestinė">
          <div><span>Peržiūrėti prekių ženklai</span><strong>{formatNumberLt(brandEntries.length)}</strong></div>
          <div><span>Oficialūs domenai</span><strong>{formatNumberLt(officialDomainCount)}</strong></div>
          <div><span>Kategorijos</span><strong>{formatNumberLt(categories.length)}</strong></div>
          <div><span>Registro peržiūros data</span><strong>{brandRegistryReviewedAt}</strong></div>
        </section>

        <section className="scope-boundaries" aria-labelledby="scope-boundaries-title">
          <div>
            <p className="eyebrow">Kaip interpretuoti</p>
            <h2 id="scope-boundaries-title">Ką apibrėžia šis registras</h2>
          </div>
          <dl>
            <div><dt>Pavadinimai</dt><dd>Tikslūs pavadinimai ir atskirai įjungti apytiksliai atitikmenys gali lemti kandidato atitiktį tik tada, kai domeno kontekstas tenkina ir kitas aptikimo taisykles.</dd></div>
            <div><dt>Oficialūs domenai</dt><dd>Teisėtos svetainės ir jų subdomenai atmetami prieš skaičiuojant atitikties balą.</dd></div>
            <div><dt>Išimtys</dt><dd>Patikrintos leksinės kolizijos mažina nuspėjamų klaidingai teigiamų rezultatų skaičių, tačiau plačiai neslepia bendros infrastruktūros.</dd></div>
            <div><dt>Šaltiniai</dt><dd>Pirminiai šaltiniai patvirtina prekių ženklo tapatybę ir oficialių domenų aprėptį. Jie nėra kandidato kenkėjiškumo įrodymai.</dd></div>
          </dl>
        </section>

        <section className="brand-registry" aria-labelledby="registry-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Dabartinis registras</p>
              <h2 id="registry-title">Prekių ženklai ir oficialios svetainės</h2>
            </div>
            <p>Rodoma <strong>{formatNumberLt(filteredEntries.length)}</strong> iš {formatNumberLt(brandEntries.length)}</p>
          </div>
          <div className="brand-filter-shell">
            <label>
              <Search aria-hidden="true" />
              <span className="sr-only">Ieškoti prekių ženklų registre</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Ieškoti pagal prekių ženklą, pavadinimą arba oficialų domeną..."
              />
            </label>
            <label>
              <span className="sr-only">Filtruoti registro kategoriją</span>
              <select value={category} onChange={(event) => setCategory(event.target.value)}>
                <option value="all">Visos kategorijos</option>
                {categories.map((value) => <option key={value} value={value}>{categoryLt[value] ?? value}</option>)}
              </select>
            </label>
          </div>
          <div className="brand-table-scroll" role="region" aria-label="Peržiūrėtas prekių ženklų registras" tabIndex={0}>
            <table className="brand-table">
              <thead><tr><th scope="col">Prekių ženklas</th><th scope="col">Tikslūs pavadinimai</th><th scope="col">Apytiksliai atitikmenys</th><th scope="col">Oficialūs domenai</th><th scope="col">Patikrintos išimtys</th><th scope="col">Šaltinis</th></tr></thead>
              <tbody>
                {filteredEntries.map((entry) => (
                  <tr key={entry.brand}>
                    <td><a className="brand-hub-link" href={brandPath(entry.brand, "lt")}>{entry.brand}</a><span>{categoryLt[entry.category] ?? entry.category}</span></td>
                    <td><div className="registry-values">{entry.aliases.map((alias) => <code key={alias}>{alias}</code>)}</div></td>
                    <td>
                      <div className="registry-values fuzzy-aliases">
                        {(entry.fuzzyAliases ?? []).map((alias) => <code key={alias}>{alias}</code>)}
                        {!entry.fuzzyAliases?.length ? <span>Nenaudojama</span> : null}
                      </div>
                    </td>
                    <td><div className="registry-values">{entry.officialDomains.map((domain) => <code key={domain}>{defangDomain(domain)}</code>)}</div></td>
                    <td>
                      <div className="registry-values muted">
                        {[...(entry.excludedTerms ?? []), ...(entry.excludedDomains ?? []).map(defangDomain)].map((value) => <code key={value}>{value}</code>)}
                        {!entry.excludedTerms?.length && !entry.excludedDomains?.length ? <span>Nenurodyta</span> : null}
                      </div>
                    </td>
                    <td>
                      <a href={entry.sources[0]} target="_blank" rel="noreferrer noopener">
                        Pirminis šaltinis <ExternalLink aria-hidden="true" />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filteredEntries.length === 0 ? <p className="registry-empty">Nė vienas registro įrašas neatitinka šios paieškos.</p> : null}
        </section>
      </main>
      <LtFooter />
    </div>
  );
}
