import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { randomBytes } from "node:crypto";
import test from "node:test";
import { gzipSync } from "node:zlib";
import { gzipUpperBound, verifyGzipBudget } from "./gzip-budget.mjs";

test("the documented bound covers actual level9 gzip of empty, compressible and random edge-sized inputs", () => {
  for (const size of [0, 1, 255, 256, 127, 16_383, 16_384, 524_287, 524_288, 524_289]) {
    for (const body of [Buffer.alloc(size, 97), randomBytes(size)]) {
      assert.ok(gzipSync(body, { level: 9 }).length <= gzipUpperBound(size), `Bound failed for ${size} bytes`);
    }
  }
});

test("small HTML is proved without pretending its gzip size was measured", () => {
  const result = verifyGzipBudget(25_000, () => assert.fail("No compression needed for a proven bound"));
  assert.equal(result.method, "proven-upper-bound");
  assert.ok(result.bytes <= 512 * 1024);
});

test("near-limit HTML is measured and incompressible overflow is still refused", () => {
  const large = Buffer.alloc(600_000, 97);
  const result = verifyGzipBudget(large.length, () => large);
  assert.equal(result.method, "measured-gzip");
  assert.equal(result.bytes, gzipSync(large, { level: 9 }).length);
  const noise = randomBytes(600_000);
  assert.throws(() => verifyGzipBudget(noise.length, () => noise), /unchanged gzip budget/);
  assert.throws(() => verifyGzipBudget(600_000, () => Buffer.alloc(1)), /changed/);
  for (const value of [-1, NaN, Infinity, 2 ** 53]) assert.throws(() => gzipUpperBound(value));
});
