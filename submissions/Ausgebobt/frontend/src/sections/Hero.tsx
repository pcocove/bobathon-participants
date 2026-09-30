import type { Status } from "../api";
import { fmt } from "../api";
import { HowTo } from "../components/Evidence";

const RULES: [string, string][] = [
  ["Missing exoneration is not proof of guilt.", "A missing alibi alone never makes someone the culprit."],
  ["Statements are statements.", "Interviews are treated as claims until documents support them."],
  ["A booking is not presence.", "A calendar entry shows an appointment, not who was actually there."],
  ["Vehicle ≠ driver, card ≠ payer.", "Plate and card logs prove the vehicle or card, not the person."],
  ["Same event ≠ independent confirmation.", "Several documents about one event do not count twice."],
  ["Open may stay open.", "An explained suspicion is not automatically a full exoneration."],
];

export function Hero({ status, inventory, exportState }: { status: Status | null; inventory: any; exportState: any }) {
  const cov = inventory?.coverage;
  const meta = status?.meta ?? {};
  const job = status?.job;
  const rep = exportState?.report;
  const pct = cov ? Math.round((100 * cov.units_reviewed) / Math.max(1, cov.units_total)) : null;
  return (
    <>
      <section className="lead-space" id="alibi">
        <div className="inner">
          <div className="eyebrow">
            <b>01</b>The problem and the principle
          </div>
          <h1>
            <strong>ALIBI</strong>
          </h1>
          <div className="claim">Exoneration first. Evidence decides.</div>
          <p>
            A model was copied during the one window when nothing was recording. The investigator hands over an unsorted case file and eight people who
            could have done it. Ask an AI "who did it?" and you get a name. ALIBI first asks why the others <b>didn't</b> – and backs every answer with an
            original passage.
          </p>
          <div className="question">"Which verifiable explanation could exonerate this person or explain the suspicious evidence against them?"</div>
          <div className="cta">
            <a className="btn primary" href="#files">
              Explore the evidence network <span>→</span>
            </a>
            <a className="btn" href="#verdict">
              See the verdict <span>→</span>
            </a>
          </div>
          <div className="kpis">
            <div className="kpi">
              <div className="v">{fmt.int(cov?.files_discovered)}</div>
              <div className="k">files in nine formats</div>
            </div>
            <div className="kpi">
              <div className="v">{fmt.int(cov?.units_total)}</div>
              <div className="k">information units, each tied to its original line</div>
            </div>
            <div className="kpi">
              <div className="v">{pct === null ? "—" : `${pct}%`}</div>
              <div className="k">of all units reviewed by IBM Bob</div>
            </div>
            <div className="kpi">
              <div className="v">{rep ? `${rep.verified_quotes}/${rep.total_quotes}` : "—"}</div>
              <div className="k">exported quotes verified verbatim at their source</div>
            </div>
          </div>
          <HowTo label="Where do these four numbers come from?">
            Files: every file found in the case bundle. Units: ALIBI's parser splits each file into meaningful pieces (one email, one Slack message, one
            ticket with its comments, one calendar event, one interview question-and-answer, one table row, one PDF page, one photo). Reviewed: units
            that were inside a labeling package Bob answered validly (plus the three images read by Bob Vision). Verified quotes: an independent
            validator re-opens the original files and checks that each exported quote is literally at the cited line, page or row.
          </HowTo>
        </div>
      </section>
      <section className="sec alt">
        <div className="inner">
          <div className="eyebrow">How ALIBI reasons</div>
          <h2>Six rules the system is not allowed to break</h2>
          <div className="rules">
            {RULES.map(([a, b]) => (
              <div className="rule" key={a}>
                <b>{a}</b>
                {b}
              </div>
            ))}
          </div>
          <div className="pipeline" aria-label="Analysis pipeline">
            {(status?.stages ?? []).map((s, i) => {
              const done = !!meta[s.key];
              const run = job?.status === "running" && job.stage === s.key;
              return (
                <div key={s.key} className={`pstep ${done ? "done" : ""} ${run ? "run" : ""}`}>
                  <div className="n">{String(i + 1).padStart(2, "0")}</div>
                  <div className="t">{s.label}</div>
                  <div className="s">{run ? `running · ${job!.done}/${job!.total}` : done ? "✓ done with IBM Bob" : "pending"}</div>
                </div>
              );
            })}
          </div>
          <p className="small muted" style={{ marginTop: 16 }}>
            Steps 1–7 are stored IBM Bob requests (Bob Shell via the Agent Client Protocol). Parsing, quote verification, weight normalisation and export
            validation are deterministic code.
          </p>
        </div>
      </section>
    </>
  );
}
