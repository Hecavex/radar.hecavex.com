/* global URL, process */

// Paths, page list and DOM helpers shared by every verify-site surface.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";

import { JSDOM } from "jsdom";

export const root = resolve(import.meta.dirname, "..", "..");
export const output = join(root, "dist");
export const publicOrigin = "https://radar.hecavex.com";
export const analyticsToken = process.env.HECAVEX_ANALYTICS_TOKEN?.trim() ?? "";
export const widths = [320, 360, 390, 768, 1024, 1280, 1440];

export const pages = [
  { path: "/", marker: "Sampled discovery, not continuous monitoring" },
  { path: "/lt/", marker: "Atrankinis aptikimas, o ne nuolatinė stebėsena" },
  { path: "/history/", marker: "Candidate history" },
  { path: "/lt/istorija/", marker: "Kandidatų istorija" },
  { path: "/brands/", marker: "Reviewed Lithuanian brand registry" },
  { path: "/changes/", marker: "What changed" },
  { path: "/lt/pokyciai/", marker: "Kas pasikeitė" },
  { path: "/trends/", marker: "Discovery trends and review quality" },
  { path: "/associations/", marker: "Published associations" },
  { path: "/tools/", marker: "Check your indicators locally" },
  { path: "/dataset/", marker: "Radar dataset distributions" },
  { path: "/lt/tendencijos/", marker: "Aptikimo tendencijos ir peržiūros kokybė" },
  { path: "/lt/sasajos/", marker: "Paskelbtos sąsajos" },
  { path: "/lt/irankiai/", marker: "Patikrinkite indikatorius vietoje" },
  { path: "/lt/duomenys/", marker: "Radaro duomenų rinkiniai" },
  { path: "/methodology/", marker: "How a signal reaches Radar" },
  { path: "/docs/", marker: "HECAVEX Radar technical reference" },
  { path: "/lt/dokumentacija/", marker: "HECAVEX Radaro techninis žinynas" },
  { path: "/404.html", marker: "Page not found" },
];

export function assert(condition, message) {
  if (!condition) throw new Error(message);
}

export function walk(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

export function outputPath(pathname) {
  const decoded = decodeURIComponent(pathname);
  if (decoded.endsWith("/")) return join(output, decoded.slice(1), "index.html");
  return join(output, decoded.slice(1));
}

export function routeForFile(path) {
  const normalized = relative(output, path).split(sep).join("/");
  if (normalized === "index.html") return "/";
  return `/${normalized.replace(/index\.html$/, "")}`;
}

export function parseFile(path) {
  return new JSDOM(readFileSync(path, "utf8"), { url: new URL(routeForFile(path), publicOrigin) }).window.document;
}

let releasedDocumentCount = 0;

export function releaseDocument(document) {
  document.defaultView?.close();
  releasedDocumentCount += 1;
}

export function collectReleasedDocuments() {
  if (releasedDocumentCount % 8 === 0) globalThis.gc?.();
}
