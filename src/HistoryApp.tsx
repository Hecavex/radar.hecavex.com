import { AlertTriangle, Archive } from "lucide-react";
import { useEffect, useState } from "react";

import { HistoryDashboard } from "./components/HistoryDashboard.tsx";
import { SiteFooter } from "./components/SiteFooter.tsx";
import { SiteHeader } from "./components/SiteHeader.tsx";
import { loadHistory } from "./lib/historyData.ts";
import { useCurrentTime } from "./lib/useCurrentTime.ts";
import type { SiteLanguage } from "./components/SiteHeader.tsx";
import type { RadarHistory } from "./types.ts";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; history: RadarHistory; totalSignals?: number; refreshError?: string }
  | { status: "error"; message: string };

export function HistoryApp(
  { initialHistory, initialNow, initialTotal, language = "en" }: { initialHistory?: RadarHistory; initialNow?: number; initialTotal?: number; language?: SiteLanguage } = {},
) {
  const now = useCurrentTime(initialNow);
  const lt = language === "lt";
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<LoadState>(
    initialHistory
      ? { status: "ready", history: initialHistory, totalSignals: initialTotal }
      : { status: "loading" },
  );
  useEffect(() => {
    const controller = new AbortController();
    void loadHistory(controller.signal)
      .then((history) => setState({ status: "ready", history }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : "Unknown history error.";
          setState((current) => current.status === "ready" ? { ...current, refreshError: message } : { status: "error", message });
        }
      });
    return () => controller.abort();
  }, [retry]);
  return (
    <div className="site-shell">
      <SiteHeader currentPage="history" language={language} />
      {(state.status === "error" || (state.status === "ready" && state.refreshError)) && <div role="status"><p>{lt ? "Istorijos atnaujinti nepavyko. Rodoma išsaugota peržiūra, jei ji yra; filtrai taikomi tik įkeltiems įrašams." : "History refresh failed. The saved preview remains available where present; filters apply only to loaded records."}</p><button className="button" type="button" onClick={() => setRetry((value) => value + 1)}>{lt ? "Bandyti dar kartą" : "Retry history refresh"}</button></div>}
      {state.status === "loading" && <main className="state-page" id="main-content" aria-live="polite"><Archive className="state-icon pulse" aria-hidden="true" /><p className="eyebrow">{lt ? "Skaitomas archyvas" : "Reading archive"}</p><h1>{lt ? "Kraunama kandidatų istorija" : "Loading candidate history"}</h1></main>}
      {state.status === "error" && <main className="state-page" id="main-content" aria-live="assertive"><AlertTriangle className="state-icon danger" aria-hidden="true" /><p className="eyebrow">{lt ? "Istorija nepasiekiama" : "History unavailable"}</p><h1>{lt ? "Nepavyko įkelti istorijos duomenų" : "The history artifact could not be loaded"}</h1><p>{state.message}</p></main>}
      {state.status === "ready" && <HistoryDashboard history={state.history} now={now} totalSignals={state.totalSignals} language={language} />}
      <SiteFooter language={language} />
    </div>
  );
}
