import { fmt } from "../api";
import { EvidenceList, HowTo, unitsOf } from "../components/Evidence";
import { CLOCK, STEP_STATUS, who } from "../labels";
import { showInGraph } from "../store";

export function Reconstruction({ analysis }: { analysis: any }) {
  const f = analysis?.final;
  const fr = analysis?.frame;
  const name = (h: string) => analysis?.suspects?.find((s: any) => s.id === h)?.name ?? h;
  return (
    <section className="sec" id="reconstruction">
      <div className="inner">
        <div className="eyebrow">
          <b>04</b>The reconstruction
        </div>
        <h2>Who, when, how – step by step with evidence</h2>
        <p className="lead">
          The sequence of events as Bob reconstructs it from the verified evidence. Every step is marked as documented, derived or hypothesis. Times are
          normalised to Europe/Zurich; each source's time basis is stated.
        </p>
        {!f && (
          <div className="notice">
            <div>No reconstruction yet – the analysis has not reached the verdict stage.</div>
          </div>
        )}
        {fr?.incident && (
          <div className="tile" style={{ marginBottom: 16 }}>
            <h3>The incident</h3>
            <p style={{ marginTop: 0 }}>{fr.incident.summary}</p>
            <div className="small muted">
              Decisive window: {fmt.when(fr.incident.window_start_local)} – {fmt.when(fr.incident.window_end_local)} · {fr.incident.window_note}
            </div>
          </div>
        )}
        {f && (
          <div className="grid gap" style={{ gridTemplateColumns: "minmax(0,1.5fr) minmax(0,1fr)" }}>
            <div className="tile">
              <div className="spread" style={{ marginBottom: 16 }}>
                <h3 style={{ margin: 0 }}>Timeline</h3>
                <button
                  className="btn tertiary sm"
                  onClick={() => {
                    const nodes = (f.timeline ?? []).flatMap((t: any) => unitsOf(t.evidence).slice(0, 1));
                    showInGraph({ title: "Reconstructed sequence", nodes, order: nodes, kind: "chain" });
                  }}
                >
                  Show sequence as chain in network
                </button>
              </div>
              <div className="timeline">
                {(f.timeline ?? []).map((t: any, i: number) => {
                  const [tone, label] = STEP_STATUS[t.status] ?? ["gray", t.status];
                  return (
                    <div key={i} className={`tl ${t.status}`}>
                      <div className="when">
                        {fmt.when(t.when)} <span className="muted">· {t.when_note}</span>
                      </div>
                      <div className="what">{t.what}</div>
                      <div className="small muted row" style={{ gap: 6 }}>
                        <span>
                          Who: {who(t.who, name)} · How: {t.how}
                        </span>
                        <span className={`tag ${tone}`}>{label}</span>
                      </div>
                      <EvidenceList list={t.evidence} compact />
                    </div>
                  );
                })}
              </div>
            </div>
            <div>
              <h3 style={{ fontSize: 20, marginBottom: 12 }}>Evidence chains</h3>
              {(f.chains ?? []).map((c: any, i: number) => {
                const nodes = (c.steps ?? []).flatMap((s: any) => unitsOf(s.evidence).slice(0, 1));
                return (
                  <div className="tile" key={i} style={{ marginBottom: 16 }}>
                    <div className="spread">
                      <h4 className="h4" style={{ margin: 0, fontSize: 16 }}>{c.title}</h4>
                      <button className="btn tertiary sm" onClick={() => showInGraph({ title: c.title, nodes, order: nodes, kind: "chain" })}>
                        Isolate in network
                      </button>
                    </div>
                    <ol className="small" style={{ paddingLeft: 18 }}>
                      {(c.steps ?? []).map((s: any, j: number) => (
                        <li key={j} style={{ marginBottom: 8 }}>
                          {s.text}
                          <EvidenceList list={s.evidence} compact />
                        </li>
                      ))}
                    </ol>
                  </div>
                );
              })}
              {(fr?.time_sources ?? []).length > 0 && (
                <div className="tile">
                  <h4 className="h4" style={{ marginTop: 0 }}>Time basis of each source</h4>
                  {fr.time_sources.map((t: any, i: number) => {
                    const [tone, label] = CLOCK[t.clock_issue] ?? ["gray", t.clock_issue];
                    return (
                      <div key={i} className="small" style={{ marginBottom: 12 }}>
                        <b>{t.source}</b> – {t.basis} <span className={`tag ${tone}`}>{label}</span>
                        <div className="muted">{t.note}</div>
                        <EvidenceList list={t.evidence} compact />
                      </div>
                    );
                  })}
                  <HowTo label="How are clocks handled?">
                    ALIBI converts every timestamp to Europe/Zurich using the zone the source states (Slack and card feed in UTC, emails with offset,
                    calendars with TZID or UTC). Clocks are never shifted by code. A deviation is only applied inside Bob's reconstruction when a source
                    documents it – and that source is cited.
                  </HowTo>
                </div>
              )}
            </div>
          </div>
        )}
        {fr?.knowledge_items?.length > 0 && (
          <div className="tile" style={{ marginTop: 16 }}>
            <h3>Insider knowledge – and how it could be learned legitimately</h3>
            <div className="grid g2 gap">
              {fr.knowledge_items.map((k: any) => (
                <div key={k.id}>
                  <b>{k.id}</b> {k.text}
                  <div className="small muted">Legitimate paths: {k.how_known_legitimately}</div>
                  <EvidenceList list={k.evidence} compact />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
