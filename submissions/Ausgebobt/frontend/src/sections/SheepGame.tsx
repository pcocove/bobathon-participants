import { useRef, useState } from "react";
import { fmt } from "../api";
import { EvidenceList } from "../components/Evidence";

type Res = { color: "green" | "red" | "yellow"; title: string; text: string; evidence: any[] };

// Feedback comes only from the stored analysis. No Bob calls, no hidden solution.
export function judge(analysis: any, id: string, T: number): Res {
  const fin = analysis?.final;
  const p = fin?.persons?.find((x: any) => x.id === id);
  const pr = analysis?.persons?.[id]?.result;
  if (!fin || !p) {
    return { color: "yellow", title: "Still open", text: "There is no analysis for this person yet. No analysis, no verdict.", evidence: [] };
  }
  const okEv = (p.evidence ?? []).filter((e: any) => e.ok);
  const exo = pr?.exoneration_confidence;
  if (p.verdict === "cleared" && typeof exo === "number" && exo >= T && okEv.length) {
    return {
      color: "green",
      title: "Cleared – this sheep may leave",
      text: `The exoneration is documented (exoneration confidence ${fmt.num(exo)} ≥ UI threshold ${fmt.num(T)}).`,
      evidence: okEv,
    };
  }
  const pos = okEv.filter((e: any) => e.kind === "belastend");
  if (p.verdict === "culprit" && typeof fin.verdict_confidence === "number" && fin.verdict_confidence >= T && pos.length) {
    return {
      color: "red",
      title: "The analysis supports the culprit hypothesis",
      text: `Positive incriminating evidence and verdict confidence ${fmt.num(fin.verdict_confidence)} ≥ UI threshold ${fmt.num(T)}.`,
      evidence: pos,
    };
  }
  let why = "The situation is open.";
  if (p.verdict === "cleared") why = `Assessed as cleared, but the exoneration confidence (${fmt.num(exo)}) is below the UI threshold ${fmt.num(T)}.`;
  else if (p.verdict === "culprit")
    why = pos.length
      ? `Leading hypothesis, but the verdict confidence (${fmt.num(fin.verdict_confidence)}) is below the UI threshold ${fmt.num(T)}.`
      : "Leading hypothesis, but without explicitly incriminating, verified evidence – a relative weight alone is not enough.";
  else why = "Neither documented as cleared nor documented as incriminated. Missing exoneration is not proof of guilt.";
  return { color: "yellow", title: "Open – stays inside for now", text: why, evidence: okEv };
}

function Sheep({ color }: { color?: string }) {
  return (
    <svg viewBox="0 0 120 90" width="120" height="90" aria-hidden="true">
      <g stroke="#2a2a2a" strokeWidth="4" strokeLinecap="round">
        <line x1="38" y1="62" x2="36" y2="82" />
        <line x1="52" y1="64" x2="52" y2="84" />
        <line x1="72" y1="64" x2="72" y2="84" />
        <line x1="86" y1="62" x2="88" y2="82" />
      </g>
      <g fill="#ffffff" stroke={color ?? "#c6c6c6"} strokeWidth={color ? 3 : 1.5}>
        <ellipse cx="62" cy="46" rx="38" ry="24" />
        <circle cx="34" cy="38" r="13" />
        <circle cx="50" cy="28" r="14" />
        <circle cx="70" cy="26" r="14" />
        <circle cx="88" cy="36" r="13" />
        <circle cx="92" cy="54" r="11" />
      </g>
      <ellipse cx="22" cy="48" rx="13" ry="15" fill="#2e2b28" />
      <ellipse cx="13" cy="40" rx="6" ry="3" fill="#2e2b28" transform="rotate(-25 13 40)" />
      <circle cx="18" cy="46" r="2.4" fill="#fff" />
      <circle cx="18.5" cy="46.5" r="1.2" fill="#111" />
    </svg>
  );
}

export function SheepGame({ analysis }: { analysis: any }) {
  const T = analysis?.sheep_threshold ?? 0.8;
  const sus: { id: string; name: string }[] = analysis?.suspects ?? [];
  const [jail, setJail] = useState<string[]>([]);
  const [res, setRes] = useState<(Res & { id: string }) | null>(null);
  const [drag, setDrag] = useState<{ id: string; x: number; y: number } | null>(null);
  const [hot, setHot] = useState(false);
  const jailRef = useRef<HTMLDivElement>(null);

  const overJail = (x: number, y: number) => {
    const r = jailRef.current?.getBoundingClientRect();
    return !!r && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
  };
  const check = (id: string) => {
    const r = judge(analysis, id, T);
    setRes({ ...r, id });
    setJail((j) => (j.includes(id) ? j : [...j, id]));
    if (r.color === "green") setTimeout(() => setJail((j) => j.filter((x) => x !== id)), 1600);
  };
  const release = (id: string) => setJail((j) => j.filter((x) => x !== id));

  const onDown = (id: string) => (e: React.PointerEvent) => {
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    setDrag({ id, x: e.clientX, y: e.clientY });
  };
  const onMove = (e: React.PointerEvent) => {
    if (!drag) return;
    setDrag({ ...drag, x: e.clientX, y: e.clientY });
    setHot(overJail(e.clientX, e.clientY));
  };
  const onUp = (e: React.PointerEvent) => {
    if (!drag) return;
    if (overJail(e.clientX, e.clientY)) check(drag.id);
    setDrag(null);
    setHot(false);
  };
  const color = (id: string) => {
    if (!jail.includes(id) || res?.id !== id) return undefined;
    return res.color === "green" ? "#007d79" : res.color === "red" ? "#da1e28" : "#f1c21b";
  };

  return (
    <section className="sec alt" id="bonus" onPointerMove={onMove} onPointerUp={onUp}>
      <div className="inner">
        <div className="eyebrow"><b>07</b>Bonus</div>
        <h2>Drag the sheep into jail</h2>
        <p className="lead">
          Drag a sheep into the jail – or use the button below it. The answer comes only from the stored analysis: green only with documented
          exoneration, red only with positive incriminating evidence and sufficient verdict confidence, yellow otherwise. The threshold {fmt.num(T)} is
          a UI rule, not a statistical limit from the case. Playing changes nothing in the analysis.
        </p>
        <div className="farm">
          <div className="meadow" aria-label="Meadow">
            {sus.filter((s) => !jail.includes(s.id)).map((s) => (
              <div key={s.id} style={{ textAlign: "center" }}>
                <button className="sheep" onPointerDown={onDown(s.id)} aria-label={`${s.name} – drag`} style={{ opacity: drag?.id === s.id ? 0.3 : 1 }}>
                  <Sheep />
                  <div className="nametag">{s.name}</div>
                </button>
                <div>
                  <button className="btn ghost sm" onClick={() => check(s.id)} style={{ marginTop: 4 }}>
                    Send to jail
                  </button>
                </div>
              </div>
            ))}
            {!sus.length && <div className="muted">Loading people …</div>}
          </div>
          <div ref={jailRef} className={`jail ${hot ? "hot" : ""}`} aria-label="Jail">
            <div className="sign">JAIL</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "center" }}>
              {jail.map((id) => (
                <button key={id} className="sheep" style={{ width: 110 }} onClick={() => release(id)} title="Back to the meadow">
                  <Sheep color={color(id)} />
                  <div className="nametag">{sus.find((s) => s.id === id)?.name}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
        {res && (
          <div className={`tile verdictbox ${res.color}`} role="status" aria-live="polite">
            <div className="spread">
              <h3>
                {sus.find((s) => s.id === res.id)?.name}: {res.title}
              </h3>
              <span className={`status-pill ${res.color === "green" ? "teal" : res.color === "red" ? "red" : "yellow"}`}>
                <i />
                {res.color === "green" ? "green" : res.color === "red" ? "red" : "yellow"}
              </span>
            </div>
            <p>{res.text}</p>
            <details className="more">
              <summary>Related evidence ({res.evidence.length})</summary>
              <EvidenceList list={res.evidence} compact empty="No verified evidence." />
            </details>
          </div>
        )}
      </div>
      {drag && (
        <div className="sheep dragging" style={{ left: drag.x - 60, top: drag.y - 45 }}>
          <Sheep />
          <div className="nametag">{sus.find((s) => s.id === drag.id)?.name}</div>
        </div>
      )}
    </section>
  );
}
