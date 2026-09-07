import { useEffect, useState } from "react";

/** Hydration starts at the embedded clock; elapsed time never changes artifact provenance. */
export function useCurrentTime(initialNow?: number): number {
  const [now, setNow] = useState(initialNow ?? Date.now());
  useEffect(() => {
    const update = () => setNow(Date.now());
    update();
    const timer = window.setInterval(update, 60_000);
    document.addEventListener("visibilitychange", update);
    window.addEventListener("focus", update);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", update);
      window.removeEventListener("focus", update);
    };
  }, []);
  return now;
}
