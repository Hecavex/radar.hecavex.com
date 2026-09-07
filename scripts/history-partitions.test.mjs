import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { parseHistory, loadHistory } from "../src/lib/historyData.ts";
import { historyPreview, HISTORY_BOOTSTRAP_BYTES } from "../src/lib/historyPreview.ts";

const encoder = new globalThis.TextEncoder();
const digest = (value) => createHash("sha256").update(value).digest("hex");
const timestamp = "2026-09-07T00:00:00.000Z";
const history = {
  schemaVersion: 1, dataset: "history", generatedAt: timestamp,
  detailRetentionDays: 30, summaryRetentionDays: 730,
  signals: Array.from({ length: 5000 }, (_, index) => {
    const domain = `fixture-${index}[.]example`;
    return {
      id: digest(domain).slice(0, 20), domain, brand: "Test fixture",
      firstSeen: timestamp, lastSeen: timestamp, observationCount: 1,
      sources: ["CertStream"], latestStatus: "suspected", reasonCodes: ["first-publication"],
      statusTransitions: [{ eventId: digest(`event-${index}`).slice(0, 32), observedAt: timestamp,
        previousStatus: null, status: "suspected", sources: ["CertStream"], reasonCodes: ["first-publication"] }],
    };
  }),
};

function partitioned() {
  const parts = new Map();
  const partitions = [];
  for (let offset = 0; offset < history.signals.length; offset += 50) {
    const rows = history.signals.slice(offset, offset + 50);
    const bytes = encoder.encode(JSON.stringify(rows));
    const sha256 = digest(bytes);
    const path = `history-parts/${sha256}.json`;
    parts.set(path, bytes);
    partitions.push({ path, sha256, bytes: bytes.length, signals: rows.length });
  }
  return { parts, index: { ...history, schemaVersion: 2, signals: [],
    signalCount: history.signals.length, partitionFormat: "hecavex-history-partitions-v1", partitions } };
}

test("5000 retained records survive the browser parser with finite response and HTML budgets", async () => {
  const { parts, index } = partitioned();
  assert.ok(encoder.encode(JSON.stringify(history)).length > 512 * 1024);
  assert.ok(encoder.encode(JSON.stringify(index)).length < 512 * 1024);
  const parsed = await parseHistory(index, async (path, maximum) => {
    assert.equal(maximum, 256 * 1024);
    assert.ok(parts.get(path).length <= maximum);
    return parts.get(path);
  });
  assert.deepEqual(parsed, history);
  const preview = historyPreview(parsed);
  assert.ok(preview.signals.length >= 25 && preview.signals.length < 5000);
  assert.ok(encoder.encode(JSON.stringify(preview)).length <= HISTORY_BOOTSTRAP_BYTES);
});

test("invalid, missing, duplicate and modified partitions never become an empty history", async () => {
  for (const damage of ["missing", "digest", "duplicate", "escape", "count"]) {
    const { parts, index } = partitioned();
    const first = index.partitions[0];
    if (damage === "missing") parts.delete(first.path);
    if (damage === "digest") parts.set(first.path, encoder.encode("[]"));
    if (damage === "duplicate") index.partitions.push(first);
    if (damage === "escape") first.path = "../private.json";
    if (damage === "count") index.signalCount -= 1;
    await assert.rejects(() => parseHistory(index, async (path) => {
      if (!parts.has(path)) throw new Error("Missing declared part");
      return parts.get(path);
    }));
  }
});

test("history loader fetches only allowlisted same-origin public partitions without indicator queries", async (context) => {
  const { parts, index } = partitioned();
  const paths = [];
  context.mock.method(globalThis, "fetch", async (path, options) => {
    assert.equal(options.credentials, "omit");
    assert.equal(options.referrerPolicy, "no-referrer");
    paths.push(path);
    const bytes = path === "/data/history.json" ? encoder.encode(JSON.stringify(index)) : parts.get(path.slice(6));
    assert.ok(bytes, `Unknown fixture path ${path}`);
    return new globalThis.Response(bytes);
  });
  assert.deepEqual(await loadHistory(), history);
  assert.equal(paths.length, parts.size + 1);
});
