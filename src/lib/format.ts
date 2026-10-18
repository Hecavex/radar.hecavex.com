const relativeFormatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function formatDateTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "Unknown time";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(timestamp);
}

export function formatRelativeTime(value: string, now = Date.now()): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "Unknown time";
  const difference = timestamp - now;
  const absolute = Math.abs(difference);
  if (absolute < 60_000) return "just now";
  if (absolute < 3_600_000) return relativeFormatter.format(Math.round(difference / 60_000), "minute");
  if (absolute < 86_400_000) return relativeFormatter.format(Math.round(difference / 3_600_000), "hour");
  return relativeFormatter.format(Math.round(difference / 86_400_000), "day");
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-GB", { notation: "compact" }).format(value);
}

export function sentenceCase(value: string): string {
  return value.length > 0 ? value[0].toUpperCase() + value.slice(1) : value;
}

const pluralRules = { en: new Intl.PluralRules("en"), lt: new Intl.PluralRules("lt") };

/** Picks the CLDR plural form; Lithuanian needs one/few/other (e.g. 1 stebėjimas, 2 stebėjimai, 10 stebėjimų). */
export function pluralize(count: number, language: "en" | "lt", forms: Partial<Record<Intl.LDMLPluralRule, string>> & { other: string }): string {
  return forms[pluralRules[language].select(count)] ?? forms.other;
}
