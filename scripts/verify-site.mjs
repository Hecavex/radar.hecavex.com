/* global process */

// Entry point: node --expose-gc scripts/verify-site.mjs [all|static|browser|health|research].
// Each surface lives in scripts/verify-site/; see docs/CODEMAP.md.

import { execFileSync } from "node:child_process";

import { verifyInBrowser } from "./verify-site/browser.mjs";
import { verifyPerformanceBudgets } from "./verify-site/budgets.mjs";
import { verifyBuiltHtml, verifyReportingEvidencePack } from "./verify-site/html.mjs";
import { verifyIdentityArtwork, verifyLayoutSourceContract } from "./verify-site/identity.mjs";
import { assert, pages, root, widths } from "./verify-site/shared.mjs";
import { verifyPublishedDefanging, verifySignalDetails, verifyStixBundle, verifySyndicationFeeds } from "./verify-site/stix.mjs";
import { verifyDeploymentTopology, verifyPythonAutomationLocks } from "./verify-site/topology.mjs";

const verificationPhase = process.argv[2] ?? "all";
assert(["all", "static", "browser", "health", "research"].includes(verificationPhase), `Unknown verification phase: ${verificationPhase}.`);

if (["all", "static"].includes(verificationPhase)) {
  execFileSync(process.execPath, ["--experimental-strip-types", "--test", "scripts/research-brief.test.mjs"], { cwd: root, stdio: "inherit" });
  verifyLayoutSourceContract();
  verifyDeploymentTopology();
  verifyPythonAutomationLocks();
  verifyBuiltHtml();
  verifyIdentityArtwork();
  verifyReportingEvidencePack();
  const signalDetails = verifySignalDetails();
  verifyStixBundle();
  verifySyndicationFeeds();
  verifyPublishedDefanging();
  const performance = verifyPerformanceBudgets(signalDetails);
  process.stdout.write(
    `Measured production sizes: ${performance.totalBytes} bytes total; ` +
      `${performance.html.path} ${performance.html.size} bytes gzip (largest HTML); ` +
      `${performance.javascript.path} ${performance.javascript.size} bytes gzip (largest JavaScript); ` +
      `${performance.stylesheet.path} ${performance.stylesheet.size} bytes gzip (largest stylesheet); ` +
      `${performance.executableBytes} bytes gzip JavaScript/CSS total; ` +
      `${performance.publicData.path} ${performance.publicData.size} bytes gzip (largest public JSON); ` +
      `${performance.signalDetailBytes} bytes across signal-detail sidecars; ` +
      `${performance.capacity.signalHtmlBytes} signal HTML bytes; ` +
      `${performance.capacity.brandHtmlBytes} brand HTML bytes; ` +
      `${performance.capacity.pairedStaticDataHtmlBytes} paired static-data HTML bytes; ` +
      `${performance.capacity.remainingOutputBytes} remaining bytes; ` +
      `${performance.maximumCapacityBytes} bytes maximum deployment capacity.\n`,
  );
}

if (verificationPhase !== "static") {
  await verifyInBrowser(verificationPhase === "health", verificationPhase === "research");
  process.stdout.write(verificationPhase === "research"
    ? "Verified bilingual research handoffs at 320/1440px: selectable preview, keyboard, clipboard denial/success, download and no external requests.\n"
    : verificationPhase === "health"
    ? "Verified bilingual no-request CT backoff telemetry, actual failure counts, timing and mobile accessibility.\n"
    : `Verified ${pages.length} hydratable static pages at ${widths.join(", ")}px with links, fragments, metadata, CSP, delayed-refresh retention, no-JS content, keyboard navigation, overflow, focus, and accessibility checks.\n`);
}
