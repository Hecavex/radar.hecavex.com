import type { RadarHistory } from "../types.ts";

// HTML is not an archive transport. Keep its first useful page bounded while
// the browser validates and loads the complete, independently bounded dataset.
export const HISTORY_BOOTSTRAP_BYTES = 64 * 1024;

export function historyPreview(history: RadarHistory): RadarHistory {
  const encoder = new TextEncoder();
  let bytes = encoder.encode(JSON.stringify({ ...history, signals: [] })).length;
  const signals: RadarHistory["signals"] = [];
  for (const signal of history.signals) {
    const size = encoder.encode(JSON.stringify(signal)).length + 1;
    if (bytes + size > HISTORY_BOOTSTRAP_BYTES) break;
    signals.push(signal);
    bytes += size;
  }
  return { ...history, signals };
}
