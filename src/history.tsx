import { StrictMode } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";

import { HistoryApp } from "./HistoryApp.tsx";
import { decodeHistoryBootstrap } from "./lib/historyBootstrap.ts";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing Radar history root.");
const bootstrap = root.dataset.historyBootstrap;
if (bootstrap) {
  void decodeHistoryBootstrap(bootstrap).then(({ history, renderedAt, totalSignals }) => {
    hydrateRoot(root, <StrictMode><HistoryApp initialHistory={history} initialNow={renderedAt} initialTotal={totalSignals} /></StrictMode>);
    delete root.dataset.historyBootstrap;
    root.dataset.hydrated = "true";
  });
} else {
  root.replaceChildren();
  createRoot(root).render(<StrictMode><HistoryApp /></StrictMode>);
  root.dataset.hydrated = "client-rendered";
}
