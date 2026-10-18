import { ArrowLeft, BookOpenText, History, Languages, Store } from "lucide-react";

import { SiteFooter } from "./components/SiteFooter.tsx";
import { SiteHeader } from "./components/SiteHeader.tsx";

export function NotFoundPage() {
  return (
    <div className="site-shell">
      <SiteHeader currentPage="not-found" />
      <main className="not-found-page" id="main-content">
        <section className="not-found-hero" aria-labelledby="not-found-title">
          <div className="not-found-copy">
            <p className="eyebrow">404 / Page not found</p>
            <h1 id="not-found-title">Page not found</h1>
            <p>
              The address may be incomplete, mistyped, or tied to a record that is no longer published. Radar does not
              redirect missing pages because an absent page should stay visibly absent.
            </p>
            <div className="hero-actions">
              <a className="hero-action-primary" href="/"><ArrowLeft aria-hidden="true" /> Overview</a>
              <a href="/changes/"><History aria-hidden="true" /> Changes</a>
              <a href="/brands/"><Store aria-hidden="true" /> Brands</a>
            </div>
          </div>
          <aside className="not-found-status" aria-label="Missing route status">
            <strong>404</strong>
            <span>NOT FOUND</span>
            <p>No Radar page exists at this address. A missing page says nothing about any candidate&apos;s status or verdict.</p>
          </aside>
        </section>

        <nav className="not-found-routes" aria-label="Useful Radar routes">
          <a href="/methodology/"><BookOpenText aria-hidden="true" /><span><strong>Methodology</strong><small>How candidates are collected and screened</small></span></a>
          <a href="/lt/"><Languages aria-hidden="true" /><span><strong>Lietuviškai</strong><small>Atverti lietuvišką radaro versiją</small></span></a>
        </nav>
      </main>
      <SiteFooter />
    </div>
  );
}
