// Size budgets: raw data caps, gzip performance budgets and deployment capacity.

import { readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { gzipSync } from "node:zlib";

import { maximumOutputBytes, verifyDeploymentCapacity } from "../deployment-capacity.mjs";
import { assert, output, routeForFile, walk } from "./shared.mjs";

export const stixBundleRawBytes = 2 * 1024 * 1024;
export const signalDetailFileRawBytes = 16 * 1024;
export const signalDetailSetRawBytes = 3 * 1024 * 1024;

const performanceBudgets = {
  htmlGzip: 512 * 1024,
  javascriptFileGzip: 225 * 1024,
  stylesheetFileGzip: 48 * 1024,
  scriptAndStyleGzip: 320 * 1024,
  publicDataFileGzip: 1024 * 1024,
};

export function verifyPerformanceBudgets(signalDetails) {
  const files = walk(output);
  const totalBytes = files.reduce((total, path) => total + statSync(path).size, 0);

  const compressed = (path) => gzipSync(readFileSync(path), { level: 9 }).byteLength;
  const compressedSizes = (paths) => paths.map((path) => ({ path: relative(output, path), size: compressed(path) }));
  const largest = (entries) => entries.reduce((maximum, entry) => (entry.size > maximum.size ? entry : maximum));
  const htmlSizes = compressedSizes(files.filter((candidate) => candidate.endsWith(".html")));
  for (const { path, size } of htmlSizes) {
    assert(size <= performanceBudgets.htmlGzip, `${path} is ${size} gzip bytes; HTML budget is ${performanceBudgets.htmlGzip}.`);
  }
  const scripts = files.filter((candidate) => candidate.endsWith(".js"));
  const styles = files.filter((candidate) => candidate.endsWith(".css"));
  const scriptSizes = compressedSizes(scripts);
  const styleSizes = compressedSizes(styles);
  for (const { path, size } of scriptSizes) {
    assert(size <= performanceBudgets.javascriptFileGzip, `${path} is ${size} gzip bytes; JavaScript file budget is ${performanceBudgets.javascriptFileGzip}.`);
  }
  for (const { path, size } of styleSizes) {
    assert(size <= performanceBudgets.stylesheetFileGzip, `${path} is ${size} gzip bytes; stylesheet budget is ${performanceBudgets.stylesheetFileGzip}.`);
  }
  const executableBytes = [...scriptSizes, ...styleSizes].reduce((total, entry) => total + entry.size, 0);
  assert(
    executableBytes <= performanceBudgets.scriptAndStyleGzip,
    `Scripts and styles total ${executableBytes} gzip bytes; budget is ${performanceBudgets.scriptAndStyleGzip}.`,
  );
  const dataSizes = compressedSizes([
    ...[
      "radar.json",
      "radar.stix.json",
      "history.json",
      "collection-health.json",
      "changes.json",
      "pipeline-health.json",
      "related-observations.json",
      "idn-matches-v1.json",
      "events.json",
      "events.atom.xml",
      "events.rss.xml",
      "events.feed.json",
      "brand-feeds.json",
      "daily-trends.json",
      "quality-metrics.json",
    ].map((name) => join(output, "data", name)),
    ...walk(join(output, "data", "brands")),
    ...signalDetails.files,
  ]);
  for (const { path, size } of dataSizes) {
    const name = path.replace(/^data\//u, "");
    assert(size <= performanceBudgets.publicDataFileGzip, `data/${name} is ${size} gzip bytes; data budget is ${performanceBudgets.publicDataFileGzip}.`);
  }
  const pairedStaticDataRoutes = new Set([
    "/changes/", "/lt/pokyciai/", "/trends/", "/lt/tendencijos/", "/associations/", "/lt/sasajos/",
    "/tools/", "/lt/irankiai/", "/dataset/", "/lt/duomenys/",
  ]);
  const signalHtmlFiles = files.filter((path) => {
    if (!path.endsWith(".html")) return false;
    const route = routeForFile(path);
    return route.startsWith("/signals/") || route.startsWith("/lt/signalai/");
  });
  const brandHtmlFiles = files.filter((path) => {
    if (!path.endsWith(".html")) return false;
    const route = routeForFile(path);
    return (route.startsWith("/brands/") && route !== "/brands/") ||
      (route.startsWith("/lt/prekes-zenklai/") && route !== "/lt/prekes-zenklai/");
  });
  const pairedStaticDataHtmlFiles = files.filter(
    (path) => path.endsWith(".html") && pairedStaticDataRoutes.has(routeForFile(path)),
  );
  const capacityClassifiedFiles = new Set([
    ...signalHtmlFiles,
    ...brandHtmlFiles,
    ...pairedStaticDataHtmlFiles,
  ]);
  const sumRawBytes = (paths) => paths.reduce((total, path) => total + statSync(path).size, 0);
  const capacity = {
    signalHtmlBytes: sumRawBytes(signalHtmlFiles),
    brandHtmlBytes: sumRawBytes(brandHtmlFiles),
    pairedStaticDataHtmlBytes: sumRawBytes(pairedStaticDataHtmlFiles),
    remainingOutputBytes: sumRawBytes(files.filter((path) => !capacityClassifiedFiles.has(path))),
  };
  verifyDeploymentCapacity(totalBytes, capacity);
  return {
    totalBytes,
    html: largest(htmlSizes),
    javascript: largest(scriptSizes),
    stylesheet: largest(styleSizes),
    executableBytes,
    publicData: largest(dataSizes),
    signalDetailBytes: signalDetails.totalBytes,
    capacity,
    maximumCapacityBytes: maximumOutputBytes,
  };
}
