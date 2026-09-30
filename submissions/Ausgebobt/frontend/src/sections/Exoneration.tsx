import { fmt, type Person } from "../api";
import { EvidenceList, HowTo, StatusPill, unitsOf } from "../components/Evidence";
import { CONCLUSION, CONDITIONS, EXPLANATION, SUSPICION_TYPE, VERDICT } from "../labels";
import { showInGraph } from "../store";

export function Exoneration({ analysis, persons }: { analysis: any; persons: Person[] }) {
  const sus = analysis?.suspects ?? [];
  return (
    <section className="sec alt" id="exoneration">
      <div className="inner">
        <div className="eyebrow">
          <b>03</b>Exoneration first
        </div>
        <h2>Eight case files – every explanation checked</h2>
        <p className="lead">
          For every person Bob first looks for the innocent, verifiable explanation of whatever looks suspicious – months before or weeks after the
          incident, in other files and formats. Red: what looks suspicious. Teal: the explanation and its evidence. "Suspicion explained" is not the
          same as "cleared".
        </p>
        <div className="grid g2 gap">
          {sus.map((s: any) => (
            <Dossier
              key={s.id}
              id={s.id}
              name={s.name}
              data={analysis?.persons?.[s.id]}
              fin={analysis?.final?.persons?.find((p: any) => p.id === s.id)}
              person={persons.find((p) => p.id === s.id)}
            />
          ))}
        </div>
        <div className="tile" style={{ marginTop: 16 }}>
          <HowTo label="How is the exoneration confidence calculated?">
            It is not computed by a formula. In the person review Bob receives the person's interview, all units linked to them (IDs, email, plate,
            cardholder, calendar), the units around the incident window and search hits it requested itself. The prompt defines the value as "how well
            the exoneration is documented, from 0 (none) to 1". Bob sets it together with its reasoning (shown under "Full review"); ALIBI only checks
            that it is a number between 0 and 1 and that at least 60 % of the quotes behind it are verbatim in the files. It is a reasoned model
            estimate, not a probability.
          </HowTo>
        </div>
      </div>
    </section>
  );
}

function Dossier({ id, name, data, fin, person }: { id: string; name: string; data: any; fin: any; person?: Person }) {
  const r = data?.result;
  const [tone, label] = r ? CONCLUSION[r.conclusion] ?? ["gray", r.conclusion] : ["gray", "Not evaluated yet"];
  const conf = r?.exoneration_confidence;
  const allUnits = r
    ? [
        `p:${id}`,
        ...unitsOf((r.suspicious ?? []).flatMap((x: any) => x.evidence)),
        ...unitsOf((r.explanations ?? []).flatMap((x: any) => [...(x.evidence ?? []), ...(x.contra ?? [])])),
      ]
    : [`p:${id}`];
  return (
    <article className={`dossier ${tone}`} id={`dossier-${id}`}>
      <div className="spread" style={{ alignItems: "flex-start" }}>
        <div>
          <h3>{name}</h3>
          <div className="small muted">{person?.titles?.[0]?.value ?? ""}</div>
        </div>
        <StatusPill tone={tone}>{label}</StatusPill>
      </div>
      <div className="meter" title="How well is the exoneration documented? Reasoned model estimate by Bob, not a calibrated probability.">
        <div>
          <div className="label">Exoneration confidence</div>
          <div className="bar" style={{ marginTop: 6 }}>
            <i className="teal" style={{ width: conf != null ? `${conf * 100}%` : 0 }} />
          </div>
        </div>
        <b>{fmt.num(conf)}</b>
      </div>
      {fin && (
        <div className="small">
          Final verdict: <span className={`tag ${VERDICT[fin.verdict]?.[0] ?? ""}`}>{VERDICT[fin.verdict]?.[1] ?? fin.verdict}</span>
        </div>
      )}
      {!r && (
        <div className="notice">
          <div>This person has not been evaluated yet. No numbers or assessments are shown.</div>
        </div>
      )}
      {data?.error && (
        <div className="notice bad">
          <div>Bob error: {data.error}</div>
        </div>
      )}
      {r && (
        <>
          <p style={{ margin: 0 }}>{r.summary_de}</p>
          <div className="row">
            <button className="btn tertiary sm" onClick={() => showInGraph({ title: `Case file ${name}`, nodes: allUnits, kind: "person" }, `p:${id}`)}>
              Show evidence in network
            </button>
            {data.requests?.length > 0 && (
              <span className="tag purple" title={data.requests.map((q: any) => q.query).join(" · ")}>
                Bob requested {data.requests.length} searches
              </span>
            )}
          </div>
          {(r.suspicious ?? []).slice(0, 2).map((s: any) => (
            <Suspicion key={s.id} s={s} expl={(r.explanations ?? []).filter((x: any) => x.for === s.id)} />
          ))}
          <details className="more">
            <summary>Full review ({(r.suspicious ?? []).length} points of suspicion, conditions, uncertainties)</summary>
            {(r.suspicious ?? []).slice(2).map((s: any) => (
              <Suspicion key={s.id} s={s} expl={(r.explanations ?? []).filter((x: any) => x.for === s.id)} />
            ))}
            <h4 className="h4">What remains possible?</h4>
            <div className="kv small">
              {CONDITIONS.map(([k, l]) => (
                <div key={k} style={{ display: "contents" }}>
                  <div>{l}</div>
                  <div>{r.conditions?.[k] ?? "—"}</div>
                </div>
              ))}
            </div>
            {(r.remaining ?? []).length > 0 && (
              <>
                <h4 className="h4">Remaining incriminating points</h4>
                {r.remaining.map((x: any, i: number) => (
                  <div key={i} className="susp" style={{ marginBottom: 8 }}>
                    {x.text}
                    <EvidenceList list={x.evidence} compact />
                  </div>
                ))}
              </>
            )}
            <h4 className="h4">Why this confidence</h4>
            <p className="small">{r.confidence_reason}</p>
            {(r.uncertainties ?? []).length > 0 && (
              <>
                <h4 className="h4">Uncertainties</h4>
                <ul className="small">
                  {r.uncertainties.map((u: string, i: number) => (
                    <li key={i}>{u}</li>
                  ))}
                </ul>
              </>
            )}
            {data.requests?.length > 0 && (
              <>
                <h4 className="h4">Searches Bob requested before deciding</h4>
                <ul className="small">
                  {data.requests.map((q: any, i: number) => (
                    <li key={i}>
                      <span className="mono">{q.query}</span> – {q.why}{" "}
                      <span className="muted">
                        ({q.results?.length ?? 0} new passages{q.already_in_context?.length ? `, ${q.already_in_context.length} already provided` : ""})
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <div className="tiny muted">
              Bob request {data.call}
              {data.reused ? " (stored result)" : ""} · {data.context_units} units in context
            </div>
          </details>
        </>
      )}
    </article>
  );
}

function Suspicion({ s, expl }: { s: any; expl: any[] }) {
  return (
    <div>
      <div className="susp">
        <div className="blocklabel" style={{ color: "var(--red)" }}>
          Looks suspicious{s.type ? ` · ${SUSPICION_TYPE[s.type] ?? s.type}` : ""}
        </div>
        <div>{s.text}</div>
        <EvidenceList list={s.evidence} compact />
      </div>
      {expl.map((x, i) => {
        const [tone, label] = EXPLANATION[x.status] ?? ["gray", x.status];
        return (
          <div key={i} className={`expl ${x.status === "belegt" ? "" : "weak"}`}>
            <div className="blocklabel" style={{ color: tone === "teal" ? "var(--teal)" : "var(--yellow-text)" }}>
              Explanation · {label}
            </div>
            <div>{x.text}</div>
            <EvidenceList list={x.evidence} compact />
            {(x.contra ?? []).length > 0 && (
              <>
                <div className="blocklabel" style={{ marginTop: 8 }}>
                  Speaks against it
                </div>
                {x.contra.map((c: any, j: number) => (
                  <div key={j} className="small">
                    {c.text}
                    <EvidenceList list={[c]} compact />
                  </div>
                ))}
              </>
            )}
          </div>
        );
      })}
      {!expl.length && <div className="expl weak small">No innocent explanation found.</div>}
    </div>
  );
}
