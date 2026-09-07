import { Code2, Languages, Menu, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

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

const portfolioNavigation = [
  { label: "Research", href: "https://hecavex.com/en/research/", current: false },
  { label: "Radar", href: "/", current: true },
  { label: "APT Notes", href: "https://apt.hecavex.com/", current: false },
  { label: "Labs", href: "https://labs.hecavex.com/", current: false },
  { label: "Data", href: "https://hecavex.com/data/", current: false },
] as const;

const englishNavigation: Array<{ label: string; href: string; pages: SitePage[] }> = [
  { label: "Overview", href: "/", pages: ["radar", "signal"] },
  { label: "Changes", href: "/changes/", pages: ["changes", "history"] },
  { label: "Brands", href: "/brands/", pages: ["brands", "brand"] },
  { label: "Trends", href: "/trends/", pages: ["trends", "quality"] },
  { label: "Associations", href: "/associations/", pages: ["associations"] },
  { label: "Tools", href: "/tools/", pages: ["tools"] },
  { label: "Methodology", href: "/methodology/", pages: ["methodology"] },
  { label: "Docs", href: "/docs/", pages: ["documentation", "dataset"] },
];

const lithuanianNavigation: Array<{ label: string; href: string; pages: SitePage[] }> = [
  { label: "Apžvalga", href: "/lt/", pages: ["radar", "signal"] },
  { label: "Pokyčiai", href: "/lt/pokyciai/", pages: ["changes", "history"] },
  { label: "Prekių ženklai", href: "/lt/prekes-zenklai/", pages: ["brands", "brand"] },
  { label: "Tendencijos", href: "/lt/tendencijos/", pages: ["trends", "quality"] },
  { label: "Sąsajos", href: "/lt/sasajos/", pages: ["associations"] },
  { label: "Įrankiai", href: "/lt/irankiai/", pages: ["tools"] },
  { label: "Metodologija", href: "/lt/metodologija/", pages: ["methodology"] },
  { label: "Dokumentacija", href: "/lt/dokumentacija/", pages: ["documentation", "dataset"] },
];

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
      {portfolioNavigation.map((item) => (
        <a
          key={item.label}
          href={language === "lt" && item.label === "Research" ? "https://hecavex.com/lt/tyrimai/" : item.href}
          aria-current={item.current ? "page" : undefined}
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
  const navigation = language === "lt" ? lithuanianNavigation : englishNavigation;
  return (
    <nav className={className} aria-label={language === "lt" ? "Radaro skyriai" : "Radar sections"}>
      {navigation.map((item) => (
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

function SourceLink({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  return (
    <a
      className={className ? `source-link ${className}` : "source-link"}
      href="https://github.com/Hecavex/radar.hecavex.com"
      target="_blank"
      rel="noreferrer"
      onClick={onNavigate}
    >
      <Code2 aria-hidden="true" />
      Source
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
        <a className="brand" href={researchHref} aria-label="HECAVEX Research">
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
              <SourceLink className="mobile-source-link" onNavigate={closeNavigation} />
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
          <a className="language-link" href={alternateHref ?? defaultAlternate} aria-label={language === "lt" ? "Open English version" : "Atverti lietuvišką versiją"}>
            {language === "lt" ? "EN" : "LT"}
          </a>
          <SourceLink />
        </div>
      </div>
    </header>
  );
}
