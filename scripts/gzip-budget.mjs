import { gzipSync } from "node:zlib";

// zlib deflateBound(), conservative fixed/stored-block bounds plus the default
// 18-byte gzip wrapper. This deliberately does not assume the tighter defaults.
// Primary algorithm: https://github.com/madler/zlib/blob/v1.3.1/deflate.c#L748-L830
// Applies to gzipSync's ordinary header, with no custom extra/name/comment.
export function gzipUpperBound(size) {
  if (!Number.isSafeInteger(size) || size < 0 || size > 256 * 1024 * 1024) {
    throw new Error("Invalid bounded gzip input size.");
  }
  const fixed = size + Math.floor(size / 8) + Math.floor(size / 256) + Math.floor(size / 512) + 4;
  const stored = size + Math.floor(size / 32) + Math.floor(size / 128) + Math.floor(size / 2048) + 7;
  return Math.max(fixed, stored) + 18;
}

export function verifyGzipBudget(rawSize, readBytes, maximum = 512 * 1024) {
  const bound = gzipUpperBound(rawSize);
  if (bound <= maximum) return { bytes: bound, method: "proven-upper-bound" };
  const body = readBytes();
  if (body.byteLength !== rawSize) throw new Error("HTML changed during the capacity check.");
  const actual = gzipSync(body, { level: 9 }).byteLength;
  if (actual > maximum) throw new Error(`HTML exceeds the unchanged gzip budget: ${actual} > ${maximum}`);
  return { bytes: actual, method: "measured-gzip" };
}
