import type { BrandEntry } from "./brandRegistry.ts";
import type { RelatedObservationEdge, RelatedObservationNode } from "./relatedObservations.ts";
import type { RadarHistorySignal, RadarSignal, SignalDetail } from "../types.ts";

export type PageLanguage = "en" | "lt";

export type SignalPageData = {
  signal: RadarSignal;
  generatedAt: string;
  history: RadarHistorySignal | null;
  detail: SignalDetail | null;
  brand: BrandEntry | null;
  relatedNodes: RelatedObservationNode[];
  relatedEdges: RelatedObservationEdge[];
  language: PageLanguage;
};

export type BrandPageData = {
  brand: BrandEntry;
  generatedAt: string;
  signals: RadarSignal[];
  history: RadarHistorySignal[];
  historyTotal?: number;
  language: PageLanguage;
};

export function encodePageBootstrap(value: SignalPageData | BrandPageData): string {
  return encodeURIComponent(JSON.stringify(value));
}

export function decodeSignalPageBootstrap(value: string): SignalPageData {
  const parsed: unknown = JSON.parse(decodeURIComponent(value));
  if (typeof parsed !== "object" || parsed === null || !("signal" in parsed)) {
    throw new Error("The embedded signal page data is invalid.");
  }
  return parsed as SignalPageData;
}

export function decodeBrandPageBootstrap(value: string): BrandPageData {
  const parsed: unknown = JSON.parse(decodeURIComponent(value));
  if (typeof parsed !== "object" || parsed === null || !("brand" in parsed) || !("signals" in parsed)) {
    throw new Error("The embedded brand page data is invalid.");
  }
  return parsed as BrandPageData;
}
