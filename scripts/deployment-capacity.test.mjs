import assert from "node:assert/strict";
import test from "node:test";

import { maximumOutputBytes, verifyDeploymentCapacity } from "./deployment-capacity.mjs";

test("retained signal pages can cross the former 12 MiB allocation", () => {
  const capacity = {
    signalHtmlBytes: 13_484_134,
    brandHtmlBytes: 2_000_000,
    pairedStaticDataHtmlBytes: 5_000_000,
    remainingOutputBytes: 5_000_000,
  };
  assert.doesNotThrow(() => verifyDeploymentCapacity(
    Object.values(capacity).reduce((total, bytes) => total + bytes, 0), capacity,
  ));
});

test("archive growth can exceed the old 32 MiB whole-site ceiling", () => {
  const capacity = { signalHtmlBytes: 96 * 1024 * 1024, remainingOutputBytes: 20 * 1024 * 1024 };
  assert.doesNotThrow(() => verifyDeploymentCapacity(
    capacity.signalHtmlBytes + capacity.remainingOutputBytes, capacity,
  ));
});

test("the whole deployment retains a finite storage limit", () => {
  assert.doesNotThrow(() => verifyDeploymentCapacity(maximumOutputBytes, { all: maximumOutputBytes }));
  assert.throws(
    () => verifyDeploymentCapacity(maximumOutputBytes + 1, { all: maximumOutputBytes + 1 }),
    /deployment budget/,
  );
});

test("unaccounted or double-counted output remains a failure", () => {
  assert.throws(() => verifyDeploymentCapacity(100, { pages: 60, other: 30 }), /exactly once/);
  assert.throws(() => verifyDeploymentCapacity(100, { pages: 60, other: 60 }), /exactly once/);
});

test("invalid byte measurements cannot bypass the deployment gate", () => {
  for (const bytes of [-1, NaN, Infinity, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => verifyDeploymentCapacity(bytes, { all: bytes }), /safe integers/);
  }
});
