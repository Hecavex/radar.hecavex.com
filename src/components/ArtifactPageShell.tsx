import { Activity } from "lucide-react";
import { SiteFooter } from "./SiteFooter.tsx";
import { SiteHeader } from "./SiteHeader.tsx";
import type { StaticPageKind } from "../lib/staticPageBootstrap.ts";

export type StaticPageLanguage = "en" | "lt";

const staticRoutes: Record<StaticPageKind, Record<StaticPageLanguage, string>> = {
  changes: { en: "/changes/", lt: "/lt/pokyciai/" },
  trends: { en: "/trends/", lt: "/lt/tendencijos/" },
  associations: { en: "/associations/", lt: "/lt/sasajos/" },
  tools: { en: "/tools/", lt: "/lt/irankiai/" },
  dataset: { en: "/dataset/", lt: "/lt/duomenys/" },
};

export function PageShell({ currentPage, language, children }: { currentPage: StaticPageKind; language: StaticPageLanguage; children: React.ReactNode }) {
  const alternateLanguage = language === "lt" ? "en" : "lt";
  return <div className="site-shell"><SiteHeader currentPage={currentPage} language={language} alternateHref={staticRoutes[currentPage][alternateLanguage]} /><main className="content-page intelligence-page" id="main-content">{children}</main><SiteFooter language={language} /></div>;
}

export function ArtifactHero({ eyebrow, title, description, icon: Icon }: { eyebrow: string; title: string; description: string; icon: typeof Activity }) {
  return <header className="artifact-hero"><div><p className="eyebrow"><Icon aria-hidden="true" /> {eyebrow}</p><h1>{title}</h1></div><p>{description}</p></header>;
}
