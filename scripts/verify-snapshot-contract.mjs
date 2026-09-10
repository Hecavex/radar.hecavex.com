/* global URL, console, structuredClone */

import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";

import { parseSnapshot } from "../src/lib/data.ts";
import { parseCollectionHealth } from "../src/lib/collectionHealth.ts";
import { trendCollectionState, trendDayState, trendFreshness } from "../src/lib/trendFreshness.ts";

const readJson = async (relative) => JSON.parse(await readFile(new URL(relative, import.meta.url), "utf8"));
const snapshots = [
  ["checked-in live snapshot", await readJson("../public/data/radar.json")],
  ["minimal v2 fixture", await readJson("../tests/fixtures/radar-snapshot-v2-minimal.json")],
];

for (const [label, snapshot] of snapshots) {
  const parsed = parseSnapshot(snapshot);
  if (parsed.schemaVersion !== 2 || parsed.dataset !== "live") {
    throw new Error(`The browser loader did not accept the ${label}.`);
  }
}

for (const unsupportedVersion of [1, 3]) {
  const unsupported = JSON.parse(JSON.stringify(snapshots[1][1]));
  unsupported.schemaVersion = unsupportedVersion;
  let rejected = false;
  try {
    parseSnapshot(unsupported);
  } catch {
    rejected = true;
  }
  if (!rejected) {
    throw new Error(`The browser loader accepted unsupported snapshot schema v${unsupportedVersion}.`);
  }
}

const relayedCollectionHealth = await readJson("../tests/fixtures/collection-health-v1-relayed.json");
const parsedCollectionHealth = parseCollectionHealth(relayedCollectionHealth);
if (
  parsedCollectionHealth.latestAttempt?.trigger !== "cadence-relay" ||
  parsedCollectionHealth.latestAttempt.scheduleStatus !== "relayed"
) {
  throw new Error("The browser loader did not preserve CertStream relay provenance.");
}

const scheduledCollectionHealth = structuredClone(relayedCollectionHealth);
Object.assign(scheduledCollectionHealth.latestAttempt, {
  trigger: "schedule",
  scheduledFor: scheduledCollectionHealth.latestAttempt.startedAt,
  scheduleStatus: "scheduled",
  delaySeconds: 0,
});
parseCollectionHealth(scheduledCollectionHealth);

const invalidCollectionHealth = [
  ["schedule trigger with relay status", { trigger: "schedule", scheduleStatus: "relayed" }],
  ["relay trigger with unknown status", { trigger: "cadence-relay", scheduleStatus: "unknown" }],
  ["manual trigger with unknown status", { trigger: "manual", scheduleStatus: "unknown" }],
  ["unknown trigger with manual status", { trigger: "unknown", scheduleStatus: "manual" }],
  ["scheduled attempt with an inaccurate delay", {
    trigger: "schedule",
    scheduledFor: scheduledCollectionHealth.latestAttempt.startedAt,
    scheduleStatus: "scheduled",
    delaySeconds: 1,
  }],
];
for (const [label, attemptPatch] of invalidCollectionHealth) {
  const invalid = structuredClone(relayedCollectionHealth);
  Object.assign(invalid.latestAttempt, attemptPatch);
  let rejected = false;
  try {
    parseCollectionHealth(invalid);
  } catch {
    rejected = true;
  }
  if (!rejected) throw new Error(`The browser loader accepted ${label}.`);
}

const historicalTrends = { generatedAt: "2026-09-05T21:14:00.000Z" };
const partialRow = { date: "2026-09-05", partialDay: true };
assert.equal(trendFreshness(historicalTrends, Date.parse("2026-09-05T23:14:00.000Z")), "current");
assert.equal(trendFreshness(historicalTrends, Date.parse("2026-09-05T23:14:00.001Z")), "delayed");
assert.equal(trendFreshness(historicalTrends, Date.parse("2026-09-07T10:00:00.000Z")), "delayed");
assert.equal(trendFreshness({ generatedAt: "invalid" }, Date.now()), "unknown");
assert.equal(trendDayState(partialRow, Date.parse("2026-09-05T23:59:59.999Z")), "partial");
assert.equal(trendDayState(partialRow, Date.parse("2026-09-06T00:00:00.000Z")), "incomplete");
assert.equal(trendDayState({ ...partialRow, partialDay: false }, Date.parse("2026-09-07T10:00:00.000Z")), "complete");

assert.equal(trendCollectionState({ recordedAttempts: 7, scheduledSlots: 96 }), "limited");
assert.equal(trendCollectionState({ recordedAttempts: 37, scheduledSlots: 96 }), "limited");
assert.equal(trendCollectionState({ recordedAttempts: 0, scheduledSlots: 4 }), "not-recorded");
assert.equal(trendCollectionState({ recordedAttempts: 0, scheduledSlots: 0 }), "unavailable");
assert.equal(trendCollectionState({ recordedAttempts: 48, scheduledSlots: 96 }), "recorded");
assert.equal(trendCollectionState({ recordedAttempts: 54, scheduledSlots: 96 }), "recorded");
assert.equal(trendCollectionState({ recordedAttempts: 101, scheduledSlots: 96 }), "recorded");
assert.equal(trendCollectionState({ recordedAttempts: NaN, scheduledSlots: 96 }), "unavailable");

console.log("Validated snapshot compatibility, collection-health provenance, UTC cutoff freshness and explicit collection-gap states.");
