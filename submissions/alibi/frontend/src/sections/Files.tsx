import { useState } from "react";
import { fmt, post, type Person, type Status } from "../api";
import { HowTo } from "../components/Evidence";
import { GraphView } from "../components/GraphView";

type Props = { status: Status | null; inventory: any; persons: Person[]; analysis: any; onStatus: () => void };

export function Files({ status, inventory, persons, analysis, onStatus }: Props) {
  const cov = inventory?.coverage;
  const job = status?.job;
  const running = job?.status === "running";
  const [msg, setMsg] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const bob = status?.bob;
  const preview = !analysis?.meta?.label;
  const ro = !!status?.readonly;

  const run = async () => {
    setMsg(null);
    try {
      await post("api/analysis/run", { stages: null, force: false });
      onStatus();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  const check = async () => {
    setChecking(true);
    try {
      await post("api/bob/check");
    } finally {
      setChecking(false);
      onStatus();
    }
  };
  const allDone = cov?.all_processed;
  const pct = (a: number, b: number) => `${Math.round((100 * a) / Math.max(1, b))}%`;

  return (
    <section className="sec" id="files">
      <div className="inner">
        <div className="eyebrow">
          <b>02</b>The files
        </div>
        <h2>What was read – and the whole case as one network</h2>
        <p className="lead">
          Every file appears in the inventory, even if processing is pending. Every piece of information stays connected to its original line. Bob
          labels the entire file in packages; anything Bob does not report counts as reviewed and unremarkable – not as deleted.
        </p>

        <div className="grid g4" style={{ marginBottom: 1 }}>
          <div className="stat">
            <div className="v">{fmt.int(cov?.files_discovered)}</div>
            <div className="k">files discovered</div>
          </div>
          <div className="stat">
            <div className="v">{fmt.int(cov?.files_parsed)}</div>
            <div className="k">parsed successfully · {fmt.int(cov?.files_failed ?? 0)} failed</div>
          </div>
          <div className="stat">
            <div className="v">
              {fmt.int(cov?.units_reviewed)}
              <small> / {fmt.int(cov?.units_total)}</small>
            </div>
            <div className="k">units reviewed by IBM Bob</div>
            <div className="bar" style={{ marginTop: 8 }}>
              <i style={{ width: cov ? pct(cov.units_reviewed, cov.units_total) : 0 }} />
            </div>
          </div>
          <div className="stat">
            <div className="v">{fmt.int(cov?.units_labeled)}</div>
            <div className="k">labeled as relevant · {fmt.int(cov?.files_pending)} files pending</div>
          </div>
        </div>
        <div className="tile" style={{ marginBottom: 16 }}>
          <HowTo label="How are these numbers produced?">
            <b>Files</b>: recursive scan of the case bundle. <b>Parsed</b>: a format-specific parser (Markdown, Slack JSON, Jira JSON, mbox, iCalendar,
            CSV, Excel, PDF, images) read the file without error. <b>Units</b>: the parser splits files into information units, each keeping its exact
            original line range. <b>Reviewed by Bob</b>: the unit was inside one of 36 labeling packages that Bob answered with a valid result (images:
            read by Bob Vision). <b>Labeled as relevant</b>: Bob explicitly reported the unit with a relevance, tags and claims – each claim has a quote
            that ALIBI verified against the file.
          </HowTo>
        </div>
        {cov && (
          <div className={`notice ${allDone ? "ok" : "warn"}`} style={{ marginBottom: 32 }}>
            <div>
              {allDone ? (
                <>
                  <b>All data processed:</b> every unit was parsed and reviewed by Bob.
                </>
              ) : (
                <>
                  <b>Not all data processed yet:</b> {fmt.int(cov.units_total - cov.units_reviewed)} units have not been reviewed by Bob.
                </>
              )}
              {inventory?.rejected ? ` ${inventory.rejected} of Bob's statements were rejected during checking (e.g. quote not found in the file).` : ""}
            </div>
          </div>
        )}

        <div className="grid g2 gap" style={{ marginBottom: 32 }}>
          <div className="tile">
            <h3>Inventory by document type</h3>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Files</th>
                  <th>Units</th>
                  <th>Reviewed</th>
                  <th>Labeled</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(inventory?.by_type ?? {})
                  .sort((a: any, b: any) => b[1].units - a[1].units)
                  .map(([t, v]: any) => (
                    <tr key={t}>
                      <td>{t}</td>
                      <td>{v.files}</td>
                      <td>{fmt.int(v.units)}</td>
                      <td>
                        <div className="bar" style={{ width: 80, display: "inline-block", verticalAlign: "middle", marginRight: 8 }}>
                          <i style={{ width: pct(v.reviewed, v.units) }} />
                        </div>
                        <span className="tiny muted">{pct(v.reviewed, v.units)}</span>
                      </td>
                      <td>{fmt.int(v.labeled)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            <details className="more tech">
              <summary>All {inventory?.files?.length ?? 0} files individually</summary>
              <div className="scroll" style={{ marginTop: 8 }}>
                <table className="tbl">
                  <tbody>
                    {(inventory?.files ?? []).map((f: any) => (
                      <tr key={f.file}>
                        <td className="mono tiny">{f.file}</td>
                        <td className="tiny">{f.status}</td>
                        <td className="tiny">{f.units} units</td>
                        <td className="tiny muted">{f.content_status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </div>

          <div className="tile">
            <div className="spread">
              <h3>Analysis with IBM Bob</h3>
              {!ro && (
                <span className={`tag ${bob?.connected ? "green" : "red"}`}>{bob?.connected ? `Connected · ${bob.version ?? ""}` : "Not connected"}</span>
              )}
            </div>
            <p className="small muted">{bob?.detail}</p>
            {!bob?.connected && bob && !ro && (
              <div className="notice warn" style={{ marginBottom: 12 }}>
                <div>
                  Setup: install Bob Shell, run <code>bob</code> once in a terminal and sign in via SSO, then press "Check connection". Without Bob,
                  ALIBI only shows a labelled preview and produces no competition submission.
                </div>
              </div>
            )}
            {!ro && (
              <div className="row tech" style={{ marginBottom: 12, gap: 1 }}>
                <button className="btn primary" disabled={running || !bob?.connected} onClick={run}>
                  Start / continue analysis <span>→</span>
                </button>
                <button className="btn tertiary" disabled={checking} onClick={check}>
                  {checking ? "Checking …" : "Check connection"}
                </button>
                {running && (
                  <button className="btn danger" onClick={() => post("api/analysis/cancel").then(onStatus)}>
                    Cancel
                  </button>
                )}
              </div>
            )}
            {!ro && (
              <div className="small muted tech">
                "Continue" only runs stages without a stored result – finished stages cost nothing. Zoom, filters, search and opening evidence never
                call Bob.
              </div>
            )}
            {msg && (
              <div className="notice bad" style={{ marginTop: 8 }}>
                <div>{msg}</div>
              </div>
            )}
            {job && !ro && (
              <div style={{ marginTop: 16 }}>
                <div className="spread small">
                  <span>
                    Last job: <b>{job.status}</b>
                    {job.stage_label ? ` · ${job.stage_label}` : ""}
                  </span>
                  <span className="mono tiny">{job.total ? `${job.done}/${job.total}` : ""}</span>
                </div>
                <div className="progress" style={{ margin: "8px 0" }}>
                  <i style={{ width: job.total ? `${(100 * job.done) / job.total}%` : running ? "5%" : "100%" }} />
                </div>
                {job.error && (
                  <div className="notice bad">
                    <div>{job.error}</div>
                  </div>
                )}
                <div className="log tech">
                  {job.log.slice(-12).map((l, i) => (
                    <div key={i}>{l.msg}</div>
                  ))}
                </div>
              </div>
            )}
            <h4 className="h4">Usage (as recorded by Bob Shell)</h4>
            <div className="kv">
              <div>Bob requests</div>
              <div>
                {fmt.int(status?.ledger.calls)} ({fmt.int(status?.ledger.ok)} successful, {fmt.int(status?.ledger.errors)} errors)
              </div>
              <div>Cost</div>
              <div>
                {status ? fmt.num(status.ledger.cost_total, 2) : "—"} <span className="muted tiny">Bob's own unit</span>
              </div>
            </div>
            <HowTo label="Where does the cost figure come from?">
              Bob Shell writes the cost and context size of every session into its local task database. ALIBI reads that value (read-only) after each
              request and adds it up. We do not convert it into money or credits.
            </HowTo>
          </div>
        </div>

        <div id="netz" style={{ scrollMarginTop: 56 }}>
          <div className="spread" style={{ marginBottom: 12 }}>
            <h3 style={{ fontSize: 28, lineHeight: "36px" }}>Evidence network</h3>
            <span className="small muted">
              {preview ? "Preview without Bob labels" : "Every unit · Bob labels with verified quotes"} · positions stay fixed when filtering
            </span>
          </div>
          <GraphView persons={persons} analysis={analysis} preview={preview} />
          <HowTo label="How is the network built?">
            Outer ring: one circle per source (file, Slack channel, calendar, Jira project); every dot is one information unit, the most relevant in the
            middle. Centre: the people. Purple ring: entities Bob recognised (places, systems, vehicles). Lines appear only when you select something:
            person links come from IDs, aliases, plates and cardholders; typed relations come from Bob labels and only exist if their quote was found
            verbatim in the file.
          </HowTo>
        </div>
      </div>
    </section>
  );
}
