// Deployment topology: workflows, Python locks, crawler policy files and the sitemap route set.

import { readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { JSDOM } from "jsdom";
import { assert, collectReleasedDocuments, output, publicOrigin, releaseDocument, root, routeForFile } from "./shared.mjs";

export function verifyDeploymentTopology() {
  const deploy = readFileSync(join(root, ".github", "workflows", "deploy-pages.yml"), "utf8");
  const ci = readFileSync(join(root, ".github", "workflows", "ci.yml"), "utf8");
  const collector = readFileSync(join(root, ".github", "workflows", "collect-certstream.yml"), "utf8");
  const cadence = readFileSync(join(root, ".github", "workflows", "maintain-certstream-cadence.yml"), "utf8");
  const snapshotCadence = readFileSync(join(root, ".github", "workflows", "maintain-snapshot-cadence.yml"), "utf8");
  const hunter = readFileSync(join(root, ".github", "workflows", "hunt-urlscan.yml"), "utf8");
  const assetHunter = readFileSync(join(root, ".github", "workflows", "hunt-brand-assets.yml"), "utf8");
  const ctSearch = readFileSync(join(root, ".github", "workflows", "poll-ct-search.yml"), "utf8");
  const domainContext = readFileSync(join(root, ".github", "workflows", "enrich-domain-context.yml"), "utf8");
  const healthEvaluator = readFileSync(join(root, ".github", "workflows", "evaluate-pipeline-health.yml"), "utf8");
  const livePublication = readFileSync(join(root, ".github", "workflows", "verify-live-publication.yml"), "utf8");
  const weeklyRelease = readFileSync(join(root, ".github", "workflows", "release-weekly-dataset.yml"), "utf8");
  const sync = readFileSync(join(root, ".github", "workflows", "sync-radar.yml"), "utf8");
  const historyPublisher = readFileSync(join(root, "hecavex_radar", "history.py"), "utf8");
  const snapshotPublisher = readFileSync(join(root, "hecavex_radar", "sync.py"), "utf8");
  const stixPublisher = readFileSync(join(root, "hecavex_radar", "stix.py"), "utf8");
  const viteConfig = readFileSync(join(root, "vite.config.ts"), "utf8");

  assert(
    /workflows:\s*\["CI"\]/u.test(deploy),
    "Pages deployment must follow successful code CI.",
  );
  assert(
    deploy.includes("repository_dispatch:") &&
      deploy.includes("types: [certstream_writer_completed, snapshot_writer_completed]"),
    "Pages deployment no longer accepts the bounded writer-completion event.",
  );
  assert(
    deploy.includes("github.event.workflow_run.name == 'CI'") &&
      !deploy.includes("github.event.workflow_run.name == 'Sync radar snapshot'") &&
      !deploy.includes("github.event.workflow_run.name == 'Collect CertStream candidates'") &&
      deploy.includes("github.event.workflow_run.event == 'push'") &&
      deploy.includes("github.event.client_payload.source_ref == 'main'") &&
      deploy.includes("github.event.client_payload.source_workflow == 'Sync radar snapshot'") &&
      deploy.includes("github.event.client_payload.source_workflow == 'Collect CertStream candidates'") &&
      deploy.includes("github.event.client_payload.source_conclusion == 'success'") &&
      deploy.includes("github.event.client_payload.source_conclusion == 'failure'") &&
      deploy.includes("github.event.client_payload.head_sha"),
    "Pages deployment no longer limits each upstream workflow to its approved trigger semantics.",
  );
  assert(
    deploy.includes("hecavex_radar.data_branch materialize") &&
      deploy.includes("--view operational") &&
      deploy.includes("publication_source_revision") &&
      deploy.includes("hecavex_radar.publication_selection") &&
      deploy.includes("--trigger-data") &&
      deploy.includes("--expected-data-revision") &&
      deploy.includes("Refuse source or data superseded while building") &&
      deploy.includes("test -f dist/404.html") &&
      deploy.includes("test -f dist/data/feed-manifest.json") &&
      deploy.includes("test -f dist/data/radar.stix.json") &&
      deploy.includes("test -f dist/data/pipeline-health.json") &&
      deploy.includes("test -f dist/data/related-observations.json") &&
      deploy.includes("test -f dist/data/schemas/radar-v2.schema.json") &&
      deploy.includes("! grep -Fq 'Allow: /data/radar.stix.json' dist/robots.txt") &&
      !deploy.includes("ref: radar-data"),
    "Pages must bind current trusted source to exact allowlisted data and reject stale selections.",
  );
  assert(!/^\s{2}workflow_dispatch:/mu.test(deploy), "Pages deployment must not bypass CI through manual dispatch.");
  assert(
    weeklyRelease.includes("Check out current trusted release tooling") &&
      weeklyRelease.includes("ref: ${{ github.sha }}") &&
      !weeklyRelease.includes("ref: ${{ inputs.source_sha || github.sha }}") &&
      weeklyRelease.includes("python -m hecavex_radar.release_source") &&
      weeklyRelease.includes('--source-repository "${RELEASE_SOURCE_ROOT}"') &&
      weeklyRelease.includes('"sourceCommit": os.environ["SOURCE_SHA"]') &&
      weeklyRelease.includes('"toolingCommit": os.environ["TRUSTED_TOOLING_SHA"]') &&
      weeklyRelease.includes('--commit "${TRUSTED_TOOLING_SHA}"') &&
      !weeklyRelease.includes('--commit "${SOURCE_SHA}"'),
    "Weekly backfills must execute current trusted tooling against a separate data-only source.",
  );
  assert(!/^\s{2}actions:\s*write\s*$/mu.test(collector), "CertStream collector retains unnecessary actions:write access.");
  assert(!collector.includes("gh workflow run deploy-pages.yml"), "CertStream collector still dispatches a duplicate Pages deployment.");
  assert(
    cadence.includes("repository_dispatch:") &&
      cadence.includes("types: [certstream_writer_completed]") &&
      cadence.includes("actions: write") &&
      cadence.includes("contents: read") &&
      /^ {4}concurrency:\n {6}group: radar-certstream-cadence\n {6}cancel-in-progress: false\n {6}queue: max/mu.test(cadence) &&
      !/^concurrency:/mu.test(cadence) &&
      cadence.includes("environment: radar-certstream-cadence") &&
      cadence.includes("github.event.client_payload.source_workflow == 'Collect CertStream candidates'") &&
      cadence.includes("github.event.client_payload.source_ref == 'main'") &&
      cadence.includes("python -m hecavex_radar.certstream_cadence") &&
      cadence.includes("github.event.workflow_run.conclusion != 'success'") &&
      !cadence.includes("select(.id > $source)") &&
      cadence.includes("/actions/workflows/collect-certstream.yml/dispatches") &&
      cadence.includes("inputs[cadence_relay]=true") &&
      !cadence.includes("contents: write"),
    "CertStream cadence relay permissions, deduplication, or fixed dispatch boundary drifted.",
  );
  assert(
    snapshotCadence.includes("repository_dispatch:") &&
      snapshotCadence.includes("types: [certstream_writer_completed]") &&
      snapshotCadence.includes("github.event.client_payload.source_workflow == 'Collect CertStream candidates'") &&
      snapshotCadence.includes("github.event.client_payload.source_conclusion == 'success'") &&
      snapshotCadence.includes("github.event.client_payload.source_ref == 'main'") &&
      snapshotCadence.includes("actions: write") &&
      snapshotCadence.includes("contents: read") &&
      snapshotCadence.includes("group: radar-snapshot-cadence") &&
      snapshotCadence.includes("cancel-in-progress: true") &&
      snapshotCadence.includes('MINIMUM_SYNC_AGE_SECONDS: "2700"') &&
      snapshotCadence.includes("COLLECTION_OUTCOME: ${{ github.event.client_payload.collection_outcome || 'manual' }}") &&
      snapshotCadence.includes('select(.status != "completed")') &&
      snapshotCadence.includes('select(.status != "completed" and .status != "in_progress")') &&
      snapshotCadence.includes('select(.status == "completed" and .conclusion == "success")') &&
      snapshotCadence.includes('[[ "${active}" -gt 0 && "${COLLECTION_OUTCOME}" != "healthy-matches" ]]') &&
      snapshotCadence.includes('[[ "${COLLECTION_OUTCOME}" == "healthy-matches" && "${queued}" -gt 0 ]]') &&
      snapshotCadence.includes('[[ -n "${latest_success}" && "${COLLECTION_OUTCOME}" != "healthy-matches" ]]') &&
      snapshotCadence.includes("/actions/workflows/sync-radar.yml/dispatches") &&
      !snapshotCadence.includes("contents: write"),
    "Snapshot cadence relay permissions, age gate, or fixed dispatch boundary drifted.",
  );
  assert(
    collector.includes("cadence_relay:") &&
      collector.includes('CERTSTREAM_DUE_TOLERANCE_SECONDS: "300"') &&
      collector.includes("timeout-minutes: 20") &&
      collector.includes("inputs.cadence_relay && 'cadence-relay' || github.event_name") &&
      collector.includes("collection_health begin-if-due") &&
      collector.includes("event_type=certstream_writer_completed") &&
      !collector.includes("event_type=certstream_cadence_checked") &&
      collector.includes("if: always() && steps.cadence.outputs.due == 'true'") &&
      collector.includes("client_payload[collection_outcome]") &&
      collector.includes("client_payload[source_workflow]=Collect CertStream candidates") &&
      collector.includes("client_payload[source_conclusion]") &&
      collector.includes("client_payload[source_run_id]") &&
      collector.includes("client_payload[source_ref]") &&
      collector.includes("client_payload[head_sha]") &&
      collector.includes('client_payload[head_sha]=${SOURCE_SHA}') &&
      sync.includes("event_type=snapshot_writer_completed") &&
      sync.includes("client_payload[source_workflow]=Sync radar snapshot") &&
      sync.includes("client_payload[source_conclusion]") &&
      sync.includes("client_payload[head_sha]") &&
      sync.includes('client_payload[head_sha]=${SOURCE_SHA}'),
    "Writer notification or relay-dispatched schedule telemetry semantics drifted.",
  );
  for (const [workflow, writer] of [[collector, "certstream"], [hunter, "urlscan"], [assetHunter, "brand-assets"]]) {
    assert(workflow.includes(`--writer ${writer}`) && workflow.includes("hecavex_radar.data_branch publish"),
      `${writer} must use the centralized data-only writer boundary.`);
  }
  assert(
    assetHunter.includes('cron: "47 3,15 * * *"') &&
      assetHunter.includes("group: radar-archive-writer") &&
      assetHunter.includes("ref: main") &&
      assetHunter.includes("persist-credentials: false"),
    "Official asset hunter schedule, serialization, or main-branch boundary drifted.",
  );
  assert(
    hunter.includes("group: radar-archive-writer") && sync.includes("group: radar-archive-writer"),
    "URLScan archive and snapshot writers are no longer serialized.",
  );
  for (const [name, workflow] of [
    ["CertStream collection", collector],
    ["URLScan hunt", hunter],
    ["official asset hunt", assetHunter],
    ["checkpointed CT search", ctSearch],
    ["DNS/RDAP context", domainContext],
    ["snapshot synchronization", sync],
  ]) {
    assert(workflow.includes("queue: max"), `${name} no longer retains pending shared-writer runs.`);
  }
  assert(
    healthEvaluator.includes('cron: "11 */2 * * *"') &&
      healthEvaluator.includes("issues: write") &&
      healthEvaluator.includes("python -m hecavex_radar.health_sentinel") &&
      healthEvaluator.includes('TITLE: "Radar pipeline health"') &&
      healthEvaluator.includes("gh issue list --state all") &&
      healthEvaluator.includes("gh issue close"),
    "The deduplicated aggregate pipeline-health issue evaluator drifted.",
  );
  assert(
    livePublication.includes('cron: "37 */2 * * *"') &&
      livePublication.includes("contents: read") &&
      livePublication.includes("issues: write") &&
      !livePublication.includes("contents: write") &&
      livePublication.includes("group: radar-live-publication-health") &&
      livePublication.includes("cancel-in-progress: false") &&
      livePublication.includes("if: github.ref == 'refs/heads/main'") &&
      livePublication.includes("persist-credentials: false") &&
      livePublication.includes("python -m hecavex_radar.live_smoke") &&
      livePublication.includes("--json-output") &&
      livePublication.includes("--markdown-output") &&
      livePublication.includes("--github-output") &&
      livePublication.includes("continue-on-error: true") &&
      livePublication.includes("unhealthy=(true|false)") &&
      livePublication.includes("UNHEALTHY: ${{ steps.smoke.outputs.unhealthy || 'true' }}") &&
      livePublication.includes('LABEL: "radar-live-health"') &&
      livePublication.includes("gh issue list --state all") &&
      livePublication.includes("gh issue close") &&
      livePublication.includes("if: steps.smoke.outputs.unhealthy != 'false'") &&
      livePublication.includes("run: exit 1"),
    "The scheduled live-publication smoke check, durable report, or deduplicated issue reconciliation drifted.",
  );
  assert(
    ctSearch.includes('cron: "43 * * * *"') &&
      ctSearch.includes("group: radar-certstream-writer") &&
      ctSearch.includes("--writer ct-search") &&
      ctSearch.includes("CT_SEARCH_REPLAY_IDS") &&
      ctSearch.includes("CT_SEARCH_REPLAY_ROWS") &&
      ctSearch.includes("if: always()"),
    "Checkpointed CT search schedule, serialization, replay boundary, or durable state publication drifted.",
  );
  assert(
    domainContext.includes('cron: "13 1,7,13,19 * * *"') &&
      domainContext.includes("group: radar-archive-writer") &&
      domainContext.includes("vars.DOMAIN_CONTEXT_RUN_BUDGET_SECONDS") &&
      domainContext.includes("--writer domain-context") &&
      domainContext.includes("if: always()"),
    "DNS/RDAP context schedule, serialization, or durable state publication drifted.",
  );
  for (const [name, workflow] of [["collector", collector], ["URLScan", hunter], ["assets", assetHunter],
    ["CT search", ctSearch], ["domain context", domainContext], ["snapshot", sync]]) {
    assert(workflow.includes("hecavex_radar.data_branch materialize") &&
      workflow.includes("hecavex_radar.data_branch publish") && workflow.includes("--state-file") &&
      workflow.includes("if: github.ref == 'refs/heads/main'") &&
      !workflow.includes("HEAD:main") && !workflow.includes("git rebase"),
      `${name} must publish only through source-owned data transport.`);
  }
  assert(
    ci.includes('- "data/certstream/**"') &&
      ci.includes('- "data/ct-search/**"') &&
      ci.includes('- "data/enrichment/**"') &&
      ci.includes('- "data/urlscan/**"') &&
      !ci.includes('- "public/data/**"'),
    "CI path filters no longer ignore only archive-only collection changes.",
  );
  assert(sync.includes("--writer snapshot") && sync.includes("python -m hecavex_radar.publication") &&
    sync.includes("python -m hecavex_radar.quality_artifacts") &&
    ci.includes("materialize-fixture") && ci.includes("9cd9e14af1dd6046f6fbb88e90775e1c406ae59f"),
    "Atomic publication or immutable isolated source-CI fixture drifted.");
  for (const setting of [
    "RADAR_HISTORY_DETAIL_DAYS",
    "RADAR_HISTORY_SUMMARY_DAYS",
    "RADAR_HISTORY_MAX_SIGNALS",
  ]) {
    assert(sync.includes(`vars.${setting}`), `Snapshot synchronization ignores repository variable ${setting}.`);
  }
  assert(
    snapshotPublisher.includes("MAXIMUM_SNAPSHOT_BYTES = 512 * 1024") &&
      historyPublisher.includes("MAXIMUM_PUBLIC_BYTES = 512 * 1024") &&
      stixPublisher.includes("MAXIMUM_STIX_BUNDLE_BYTES = 2 * 1024 * 1024"),
    "Python public-artifact caps no longer match the bounded-artifact scenario.",
  );
  assert(!viteConfig.includes("Date.now()"), "Vite prerendering still uses a nondeterministic wall-clock timestamp.");
}

function inputPins(path) {
  return readFileSync(path, "utf8")
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .filter((line) => /^[a-z0-9][a-z0-9._-]*==[^\s]+$/iu.test(line));
}

function verifyLock(path, expectedPins) {
  const lock = readFileSync(path, "utf8");
  assert(lock.includes("CPython 3.12 on GitHub Actions Linux x86_64"), `${relative(root, path)} has no target provenance.`);
  assert(!/^--(?:extra-)?index-url\b/mu.test(lock), `${relative(root, path)} must not embed a package index.`);
  for (const pin of expectedPins) {
    assert(lock.includes(`${pin} \\\n`), `${relative(root, path)} does not contain ${pin}.`);
  }

  const requirementStarts = [...lock.matchAll(/^([a-z0-9][a-z0-9._-]*==[^\s]+) \\\n((?:\s+--hash=sha256:[a-f0-9]{64}(?: \\)?\r?\n)+)/gimu)];
  const declared = [...lock.matchAll(/^[a-z0-9][a-z0-9._-]*==[^\s]+/gimu)];
  assert(requirementStarts.length === declared.length, `${relative(root, path)} contains a requirement without SHA-256 hashes.`);
  assert(declared.length >= expectedPins.length, `${relative(root, path)} is missing resolved transitive dependencies.`);
}

export function verifyPythonAutomationLocks() {
  const requirements = join(root, "requirements");
  const runtimeLock = "requirements/automation-runtime-py312.lock";
  const ciLock = "requirements/automation-ci-py312.lock";
  const runtimePins = inputPins(join(requirements, "automation-runtime.in"));
  const ciPins = [...runtimePins, ...inputPins(join(requirements, "automation-ci.in"))];
  const project = readFileSync(join(root, "pyproject.toml"), "utf8");
  const projectPins = [...project.matchAll(/"([a-z0-9][a-z0-9._-]*==[^"\s]+)"/giu)].map((match) => match[1]);
  assert(
    new Set(projectPins).size === new Set(ciPins).size && projectPins.every((pin) => ciPins.includes(pin)),
    "Python automation inputs have drifted from the exact dependencies declared in pyproject.toml.",
  );
  verifyLock(join(root, runtimeLock), runtimePins);
  verifyLock(join(root, ciLock), ciPins);

  const workflowLocks = new Map([
    ["ci.yml", ciLock],
    ["collect-certstream.yml", runtimeLock],
    ["hunt-urlscan.yml", runtimeLock],
    ["hunt-brand-assets.yml", runtimeLock],
    ["poll-ct-search.yml", runtimeLock],
    ["enrich-domain-context.yml", runtimeLock],
    ["sync-radar.yml", runtimeLock],
  ]);
  for (const [name, lock] of workflowLocks) {
    const workflow = readFileSync(join(root, ".github", "workflows", name), "utf8");
    assert(workflow.includes('python-version: "3.12"'), `${name} must run the Python 3.12 lock target.`);
    assert(workflow.includes(`--require-hashes -r ${lock}`), `${name} does not install its reviewed hash lock.`);
    assert(workflow.includes("--no-deps --no-build-isolation"), `${name} can still resolve dependencies outside its lock.`);
    assert(workflow.split(lock).length >= 3, `${name} does not include its lock in both installation and the pip cache key.`);
  }
}

export function verifyCrawlerPolicy() {
  const robots = readFileSync(join(output, "robots.txt"), "utf8");
  const llms = readFileSync(join(output, "llms.txt"), "utf8");
  assert(robots.includes("Content-Signal: search=yes, ai-input=yes, ai-train=no"), "Built robots.txt lost the reviewed content-use signal.");
  assert(!robots.includes("Allow: /data/radar.stix.json"), "Raw STIX observables must not be explicitly allowed for crawler retrieval.");
  for (const endpoint of [
    "radar.json",
    "radar.stix.json",
    "radar-reviewed.stix.json",
    "history.json",
    "collection-health.json",
    "pipeline-health.json",
    "changes.json",
    "related-observations.json",
    "idn-matches-v1.json",
    "events.json",
    "events.atom.xml",
    "events.rss.xml",
    "events.feed.json",
    "brand-feeds.json",
    "daily-trends.json",
    "quality-metrics.json",
    "radar.index.json",
    "feed-manifest.json",
  ]) {
    assert(llms.includes(`https://radar.hecavex.com/data/${endpoint}`), `Built llms.txt omits approved endpoint ${endpoint}.`);
  }
  for (const endpoint of [
    "radar.json",
    "history.json",
    "events.json",
    "brand-feeds.json",
    "daily-trends.json",
    "quality-metrics.json",
  ]) {
    assert(robots.includes(`Allow: /data/${endpoint}`), `Built robots.txt does not allow the intended aggregate endpoint ${endpoint}.`);
  }
  assert(robots.includes("Disallow: /data/radar.stix.json") && robots.includes("Disallow: /data/radar-reviewed.stix.json"), "Built robots.txt no longer excludes raw STIX observables from crawler discovery.");
  assert(llms.includes("must not be made clickable or visited automatically"), "Built llms.txt lost the candidate-handling safety boundary.");
}

export function verifySitemap(htmlFiles) {
  let sitemapDocument = new JSDOM(readFileSync(join(output, "sitemap.xml"), "utf8"), {
    contentType: "text/xml",
  }).window.document;
  assert(!sitemapDocument.querySelector("parsererror"), "Generated sitemap.xml is not valid XML.");
  const sitemapLocations = new Set(
    [...sitemapDocument.querySelectorAll("loc")].map((node) => node.textContent?.trim()).filter(Boolean),
  );
  const expectedLocations = new Set(
    htmlFiles
      .map((path) => routeForFile(path))
      .filter((route) => route !== "/404.html")
      .map((route) => `${publicOrigin}${route}`),
  );
  assert(sitemapLocations.size === expectedLocations.size, "Generated sitemap does not contain exactly the public HTML routes.");
  for (const location of expectedLocations) {
    assert(sitemapLocations.has(location), `Generated sitemap omits ${location}.`);
  }
  assert(!sitemapLocations.has(`${publicOrigin}/404.html`), "Generated sitemap includes the custom 404 page.");
  releaseDocument(sitemapDocument);
  sitemapDocument = null;
  collectReleasedDocuments();
}
