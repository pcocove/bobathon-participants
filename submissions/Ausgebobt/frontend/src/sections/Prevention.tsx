import { EvidenceList, unitsOf } from "../components/Evidence";
import { CATEGORY, PRIORITY } from "../labels";
import { showInGraph } from "../store";

const ORDER = ["zugriff", "kopie", "erkennung", "untersuchung"];

export function Prevention({ analysis }: { analysis: any }) {
  const ms: any[] = analysis?.prevention?.measures ?? [];
  const tl: any[] = analysis?.final?.timeline ?? [];
  return (
    <section className="sec" id="prevention">
      <div className="inner">
        <div className="eyebrow">
          <b>06</b>Prevention
        </div>
        <h2>Controls derived from the documented sequence</h2>
        <p className="lead">
          Every recommendation is tied to a concrete step of the reconstruction and to original evidence. It changes neither evidence nor verdict. Where
          the sequence is uncertain, the recommendation is explicitly conditional – and where only detection is possible, it promises no prevention.
        </p>
        {!ms.length && (
          <div className="notice">
            <div>No prevention analysis yet.</div>
          </div>
        )}
        {ms.length > 0 && (
          <div className="grid g4 gap">
            {ORDER.map((k) => {
              const [title, q] = CATEGORY[k];
              return (
                <div key={k}>
                  <h3 style={{ fontSize: 20, lineHeight: "28px" }}>{title}</h3>
                  <div className="small muted" style={{ marginBottom: 12 }}>{q}</div>
                  {ms
                    .filter((m) => m.category === k)
                    .sort((a, b) => ["hoch", "mittel", "niedrig"].indexOf(a.priority) - ["hoch", "mittel", "niedrig"].indexOf(b.priority))
                    .map((m, i) => {
                      const step = m.timeline_index != null ? tl[m.timeline_index] : null;
                      const nodes = [...unitsOf(m.evidence), ...(step ? unitsOf(step.evidence) : [])];
                      const [ptone, plabel] = PRIORITY[m.priority] ?? ["gray", m.priority];
                      return (
                        <div key={i} className={`tile cat ${k}`} style={{ marginBottom: 16 }}>
                          <div className="row">
                            <span className={`tag ${ptone}`}>{plabel}</span>
                            {m.conditional && <span className="tag yellow">conditional</span>}
                          </div>
                          <h4 className="h4" style={{ fontSize: 16, marginTop: 12 }}>{m.title}</h4>
                          <div className="small"><b>Weakness:</b> {m.weakness}</div>
                          <div className="small"><b>Attack step:</b> {m.attack_step}</div>
                          <div className="small"><b>Control:</b> {m.control}</div>
                          <div className="small"><b>Expected effect:</b> {m.effect}</div>
                          <div className="small muted"><b>Limits:</b> {m.limits}</div>
                          <div className="tiny muted" style={{ marginTop: 8 }}>{m.priority_reason}</div>
                          <details className="more">
                            <summary>Evidence ({(m.evidence ?? []).length})</summary>
                            <EvidenceList list={m.evidence} compact />
                          </details>
                          {nodes.length > 0 && (
                            <button
                              className="btn tertiary sm"
                              style={{ marginTop: 12 }}
                              onClick={() => showInGraph({ title: `Control point: ${m.title}`, nodes, order: nodes, kind: "chain" })}
                            >
                              Show step in network
                            </button>
                          )}
                        </div>
                      );
                    })}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
