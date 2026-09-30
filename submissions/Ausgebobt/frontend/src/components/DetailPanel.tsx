import type Graph from "graphology";
import type { Person } from "../api";
import { fmt } from "../api";
import { CONCLUSION, LINK_BASIS, VERDICT, relLabel } from "../labels";
import { openSource, setState } from "../store";
import { BasisTag } from "./Evidence";
import { UnitView } from "./UnitView";

const ALIAS: Record<string, string> = { slack_id: "Slack ID", email: "Email", handle: "Handle", name: "Name", plate: "Plate" };

export function DetailPanel({ id, graph, persons, analysis }: { id: string; graph: Graph; persons: Person[]; analysis: any }) {
  const close = () => setState({ selected: null });
  let body: React.ReactNode = null;
  if (id.startsWith("u:")) body = <UnitView uid={id.slice(2)} />;
  else if (id.startsWith("p:")) body = <PersonBox id={id.slice(2)} graph={graph} persons={persons} analysis={analysis} />;
  else if (id.startsWith("e:")) body = <EntityBox id={id} graph={graph} />;
  else if (id.startsWith("edge:")) body = <RelationBox edge={id.slice(5)} graph={graph} />;
  return (
    <div className="detail" role="complementary" aria-label="Details">
      <div className="head">
        <div className="label">
          {id.startsWith("u:") ? "Evidence & interpretation" : id.startsWith("p:") ? "Person" : id.startsWith("e:") ? "Entity" : "Relation"}
        </div>
        <button className="close" onClick={close} aria-label="Close details">✕</button>
      </div>
      <div className="body">{body}</div>
    </div>
  );
}

function PersonBox({ id, graph, persons, analysis }: { id: string; graph: Graph; persons: Person[]; analysis: any }) {
  const p = persons.find((x) => x.id === id);
  if (!p) return <div className="muted">Unknown</div>;
  const counts: Record<string, number> = {};
  graph.forEachEdge(`p:${id}`, (_e, a) => {
    if (a.kind === "bezug") counts[a.b] = (counts[a.b] ?? 0) + 1;
  });
  const pr = analysis?.persons?.[id]?.result;
  const fin = analysis?.final?.persons?.find((x: any) => x.id === id);
  return (
    <div>
      <h3>{p.name}</h3>
      <div className="muted small">{p.titles?.[0]?.value ?? (p.kind === "organisation" ? "Organisation" : "")}</div>
      {p.suspect && <div className="tag yellow" style={{ marginTop: 8 }}>One of the eight people under review</div>}
      <h4>Analysis</h4>
      {!pr && <div className="small muted">Not evaluated yet</div>}
      {pr && (
        <div className="small">
          <div>
            Individual review: <b>{CONCLUSION[pr.conclusion]?.[1] ?? pr.conclusion}</b> · exoneration confidence {fmt.num(pr.exoneration_confidence)}
          </div>
          {fin && (
            <div>
              Verdict: <b>{VERDICT[fin.verdict]?.[1] ?? fin.verdict}</b>
            </div>
          )}
          <p>{pr.summary_de}</p>
          <button className="btn tertiary sm" onClick={() => document.getElementById(`dossier-${id}`)?.scrollIntoView({ behavior: "smooth" })}>
            Open case file
          </button>
        </div>
      )}
      <h4>Linked units by link basis</h4>
      <div className="kv">
        {Object.entries(counts).map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <div>{LINK_BASIS[k] ?? k}</div>
            <div>{v}</div>
          </div>
        ))}
      </div>
      <h4>Aliases (with source)</h4>
      <div className="small">
        {p.aliases.map((a, i) => (
          <div key={i}>
            {ALIAS[a.kind] ?? a.kind}: <span className="mono">{a.value}</span>{" "}
            {a.source && (
              <button className="btn ghost sm" style={{ minHeight: 24, padding: "0 4px" }} onClick={() => openSource(a.source!.includes(":") ? a.source : null)}>
                {a.source}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function EntityBox({ id, graph }: { id: string; graph: Graph }) {
  if (!graph.hasNode(id)) return null;
  const a = graph.getNodeAttributes(id);
  const nb: string[] = [];
  graph.forEachNeighbor(id, (n) => nb.push(n));
  return (
    <div>
      <h3>{a.label}</h3>
      <div className="muted small">Entity recognised by Bob · {id.split(":")[1]}</div>
      <h4>Linked ({nb.length})</h4>
      <ul className="plist">
        {nb.slice(0, 80).map((n) => (
          <li key={n}>
            <button onClick={() => setState({ selected: n })}>{graph.getNodeAttribute(n, "label")}</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RelationBox({ edge, graph }: { edge: string; graph: Graph }) {
  if (!graph.hasEdge(edge)) return null;
  const a = graph.getEdgeAttributes(edge);
  return (
    <div>
      <h3>
        {graph.getNodeAttribute(a.s0, "label")} <span className="muted">— {relLabel(a.rt)} —</span> {graph.getNodeAttribute(a.t0, "label")}
      </h3>
      <p>{a.tx}</p>
      <div className="ev ok">
        <div className="q">{a.q}</div>
        <div className="row" style={{ marginTop: 6 }}>
          <button className="src" onClick={() => openSource(a.src, a.u)}>{a.src}</button>
          <span className="tag teal">✓ Quote verified at source</span>
          <BasisTag basis={a.b} />
        </div>
      </div>
      <div className="tiny muted">Relation from a Bob label. The verified quote proves the passage exists – not automatically the interpretation.</div>
      {a.u && (
        <button className="btn tertiary sm" style={{ marginTop: 12 }} onClick={() => setState({ selected: `u:${a.u}` })}>
          Open evidence unit
        </button>
      )}
    </div>
  );
}
