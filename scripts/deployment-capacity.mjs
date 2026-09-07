// This is storage for the entire deployed site, not the bytes a reader downloads.
// Retained signals produce independent EN/LT pages, so directory totals grow
// with the archive even when every individual response stays small.
export const maximumOutputBytes = 256 * 1024 * 1024;

export function verifyDeploymentCapacity(totalBytes, capacity) {
  const partitions = Object.values(capacity);
  if (![totalBytes, ...partitions].every((bytes) => Number.isSafeInteger(bytes) && bytes >= 0)) {
    throw new Error("Deployment byte measurements must be non-negative safe integers.");
  }
  if (partitions.reduce((total, bytes) => total + bytes, 0) !== totalBytes) {
    throw new Error("Output capacity classes do not cover the complete production tree exactly once.");
  }
  if (totalBytes > maximumOutputBytes) {
    throw new Error(`Built output is ${totalBytes} bytes; deployment budget is ${maximumOutputBytes}.`);
  }
}
