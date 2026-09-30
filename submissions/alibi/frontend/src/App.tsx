import { useCallback, useEffect, useRef, useState } from "react";
import { get, type Person, type Status } from "./api";
import { Exoneration } from "./sections/Exoneration";
import { Files } from "./sections/Files";
import { Hero } from "./sections/Hero";
import { Prevention } from "./sections/Prevention";
import { Reconstruction } from "./sections/Reconstruction";
import { SheepGame } from "./sections/SheepGame";
import { Verdict } from "./sections/Verdict";
import { SourceModal } from "./components/SourceModal";
import { getState, setState, useStore } from "./store";

const SECTIONS = [
  ["alibi", "ALIBI"],
  ["files", "The files"],
  ["exoneration", "Exoneration first"],
  ["reconstruction", "Reconstruction"],
  ["verdict", "The verdict"],
  ["prevention", "Prevention"],
  ["bonus", "Bonus"],
] as const;

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [inventory, setInventory] = useState<any>(null);
  const [persons, setPersons] = useState<Person[]>([]);
  const [analysis, setAnalysis] = useState<any>(null);
  const [exportState, setExportState] = useState<any>(null);
  const [active, setActive] = useState("alibi");
  const present = useStore((s) => s.present);
  const lastJob = useRef<string | null>(null);

  const loadExport = useCallback(() => get("api/export").then(setExportState).catch(() => {}), []);
  const loadAll = useCallback(() => {
    get("api/inventory").then(setInventory).catch(() => {});
    get<Person[]>("api/persons").then(setPersons).catch(() => {});
    get("api/analysis").then(setAnalysis).catch(() => {});
    loadExport();
  }, [loadExport]);

  const loadStatus = useCallback(() => {
    get<Status>("api/status")
      .then((s) => {
        setStatus(s);
        const key = s.job ? `${s.job.id}:${s.job.status}:${s.job.completed_stages.length}:${s.job.done}` : null;
        if (key !== lastJob.current) {
          const before = lastJob.current;
          lastJob.current = key;
          if (before !== null) {
            loadAll();
            if (s.job && (s.job.status !== "running" || s.job.stage === "label")) setState({ analysisVersion: getState().analysisVersion + 1 });
          }
        }
      })
      .catch(() => {});
  }, [loadAll]);

  useEffect(() => {
    loadAll();
    loadStatus();
  }, [loadAll, loadStatus]);

  useEffect(() => {
    const running = status?.job?.status === "running";
    const t = setInterval(loadStatus, running ? 2500 : 15000);
    return () => clearInterval(t);
  }, [status?.job?.status, loadStatus]);

  useEffect(() => {
    document.body.classList.toggle("present", present);
  }, [present]);

  useEffect(() => {
    const obs = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(e.target.id)), {
      rootMargin: "-40% 0px -55% 0px",
    });
    SECTIONS.forEach(([id]) => {
      const el = document.getElementById(id);
      if (el) obs.observe(el);
    });
    return () => obs.disconnect();
  }, []);

  const bob = status?.bob;
  const rs = status?.result_source;
  return (
    <>
      <header className="shell">
        <a href="#alibi" className="name">
          <b>ALIBI</b> <span>Exoneration-first investigation</span>
        </a>
        <nav aria-label="Sections">
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`} className={active === id ? "on" : ""}>
              {label}
            </a>
          ))}
        </nav>
        <div className="actions">
          {status?.readonly ? (
            <span className="status ok" title={bob?.detail}>
              <i /> Read-only view · stored Bob analysis
            </span>
          ) : (
            <span className={`status ${bob?.connected ? "ok" : bob ? "bad" : ""}`} title={bob?.detail}>
              <i /> {bob ? (bob.connected ? "IBM Bob connected" : "IBM Bob not connected") : "IBM Bob …"}
            </span>
          )}
          {rs && !status?.readonly && (
            <span className={`status tech ${rs.kind === "none" ? "bad" : "ok"}`} title={rs.label}>
              <i /> {rs.kind === "none" ? "Preview without Bob" : "Results from Bob runs"}
            </span>
          )}
          <button className="hbtn" onClick={() => setState({ present: !present })} aria-pressed={present}>
            {present ? "Exit presentation" : "Presentation mode"}
          </button>
        </div>
      </header>
      <main>
        <Hero status={status} inventory={inventory} exportState={exportState} />
        <Files status={status} inventory={inventory} persons={persons} analysis={analysis} onStatus={loadStatus} />
        <Exoneration analysis={analysis} persons={persons} />
        <Reconstruction analysis={analysis} />
        <Verdict analysis={analysis} status={status} exportState={exportState} onExport={loadExport} />
        <Prevention analysis={analysis} />
        <SheepGame analysis={analysis} />
      </main>
      <footer className="footer">
        <div className="inner">
          ALIBI · Bobathon @ HSG · fictional case "The Meridian Problem". Every analysis step is a stored IBM Bob request; numbers are reasoned model
          estimates, not calibrated probabilities. Every statement links to an original passage. Visual design inspired by the IBM Carbon Design System
          – not an IBM product.
        </div>
      </footer>
      <SourceModal />
    </>
  );
}
