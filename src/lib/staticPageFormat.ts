import { formatDateTime } from "./format.ts";
import type { StaticPageLanguage } from "../components/ArtifactPageShell.tsx";

export function formatEventDateTime(value: string, language: StaticPageLanguage): string {
  if (language === "en") return formatDateTime(value);
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "Laikas nežinomas";
  return new Intl.DateTimeFormat("lt-LT", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(timestamp);
}
