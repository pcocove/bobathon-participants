import type { Ev } from "../api";
import { BASIS } from "../labels";
import { openSource, showInGraph } from "../store";

const CHECK: Record<string, [string, string, string]> = {
  exact: ["teal", "ok", "✓ Quote verified at source"],
  pdf_whitespace: ["teal", "ok", "✓ Quote in PDF text (extraction whitespace)"],
  empty: ["red", "bad", "✕ No quote"],
  image: ["yellow", "warn", "◐ Image source – not exactly verifiable"],
  not_found: ["red", "bad", "✕ Quote not found"],
  unknown_unit: ["red", "bad", "✕ Unknown unit"],
  invalid_source: ["red", "bad", "✕ Invalid source"],
};

export function checkOf(ev: Ev): [string, string, string] {
  return CHECK[ev.status] ?? (ev.ok ? ["teal", "ok", "✓ Quote found"] : ["red", "bad", `✕ ${ev.status}`]);
}

export function QuoteCheck({ ev }: { ev: Ev }) {
  const [tone, , txt] = checkOf(ev);
  return (
    <span className={`tag ${tone}`} title={ev.detail || ""}>
      {txt}
      {ev.match === "normalized" ? " · whitespace normalised" : ev.match === "fragment" ? " · exact fragment" : ""}
    </span>
  );
}

export function BasisTag({ basis }: { basis?: string | null }) {
  if (!basis) return null;
  return (
    <span className="tag outline" title="Interpretation – checked separately from the quote">
      Interpretation: {BASIS[basis] ?? basis}
    </span>
  );
}

export function EvidenceItem({ ev, claim, basis, compact }: { ev: Ev; claim?: string; basis?: string; compact?: boolean }) {
  const q = ev.quote ?? ev.quote_given ?? "";
  const text = claim ?? ev.claim_de ?? ev.text;
  const [, cls] = checkOf(ev);
  return (
    <div className={`ev ${cls}`}>
      {text && <div className="claim">{text}</div>}
      {q && <div className="q">{q}</div>}
      <div className="row" style={{ marginTop: 6 }}>
        <button className="src" onClick={() => openSource(ev.source, ev.unit)} title="Open the original passage">
          {ev.source ?? ev.unit}
        </button>
        <QuoteCheck ev={ev} />
        {basis && <BasisTag basis={basis} />}
        {!compact && ev.unit && (
          <button
            className="btn ghost sm"
            onClick={() => showInGraph({ title: `Evidence ${ev.source ?? ev.unit}`, nodes: [`u:${ev.unit}`], kind: "unit" }, `u:${ev.unit}`)}
          >
            Show in network
          </button>
        )}
      </div>
    </div>
  );
}

export function EvidenceList({ list, empty, compact }: { list?: Ev[] | null; empty?: string; compact?: boolean }) {
  const l = (list ?? []).filter(Boolean);
  if (!l.length) return empty ? <div className="muted small">{empty}</div> : null;
  return (
    <div>
      {l.map((e, i) => (
        <EvidenceItem key={i} ev={e} compact={compact} />
      ))}
    </div>
  );
}

export function unitsOf(list?: Ev[] | null): string[] {
  return (list ?? []).filter((e) => e && e.unit && (e.ok || e.status === "image")).map((e) => `u:${e.unit}`);
}

export function Tag({ tone, children, title }: { tone?: string; children: React.ReactNode; title?: string }) {
  return (
    <span className={`tag ${tone ?? ""}`} title={title}>
      {children}
    </span>
  );
}

export function StatusPill({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <span className={`status-pill ${tone}`}>
      <i />
      {children}
    </span>
  );
}

export function HowTo({ children, label = "How is this number calculated?" }: { children: React.ReactNode; label?: string }) {
  return (
    <details className="howto">
      <summary>{label}</summary>
      {children}
    </details>
  );
}
