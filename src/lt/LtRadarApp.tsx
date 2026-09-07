import { AlertTriangle, RadioTower } from "lucide-react";
import { useEffect, useState } from "react";

import { Dashboard } from "../components/Dashboard.tsx";
import { SiteHeader } from "../components/SiteHeader.tsx";
import { loadSnapshot } from "../lib/data.ts";
import { useCurrentTime } from "../lib/useCurrentTime.ts";
import type { RadarSnapshot } from "../types.ts";
import { LtFooter } from "./LtFooter.tsx";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; snapshot: RadarSnapshot; refreshError: string | null }
  | { status: "error"; message: string };

export function LtRadarApp({ initialSnapshot, initialNow }: { initialSnapshot?: RadarSnapshot; initialNow?: number } = {}) {
  const now = useCurrentTime(initialNow);
  const [state, setState] = useState<LoadState>(initialSnapshot
    ? { status: "ready", snapshot: initialSnapshot, refreshError: null }
    : { status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void loadSnapshot(controller.signal)
      .then((snapshot) => setState({ status: "ready", snapshot, refreshError: null }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : "Nežinoma duomenų klaida.";
          setState((current) => current.status === "ready"
            ? { ...current, refreshError: message }
            : { status: "error", message });
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="site-shell">
      <SiteHeader currentPage="radar" language="lt" alternateHref="/" />
      {state.status === "loading" && <main className="state-page" id="main-content" aria-live="polite"><RadioTower className="state-icon pulse" aria-hidden="true" /><p className="eyebrow">Gaunama suvestinė</p><h1>Kraunami naujausi signalai</h1></main>}
      {state.status === "error" && <main className="state-page" id="main-content" aria-live="assertive"><AlertTriangle className="state-icon danger" aria-hidden="true" /><p className="eyebrow">Duomenys nepasiekiami</p><h1>Nepavyko įkelti radaro suvestinės</h1><p>{state.message}</p><button className="button" type="button" onClick={() => window.location.reload()}>Bandyti dar kartą</button></main>}
      {state.status === "ready" && (
        <Dashboard snapshot={state.snapshot} now={now} language="lt" refreshError={state.refreshError} />
      )}
      <LtFooter />
    </div>
  );
}
