import { useEffect, useState } from "react";
import { fmt, get, post, type Status } from "../api";
import { EvidenceList, HowTo, StatusPill, unitsOf } from "../components/Evidence";
import { VERDICT, who } from "../labels";
import { showInGraph } from "../store";

export function Verdict({ analysis, status, exportState, onExport }: { analysis: any; status: Status | null; exportState: any; onExport: () => void }) {
  const f = analysis?.final;
  const sus: { id: string; name: string }[] = analysis?.suspects ?? [];
  const name = (h: string) => sus.find((s) => s.id === h)?.name ?? h;
  const w = f?.weights_normalized ?? {};
  const why = Object.fromEntries((f?.weights ?? []).map((x: any) => [x.id, x.why]));
  const order = [...sus].sort((a, b) => (w[b.id] ?? 0) - (w[a.id] ?? 0));
  const x = f?.crosscheck;
  const lead = f?.persons?.find((p: any) => p.id === f?.leading);
  return (
    <section className="sec alt" id="verdict">
      <div className="inner">
        <div className="eyebrow">
          <b>05</b>The verdict
        </div>
        <h2>Leading hypothesis, confidence and all eight assessments</h2>
        <p className="lead">
          Three numbers, three meanings. <b>Estimated culpability</b> compares the eight hypotheses relative to each other. <b>Verdict confidence</b>{" "}
          says how well the verdict holds up after the cross-check. <b>Exoneration confidence</b> is in each case file. All are reasoned estimates by
          IBM Bob – not calibrated probabilities.
        </p>
        {!f && (
          <div className="notice">
            <div>No verdict yet. Leading hypothesis: — · Verdict confidence: — · Assessments: not evaluated yet.</div>
          </div>
        )}
        {f && (
          <>
            <div className="verdict-hero">
              <div className="tile" style={{ padding: 24 }}>
                <div className="label">Leading hypothesis</div>
                <h3 style={{ fontSize: 42, lineHeight: "50px", fontWeight: 300, margin: "8px 0" }}>{name(f.leading)}</h3>
                <p className="small">{lead?.reasoning_de}</p>
                <div className="row" style={{ alignItems: "flex-end", gap: 32, marginTop: 16 }}>
                  <div>
                    <div className="label">Verdict confidence (after cross-check)</div>
                    <div className="bignum">{fmt.num(f.verdict_confidence)}</div>
                  </div>
                  <div className="small muted" style={{ maxWidth: 420 }}>
                    Before the cross-check: {fmt.num(f.verdict_confidence_synthesis)}. {f.confidence_reason}
                  </div>
                </div>
                <HowTo label="How is the verdict confidence calculated?">
                  Two Bob requests. (1) The verdict step sees all eight reviews and estimates how well the verdict holds up (0–1). (2) A separate
                  cross-check request is told to attack the verdict as hard as possible with evidence; it returns a revised value. ALIBI uses the revised
                  value – this is the <code>confidence</code> in verdict.json. It is not derived from the weights.
                </HowTo>
                {(f.merge_notes ?? []).length > 0 && (
                  <div className="notice warn" style={{ marginTop: 16 }}>
                    <div>
                      {f.merge_notes.map((n: string, i: number) => (
                        <div key={i}>{n}</div>
                      ))}
                    </div>
                  </div>
                )}
                <button
                  className="btn tertiary sm"
                  style={{ marginTop: 16 }}
                  onClick={() => showInGraph({ title: `Evidence: ${name(f.leading)}`, nodes: [`p:${f.leading}`, ...unitsOf(lead?.evidence)], kind: "person" }, `p:${f.leading}`)}
                >
                  Show evidence in network
                </button>
              </div>
              <div className="tile" style={{ padding: 24 }}>
                <div className="label">Estimated culpability (relative, sums to 1)</div>
                <div style={{ marginTop: 12 }}>
                  {order.map((s) => (
                    <div key={s.id} className={`wbar ${s.id === f.leading ? "lead" : ""}`} title={why[s.id]}>
                      <span>{s.name}</span>
                      <div className="bar">
                        <i style={{ width: `${(w[s.id] ?? 0) * 100}%` }} />
                      </div>
                      <b className="mono" style={{ textAlign: "right" }}>{fmt.num(w[s.id])}</b>
                    </div>
                  ))}
                </div>
                <HowTo label="How are these weights calculated?">
                  In the verdict step Bob assigns every person a raw weight with a one-sentence reason (hover a bar). ALIBI divides each raw weight by
                  the sum of all eight so they add up to 1. This compares the hypotheses under the assumption that one of the eight did it – a high
                  weight is not a probability of guilt and does not raise the verdict confidence.
                </HowTo>
                <div className="tiny muted" style={{ marginTop: 8 }}>{f.weights_basis}</div>
              </div>
            </div>

            {x && (
              <div className="tile" style={{ marginTop: 16, padding: 24 }}>
                <div className="spread">
                  <h3 style={{ margin: 0 }}>Cross-check: the strongest alternative</h3>
                  <StatusPill tone={x.holds ? "teal" : "red"}>{x.holds ? "Hypothesis holds" : "Hypothesis does not hold"}</StatusPill>
                </div>
                <p>
                  <b>{who(x.strongest_alternative?.person, name)}:</b> {x.strongest_alternative?.argument}
                </p>
                <EvidenceList list={x.strongest_alternative?.evidence} compact />
                {(x.weak_points ?? []).length > 0 && (
                  <>
                    <h4 className="h4">Weak points of the verdict</h4>
                    {x.weak_points.map((p: any, i: number) => (
                      <div key={i} className="small" style={{ marginBottom: 8 }}>
                        • {p.text}
                        <EvidenceList list={p.evidence} compact />
                      </div>
                    ))}
                  </>
                )}
                <div className="small muted">{x.reason}</div>
              </div>
            )}

            <div className="tile" style={{ marginTop: 16, padding: 24 }}>
              <h3>All eight assessments</h3>
              <table className="tbl vtable">
                <thead>
                  <tr>
                    <th>Person</th>
                    <th>Status</th>
                    <th>Reasoning</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {sus.map((s) => {
                    const p = f.persons?.find((q: any) => q.id === s.id);
                    const pr = analysis?.persons?.[s.id]?.result;
                    const [tone, label] = VERDICT[p?.verdict] ?? ["gray", "Not evaluated"];
                    return (
                      <tr key={s.id}>
                        <td>{s.name}</td>
                        <td>
                          <StatusPill tone={tone}>{label}</StatusPill>
                          <div className="tiny muted" style={{ marginTop: 4 }}>Exoneration confidence {fmt.num(pr?.exoneration_confidence)}</div>
                          {p?.revised_by_crosscheck && <div className="tiny" style={{ color: "var(--red)" }}>changed by cross-check</div>}
                        </td>
                        <td className="small">{p?.reasoning_de}</td>
                        <td style={{ minWidth: 320 }}>
                          <EvidenceList list={p?.evidence} compact empty="no evidence" />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="grid g2 gap" style={{ marginTop: 16 }}>
              <div className="tile" style={{ padding: 24 }}>
                <h3>Suspicions that were explained</h3>
                {(f.dismissed ?? []).map((d: any, i: number) => (
                  <div key={i} style={{ marginBottom: 12 }}>
                    <b>{name(d.person)}</b>: <span className="muted">{d.suspicion}</span>
                    <div className="small">→ {d.explanation}</div>
                    <EvidenceList list={d.evidence} compact />
                  </div>
                ))}
              </div>
              <div className="tile" style={{ padding: 24 }}>
                <h3>Open questions</h3>
                <ul>
                  {(f.open_questions ?? []).map((q: string, i: number) => (
                    <li key={i} className="small" style={{ marginBottom: 4 }}>
                      {q}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <RunsCompare sus={sus} />
          </>
        )}
        <ExportPanel ready={!!f} status={status} d={exportState} onExport={onExport} />
      </div>
    </section>
  );
}

const VSHORT: Record<string, string> = { cleared: "cleared", unresolved: "open", culprit: "hypothesis" };

function RunsCompare({ sus }: { sus: { id: string; name: string }[] }) {
  const [runs, setRuns] = useState<any[]>([]);
  useEffect(() => {
    get("api/runs").then(setRuns).catch(() => setRuns([]));
  }, []);
  if (runs.length < 2) return null;
  const label = (n: string) => (n === "run1" ? "Run 1 · no source requests" : n === "run2" ? "Run 2 · with source requests" : n);
  return (
    <div className="tile" style={{ marginTop: 16, padding: 24 }}>
      <h3>Stability across repeated runs</h3>
      <p className="small muted">
        The same pipeline, executed again with IBM Bob. Run 2 added a mandatory step in which Bob requests extra source passages before deciding.
        Differences show how much the result depends on the model's estimate.
      </p>
      <table className="tbl">
        <thead>
          <tr>
            <th>Person</th>
            {runs.map((r) => (
              <th key={r.name}>{label(r.name)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sus.map((s) => (
            <tr key={s.id}>
              <td>{s.name}</td>
              {runs.map((r) => {
                const p = r.persons[s.id] ?? {};
                return (
                  <td key={r.name} className="small">
                    <b>{VSHORT[p.verdict] ?? "—"}</b>{" "}
                    <span className="muted">
                      · exon. {fmt.num(p.exo)} · weight {fmt.num(p.weight)}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
          <tr>
            <td>
              <b>Verdict confidence</b>
            </td>
            {runs.map((r) => (
              <td key={r.name}>
                <b>{fmt.num(r.confidence)}</b>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function ExportPanel({ ready, status, d, onExport }: { ready: boolean; status: Status | null; d: any; onExport: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const rep = d?.report;
  const write = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await post("api/export/write");
      setMsg(`Written: ${r.path}`);
      onExport();
    } catch (e: any) {
      setMsg(`Not written: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="tile" style={{ marginTop: 16, padding: 24 }} id="export">
      <div className="spread">
        <h3 style={{ margin: 0 }}>Competition submission · verdict.json</h3>
        {d?.draft && <StatusPill tone={rep?.valid ? "teal" : "red"}>{rep?.valid ? "Valid and source-verified" : "Not valid"}</StatusPill>}
      </div>
      {!d?.draft && (
        <div className="notice" style={{ marginTop: 12 }}>
          <div>{ready ? "Building export …" : "Before a real analysis there is no export – not even a placeholder."}</div>
        </div>
      )}
      {d?.draft && (
        <>
          <p className="small muted">
            {d.written
              ? d.written_matches_draft
                ? `Final file is at ${d.path} and matches this state.`
                : `DRAFT – differs from the written file ${d.path}.`
              : `DRAFT – not yet written to ${d.path}.`}{" "}
            Independent validator: {rep?.verified_quotes}/{rep?.total_quotes} quotes found verbatim at their source.
          </p>
          <HowTo label="What does the validator check?">
            It re-reads the template and the original files itself (not the pipeline's data): exactly the template's fields, all eight names once, valid
            verdict codes, one culprit that matches the person verdicts, confidence between 0 and 1, and for every piece of evidence that the file exists,
            the line/page/row exists and the quote is literally there. A cleared person without verified evidence is rejected.
          </HowTo>
          {rep?.errors?.length > 0 && (
            <div className="notice bad" style={{ marginTop: 8 }}>
              <div>
                {rep.errors.slice(0, 12).map((e: string, i: number) => (
                  <div key={i}>✕ {e}</div>
                ))}
              </div>
            </div>
          )}
          {rep?.warnings?.length > 0 && (
            <div className="notice warn" style={{ marginTop: 8 }}>
              <div>
                {rep.warnings.map((e: string, i: number) => (
                  <div key={i}>! {e}</div>
                ))}
              </div>
            </div>
          )}
          {(d.notes ?? []).length > 0 && (
            <details className="more tech">
              <summary>Safety rules applied during export ({d.notes.length})</summary>
              <ul className="small">
                {d.notes.map((n: string, i: number) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </details>
          )}
          <div className="row" style={{ marginTop: 16, gap: 1 }}>
            {!status?.readonly && (
              <button className="btn primary tech" disabled={!rep?.valid || busy} onClick={write}>
                Write final file to team folder <span>→</span>
              </button>
            )}
            <a className="btn tertiary" href={rep?.valid ? "api/export/download" : undefined} aria-disabled={!rep?.valid}>
              Download verdict.json
            </a>
          </div>
          {msg && (
            <div className="small" style={{ marginTop: 8 }}>
              {msg}
            </div>
          )}
          <details className="more">
            <summary>View export content</summary>
            <pre className="orig" style={{ padding: 12, maxHeight: 420, overflow: "auto" }}>{JSON.stringify(d.draft, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}
