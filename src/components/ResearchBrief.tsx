import { useState } from "react";
import type { SignalPageData } from "../lib/pageBootstrap.ts";
import { buildResearchBrief, researchBriefCopy, researchBriefFilename } from "../lib/researchBrief.ts";

export function ResearchBrief({ data }: { data: SignalPageData }) {
  const [status, setStatus] = useState("");
  const text = researchBriefCopy[data.language];
  const brief = buildResearchBrief(data);
  async function copy() {
    try {
      await navigator.clipboard.writeText(brief);
      setStatus(text.copied);
    } catch {
      setStatus(text.denied);
    }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([brief], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = researchBriefFilename(data);
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setStatus(text.downloaded);
  }
  return <section className="profile-section research-brief" aria-labelledby="research-brief-title">
    <h2 id="research-brief-title">{text.title}</h2>
    <p>{text.intro}</p>
    <label htmlFor="research-brief-preview">{text.preview}</label>
    <textarea id="research-brief-preview" readOnly value={brief} rows={14} spellCheck={false} />
    <div className="research-brief-actions">
      <button className="button" type="button" onClick={() => void copy()}>{text.copy}</button>
      <button className="button" type="button" onClick={download}>{text.download}</button>
    </div>
    <p className="research-brief-status" role="status">{status}</p>
  </section>;
}
