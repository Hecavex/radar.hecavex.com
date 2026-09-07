import { AlertTriangle, Archive } from "lucide-react";
import { useEffect, useState } from "react";

import { HistoryDashboard } from "./components/HistoryDashboard.tsx";
import { SiteFooter } from "./components/SiteFooter.tsx";
import { SiteHeader } from "./components/SiteHeader.tsx";
import { loadHistory } from "./lib/historyData.ts";
import type { RadarHistory } from "./types.ts";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; history: RadarHistory; renderedAt: number; totalSignals?: number }
  | { status: "error"; message: string };

export function HistoryApp(
  { initialHistory, initialNow, initialTotal }: { initialHistory?: RadarHistory; initialNow?: number; initialTotal?: number } = {},
) {
  const [state, setState] = useState<LoadState>(
    initialHistory
      ? { status: "ready", history: initialHistory, renderedAt: initialNow ?? Date.now(), totalSignals: initialTotal }
      : { status: "loading" },
  );
  useEffect(() => {
    const controller = new AbortController();
    void loadHistory(controller.signal)
      .then((history) => setState({ status: "ready", history, renderedAt: Date.now() }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ status: "error", message: error instanceof Error ? error.message : "Unknown history error." });
        }
      });
    return () => controller.abort();
  }, []);
  return (
    <div className="site-shell">
      <SiteHeader currentPage="history" />
      {state.status === "loading" && <main className="state-page" id="main-content" aria-live="polite"><Archive className="state-icon pulse" aria-hidden="true" /><p className="eyebrow">Reading archive</p><h1>Loading candidate history</h1></main>}
      {state.status === "error" && <main className="state-page" id="main-content" aria-live="assertive"><AlertTriangle className="state-icon danger" aria-hidden="true" /><p className="eyebrow">History unavailable</p><h1>The history artifact could not be loaded</h1><p>{state.message}</p></main>}
      {state.status === "ready" && <HistoryDashboard history={state.history} now={state.renderedAt} totalSignals={state.totalSignals} />}
      <SiteFooter />
    </div>
  );
}
