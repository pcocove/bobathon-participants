import { useEffect, useState } from "react";
import { get } from "../api";
import { setState, useStore } from "../store";
import { UnitView } from "./UnitView";

// Shows the original passage for a source reference (lines / page / Excel row) plus its unit.
export function SourceModal() {
  const src = useStore((s) => s.source);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setErr(null);
    if (!src?.ref) return;
    get(`api/source?ref=${encodeURIComponent(src.ref)}&ctx=4`).then(setData, (e) => setErr(String(e.message)));
  }, [src?.ref]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && setState({ source: null });
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  if (!src) return null;
  const unit = data?.unit ?? src.unit;
  return (
    <div className="modal-bg" onClick={() => setState({ source: null })}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="head">
          <div className="label">Original evidence</div>
          <h3 className="mono" style={{ fontSize: 16 }}>{src.ref ?? unit}</h3>
          <button className="close" onClick={() => setState({ source: null })} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="body">
          {err && <div className="notice bad">{err}</div>}
          {data?.kind === "lines" && (
            <div className="orig">
              {data.lines.map((l: any) => (
                <div key={l.n} className={`ln ${l.in ? "hit" : "out"}`}>
                  <span>{l.n}</span>
                  <span>{l.text || " "}</span>
                </div>
              ))}
            </div>
          )}
          {data?.kind === "pdf" && (
            <>
              <div className="label">PDF page {data.page} – text layer (pypdf)</div>
              <pre className="orig" style={{ padding: 12, whiteSpace: "pre-wrap" }}>{data.segments[0]}</pre>
            </>
          )}
          {data?.kind === "xlsx" && (
            <>
              <div className="label">Excel row {data.page} (first sheet)</div>
              <div className="orig" style={{ padding: 12 }}>{data.segments.filter(Boolean).join("  |  ")}</div>
            </>
          )}
          {data?.kind === "image" && <div className="notice warn">Image source – cited without a line number; quotes cannot be verified exactly.</div>}
          {unit && (
            <div style={{ marginTop: 24 }}>
              <UnitView uid={unit} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
