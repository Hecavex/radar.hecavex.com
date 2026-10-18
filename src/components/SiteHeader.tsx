import { Code2, Languages, Menu, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import navigation from "../lib/navigation.json";

export type SitePage =
  | "radar"
  | "changes"
  | "history"
  | "brands"
  | "trends"
  | "associations"
  | "tools"
  | "quality"
  | "dataset"
  | "methodology"
  | "documentation"
  | "signal"
  | "brand"
  | "not-found";

export type SiteLanguage = "en" | "lt";

const alternateRoutes: Record<SitePage, { en: string; lt: string }> = {
  radar: { en: "/", lt: "/lt/" },
  changes: { en: "/changes/", lt: "/lt/pokyciai/" },
  history: { en: "/history/", lt: "/lt/istorija/" },
  brands: { en: "/brands/", lt: "/lt/prekes-zenklai/" },
  brand: { en: "/brands/", lt: "/lt/prekes-zenklai/" },
  trends: { en: "/trends/", lt: "/lt/tendencijos/" },
  quality: { en: "/trends/", lt: "/lt/tendencijos/" },
  associations: { en: "/associations/", lt: "/lt/sasajos/" },
  tools: { en: "/tools/", lt: "/lt/irankiai/" },
  dataset: { en: "/dataset/", lt: "/lt/duomenys/" },
  methodology: { en: "/methodology/", lt: "/lt/metodologija/" },
  documentation: { en: "/docs/", lt: "/lt/dokumentacija/" },
  signal: { en: "/", lt: "/lt/" },
  "not-found": { en: "/", lt: "/lt/" },
};

function PortfolioNavigation({ className, onNavigate, language }: { className: string; onNavigate?: () => void; language: SiteLanguage }) {
  return (
    <nav className={className} aria-label="HECAVEX projects">
      {navigation.portfolio[language].map((item) => (
        <a
          key={item.href}
          href={item.href}
          aria-current={"current" in item ? "page" : undefined}
          onClick={onNavigate}
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}

function ProductNavigation({ currentPage, className, onNavigate, language }: {
  currentPage: SitePage;
  className: string;
  onNavigate?: () => void;
  language: SiteLanguage;
}) {
  const items = navigation.product[language];
  return (
    <nav className={className} aria-label={language === "lt" ? "Radaro skyriai" : "Radar sections"}>
      {items.map((item) => (
        <a
          key={item.label}
          href={item.href}
          aria-current={item.pages.includes(currentPage) ? "page" : undefined}
          onClick={onNavigate}
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}

function SourceLink({ className, onNavigate, language }: { className?: string; onNavigate?: () => void; language: SiteLanguage }) {
  return (
    <a
      className={className ? `source-link ${className}` : "source-link"}
      href="https://github.com/Hecavex/radar.hecavex.com"
      target="_blank"
      rel="noreferrer"
      onClick={onNavigate}
    >
      <Code2 aria-hidden="true" />
      {navigation.sourceLabel[language]}
    </a>
  );
}

export function SiteHeader({ currentPage, language = "en", alternateHref }: {
  currentPage: SitePage;
  language?: SiteLanguage;
  alternateHref?: string;
}) {
  const navigationRef = useRef<HTMLDetailsElement>(null);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const researchHref = language === "lt" ? "https://hecavex.com/lt/" : "https://hecavex.com/en/";
  const defaultAlternate = language === "lt" ? alternateRoutes[currentPage].en : alternateRoutes[currentPage].lt;

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      const navigation = navigationRef.current;
      if (event.key !== "Escape" || !navigation?.open) return;
      navigation.open = false;
      setNavigationOpen(false);
      navigation.querySelector<HTMLElement>("summary")?.focus({ preventScroll: true });
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, []);

  const closeNavigation = () => {
    if (!navigationRef.current) return;
    navigationRef.current.open = false;
    setNavigationOpen(false);
  };

  return (
    <header className="site-header" data-portfolio-shell="v2">
      <div className="network-bar">
        <a className="brand" href={researchHref}>
          <img src="/hecavex-mark.svg" alt="" width="36" height="36" />
          <span className="brand-copy">
            <strong>HECAVEX</strong>
            <small>{language === "lt" ? "Radaras / vieši grėsmių signalai" : "Radar / public threat signals"}</small>
          </span>
        </a>

        <PortfolioNavigation className="portfolio-navigation" language={language} />

        <details className="mobile-navigation" data-mobile-navigation ref={navigationRef} onToggle={(event) => setNavigationOpen(event.currentTarget.open)}>
          <summary aria-label={language === "lt" ? (navigationOpen ? "Užverti naršymo meniu" : "Atverti naršymo meniu") : (navigationOpen ? "Close navigation menu" : "Open navigation menu")}>
            <Menu className="menu-open-icon" aria-hidden="true" />
            <X className="menu-close-icon" aria-hidden="true" />
            <span>{language === "lt" ? "Meniu" : "Menu"}</span>
          </summary>
          <div className="mobile-navigation-panel">
            <div className="mobile-navigation-column">
              <span className="navigation-label">Radar</span>
              <ProductNavigation currentPage={currentPage} className="mobile-product-navigation" language={language} onNavigate={closeNavigation} />
              <a className="language-link" href={alternateHref ?? defaultAlternate} onClick={closeNavigation}>
                <Languages aria-hidden="true" /> {language === "lt" ? "English" : "Lietuviškai"}
              </a>
              <SourceLink className="mobile-source-link" onNavigate={closeNavigation} language={language} />
            </div>
            <div className="mobile-navigation-column">
              <span className="navigation-label">{language === "lt" ? "HECAVEX tinklas" : "HECAVEX network"}</span>
              <PortfolioNavigation className="mobile-portfolio-navigation" language={language} onNavigate={closeNavigation} />
            </div>
          </div>
        </details>
      </div>

      <div className="product-bar">
        <a className="product-identity" href={language === "lt" ? "/lt/" : "/"}>
          <strong>Radar</strong>
          <span>{language === "lt" ? "Galima phishing infrastruktūra" : "Potential phishing infrastructure"}</span>
        </a>
        <ProductNavigation currentPage={currentPage} className="product-navigation" language={language} />
        <div className="header-utility">
          <a
            className="language-link"
            href={alternateHref ?? defaultAlternate}
            lang={language === "lt" ? "en" : "lt"}
            hrefLang={language === "lt" ? "en" : "lt"}
            aria-label={language === "lt" ? "EN – English version" : "LT – lietuviška versija"}
          >
            {language === "lt" ? "EN" : "LT"}
          </a>
          <SourceLink language={language} />
        </div>
      </div>
    </header>
  );
}
