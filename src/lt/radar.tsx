import { StrictMode } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";

import { decodeSnapshotBootstrap } from "../lib/snapshotBootstrap.ts";
import "../styles.css";
import { LtRadarApp } from "./LtRadarApp.tsx";

const root = document.getElementById("root");
if (!root) throw new Error("Nerastas Radaro programos elementas.");
const bootstrap = root.dataset.radarBootstrap;
if (bootstrap) {
  const { snapshot, renderedAt, periodData } = decodeSnapshotBootstrap(bootstrap);
  hydrateRoot(root, <StrictMode><LtRadarApp initialSnapshot={snapshot} initialNow={renderedAt} initialPeriodData={periodData} /></StrictMode>);
  delete root.dataset.radarBootstrap;
  root.dataset.hydrated = "true";
} else {
  root.replaceChildren();
  createRoot(root).render(<StrictMode><LtRadarApp /></StrictMode>);
  root.dataset.hydrated = "client-rendered";
}
