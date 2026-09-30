import { useEffect, useState } from "react";
import { get } from "../api";
import { LINK_BASIS, RELEVANCE, TAG, relLabel } from "../labels";
import { BasisTag, QuoteCheck } from "./Evidence";

export function UnitView({ uid }: { uid: string }) {
  const [u, setU] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setU(null);
    setErr(null);
    get(`api/unit/${encodeURIComponent(uid)}`).then(setU, (e) => setErr(String(e.message)));
  }, [uid]);
  if (err) return <div className="notice bad">{err}</div>;
  if (!u) return <div className="muted small">Loading unit …</div>;
  const lab = u.label;
  return (
    <div>
      <div className="row">
        <span className="tag blue">{u.doc_label}</span>
        <span className="mono tiny muted">{u.id}</span>
      </div>
      <h3 style={{ marginTop: 8 }}>{u.title}</h3>
      <div className="mono tiny muted" style={{ marginTop: 2 }}>
        {u.file}
        {u.loc.type === "lines" && `:${u.loc.start}${u.loc.end !== u.loc.start ? "-" + u.loc.end : ""}`}
        {u.loc.type === "page" && ` · page ${u.loc.page}`}
        {u.loc.type === "row" && ` · Excel row ${u.loc.row}`}
      </div>
      {u.note && (
        <div className="notice small" style={{ marginTop: 12 }}>
          <div>{u.note}</div>
        </div>
      )}

      {u.times?.length > 0 && (
        <>
          <h4>Timestamps (original → normalised to Europe/Zurich)</h4>
          {u.times.map((t: any, i: number) => (
            <div key={i} className="small" style={{ marginBottom: 4 }}>
              <span className="mono">{t.original}</span> → <b>{(t.local || "").replace("T", " ").slice(0, 19)}</b>{" "}
              <span className="muted">({t.basis}{t.assumed_zone ? "; zone assumed, clock not corrected" : ""})</span>
            </div>
          ))}
        </>
      )}

      {u.people?.length > 0 && (
        <>
          <h4>Linked people (from IDs, aliases, plates)</h4>
          <div className="small">
            {u.people.slice(0, 14).map((p: any, i: number) => (
              <div key={i}>
                <b>{u.person_names[p.person] ?? p.person ?? p.list}</b>{" "}
                <span className="muted">
                  – {p.role || LINK_BASIS[p.basis] || p.basis}: {p.via}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      <h4>Original</h4>
      {u.lines && (
        <div className="orig">
          {u.lines.map((l: any) => (
            <div key={l.n} className={`ln ${l.in ? "" : "out"} ${u.loc.focus === l.n ? "hit" : ""}`}>
              <span>{l.n}</span>
              <span>{l.text || " "}</span>
            </div>
          ))}
        </div>
      )}
      {u.page_text && <pre className="orig" style={{ padding: 10, whiteSpace: "pre-wrap" }}>{u.page_text}</pre>}
      {u.row_cells && <div className="orig" style={{ padding: 10 }}>{u.row_cells.filter(Boolean).join("  |  ")}</div>}
      {u.image && (
        <div style={{ marginTop: 8 }}>
          <img src={`api/image/${encodeURIComponent(u.id)}`} alt={u.title} style={{ maxWidth: "100%", border: "1px solid var(--border)" }} />
        </div>
      )}
      {u.vision && (
        <>
          <h4>
            Bob Vision transcript <span className="tag yellow">uncertain – never exported as a quote</span>
          </h4>
          <div className="orig" style={{ padding: 10 }}>
            {(u.vision.transcript_lines || []).map((l: string, i: number) => (
              <div key={i}>{l}</div>
            ))}
          </div>
          <p className="small muted">{u.vision.description}</p>
        </>
      )}

      <h4>Bob's interpretation</h4>
      {!lab && (
        <div className="small muted">
          {u.reviewed ? `Reviewed by Bob (package ${u.reviewed.package}) – not reported as relevant.` : "Not yet reviewed by Bob."}
        </div>
      )}
      {lab && (
        <div>
          <div className="row" style={{ marginBottom: 8 }}>
            <span className="tag outline">Relevance: {RELEVANCE[lab.relevance] ?? lab.relevance}</span>
            {(lab.tags || []).map((t: string) => (
              <span key={t} className={`tag ${TAG[t]?.[0] ?? ""}`}>{TAG[t]?.[1] ?? t}</span>
            ))}
          </div>
          <div style={{ marginBottom: 8 }}>{lab.summary}</div>
          {(lab.claims || []).map((c: any, i: number) => (
            <div className="ev" key={i}>
              <div className="claim">{c.text}</div>
              {c.evidence?.quote && <div className="q">{c.evidence.quote}</div>}
              <div className="row" style={{ marginTop: 6 }}>
                <span className="mono tiny">{c.evidence?.source ?? "—"}</span>
                <QuoteCheck ev={c.evidence} />
                <BasisTag basis={c.basis} />
                {c.relation && <span className="tag purple">Relation: {relLabel(c.relation.type)}</span>}
              </div>
            </div>
          ))}
          <div className="tiny muted" style={{ marginTop: 8 }}>
            Bob label (AI interpretation) · package {lab.package} · request {lab.call}
            {lab.reused ? " (stored result)" : ""} · shown in English (Bob translation of the stored German label)
          </div>
        </div>
      )}
    </div>
  );
}
