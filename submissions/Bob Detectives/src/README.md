# Bob Investigator

An agentic, citation-first investigation environment for the case bundle, with IBM Bob as the
investigator. **Tools propose, Bob decides.** The tools read every source exactly as received,
sweep for inconsistencies first and turn the bundle into *proposals*. Bob works a playbook step by
step: he reviews every proposal with a note, digs deeper where it matters, adds what the tools
missed (every quote verified), and drafts the verdict. A person makes the judgement calls. The
tools-only result is kept as a baseline, so you can see what the agent changed.

How we got here — the manual steps, retraced without case specifics — is in [METHOD.md](METHOD.md).

## Two agents, one framework

| | **Investigator** (`src/investigate`) | **Security Guard** (`src/guard`) |
|---|---|---|
| Question | Who did it, how sure, and where every piece of reasoning comes from | What is still weak today, why the process lets it happen, and what to do |
| Needs | the suspect list | nothing but the data |
| Tools propose | findings F-### per suspect (presence, statements, knowledge echoes, …) | risks S-### (stale access, audit gaps, exposed documents, physical access, …), root causes P-##, remediations M-## |
| Bob decides | reviews proposals, digs, drafts the verdict | triages risks (real? severity? still open?), confirms root causes, makes remediations specific |
| A person decides | clock/plate/leak judgements, the confidence | remediation approval, risk acceptance |
| Output | `investigation/output/` incl. `verdict.json` and `10_security_remaining.md` | `security/output/` incl. `risk_register.csv`, posture, root causes, remediation plan |

**Shared:** the corpus read exactly as received and its quote gate · typed records with their own time
basis · the inconsistency sweep · Finding/Issue/Task types · the workspace (stable IDs, reviews, steps,
journal) · `dig` · the ACP orchestrator and permission policy · the UI (switch agents in the header) ·
the tests. **Different:** the analysis layer (`analyze.py`/`argue.py` vs `security.py`), the playbook
(`playbook.py` vs `guard_playbook.py`) and the Bob mode (`investigator` vs `securityguard`).

The investigator runs the Guard's scanner too: `10_security_remaining.md` lists the weaknesses the
incident exposed that are **still in place**, the process misdesign behind them and the remediations —
with the same S-/P-/M- IDs, so a risk Bob triaged in the Guard shows up triaged in the investigation.

```bash
src/guard run                    # scan: risks, root causes, remediations (seconds)
src/guard agent run --depth normal   # Bob triages, hunts, confirms root causes, refines remediations
src/guard proposals --constraint stale-access
src/guard dig S-005
src/investigate serve --open     # both agents in one UI (header switch)
```

## The agentic workflow

```bash
src/investigate run                                   # tools produce proposals (seconds)
src/investigate agent run --depth normal              # Bob works the whole playbook (minutes)
src/investigate agent run --steps suspect:<handle> --depth deep     # …or one step
src/investigate agent dig F-012 --question "Could this record be wrong?"  # Bob goes deeper on one thing
src/investigate agent log                             # Bob's messages, commands and outputs
src/investigate serve --open                          # the same, live, in the UI (Agent view)
```

Bob is driven over ACP (`bob acp`), using your normal Bob login — no API key. The orchestrator
opens a session per step in the **Investigator** mode, gives Bob the step's goal and instructions,
lets him drive the CLI, re-runs the pipeline, checks the step's definition of done, and sends him
back to anything he skipped. Every message, command, output and permission decision is logged
(`investigation/state/sessions/`) and streamed to the UI.

**Playbook** (`src/investigate playbook`): frame → sweep (decide every inconsistency) → one step per
suspect (review every proposal, suspicion → paperwork → judgement) → crosscheck (who knew what,
when) → challenge (try to break the leading hypothesis) → verdict (a draft per suspect, a proposed
confidence for a person to sign off).

**What Bob may do.** Only `src/investigate …` commands (optionally piped into head/grep/…) and edits
to `investigation/notes/` (his case memory). Everything else is denied and shown in the trace.
Evidence only enters through `finding add` / `review --source --quote`, which reject quotes that are
not at their source.

**Modes.** `agent` (default): only findings Bob reviewed or added count; until he has reviewed
anything, `verdict.json` is the labelled tools-only baseline. `autopilot`: every proposal counts.
`verdict_baseline.json` is always written for comparison.

## Run it

```bash
src/investigate run                                  # full pipeline, ~5 s → investigation/output/verdict.json
src/investigate run --export verdict_investigator.json   # …and copy the verified verdict to the repo
src/investigate serve --open                         # local UI on http://127.0.0.1:8765
src/investigate verify verdict.json                  # check any verdict file against the bundle
src/investigate repair verdict.json --in-place       # fix its citations (backup kept, change log written)
```

Needs Python ≥ 3.10 and `pypdf` (`pip install -r src/requirements.txt`). Optional: `tesseract`
for the scanned statement and photos (`brew install tesseract`), and the IBM Bob CLI.

The bundle is auto-detected (any `*/case_bundle` directory, or a zip containing one).
A rewritten/"normalised" copy is **refused**: its line numbers and values no longer match the
files the scorer checks. Override with `--bundle PATH`.

## What comes out

`investigation/output/`

| File | |
|---|---|
| `verdict.json` | the investigator's answer — every quote re-verified after writing (export it with `run --export` / `export`; download it in the UI) |
| `verification.json` | per-quote check report |
| `context/01_case_context.md` | frame, identities, sources and their time basis |
| `context/02_inconsistencies.md` | hints + inconsistencies, each fixed/explained/handed on |
| `context/03_evidence_relevance.md` | which sources carry the case |
| `context/04_findings_log.md` | every finding with exact sources |
| `context/05_argumentation.md` | 🔴🟡🟢⚪ per suspect, constraint matrix, confidence formula |
| `context/06_adversarial.md` | the pipeline trying to break its own case |
| `context/07_tasks_agent.md` / `08_tasks_human.md` | work for Bob / decisions for a person |
| `context/09_verdict_summary.md` | suspicion → paperwork → judgement, for the pitch |
| `investigation.json` | everything above as data (the UI reads this) |

`investigation/state/` keeps human decisions (`resolutions.json`), findings added by Bob or a
person (`agent_findings.jsonl`), Bob transcripts and the OCR cache. Decisions survive re-runs.

## Pipeline

```
ingest ─► context ─► SWEEP ─► analyse ─► agent findings ─► adversarial ─► argue ─► verdict ─► report
          (frame)    (fix first)          (Bob/human, gated)                        (verified)  (docs)
```

| Stage | Module | Does |
|---|---|---|
| ingest | `corpus.py`, `records.py` | line-addressable corpus (text lines, PDF pages, xlsx rows, OCR); typed records with their own time basis |
| context | `case.py` | suspects (names from the template) → handles, e-mail, cards, plates, calendars, interviews, offices; incident & operation window; withheld facts; the secret the operator needed; the receiving party |
| **sweep** | `sweep.py` | hint scan; exporter time bases; clock tests (records of the same moment, seasonal step); speaker labels; degraded plate reads resolved by elimination; narrative vs card; leak channels; unsure witness identifications |
| analyse | `analyze.py` | presence (barrier, card, chat), interview vs records, knowledge echoes with innocent-route search, routes to the secret, links, leads |
| adversarial | `adversarial.py` | quote re-verification, absence-only clearances, vocabulary check, timing check, leave-one-analysis-out, counter-evidence |
| argue | `argue.py` | constraints per suspect, elimination, verdicts, confidence formula |
| verdict / report | `verdict.py`, `report.py` | `verdict.json` + verification + context docs |

Confidence = `min(0.95, 0.5 + 0.08·pillars + 0.10·min(margin, 2.5)) − penalties`, where pillars
are independent constraints pointing at the culprit, margin is the score gap to the next suspect
still standing, and penalties are open judgement calls the case depends on. A person signs it off
(human task) and can override it.

## Bob inside the system

- **Orchestrated** (`src/investigate agent …`, or the UI's Agent view): Bob over ACP with your login,
  step by step, live trace, completion checks, nudges.
- **Interactive** (`bob chat` in the repo, mode *Investigator*): the same tools by hand. Skills:
  `/work-playbook-step`, `/dig-deeper`, `/work-agent-task`. Rules in `.bob/rules-investigator/AGENTS.md`.
- **Headless**: `src/investigate bob A-01` (or "Send to Bob" in the UI) runs
  `bob run --mode investigator`. Needs `BOB_API_KEY`; without it the UI/CLI shows the exact prompt
  to paste into `bob chat`.
- **Chat is only a lead.** Bob can only add evidence with `investigate finding add`, which checks
  every quote against the bundle and rejects what is not there (it also tells you when the quote is
  on a different line). Accepted findings are tagged with their provenance.

## CLI (for humans and Bob)

| Command | |
|---|---|
| `src/investigate status` | culprit, confidence, per-suspect constraints, open tasks |
| `src/investigate search REGEX [--in PREFIX]` | citable hits `path:line` |
| `src/investigate show SOURCE [-C N]` | read a citation in context (`file.pdf:page`, `file.xlsx:row`, photo) |
| `src/investigate timeline [--suspect NAME] [--hours N]` | records around the operation window, clock-corrected, raw value kept |
| `src/investigate suspect NAME` | one suspect's findings |
| `src/investigate verify-quote SOURCE QUOTE` | is it really there? |
| `src/investigate verify [FILE]` | check every quote of any `verdict.json` |
| `src/investigate repair FILE [--in-place \| --out PATH]` | fix citations of any verdict file: wrong lines, quotes copied from a rewritten copy, decorated quotes. Never changes claims or verdicts; unresolvable items are left for a person |
| `src/investigate export [PATH]` | copy the investigator's verdict (re-verified; refuses if any quote fails) to PATH, default `verdict_investigator.json` |
| `src/investigate tasks [--kind human\|agent] [--all]` | the work queue |
| `src/investigate task resolve ID --decision D [--note] [--value] [--rerun]` | record a human decision |
| `src/investigate finding add …` | add a finding (quotes verified first) |
| `src/investigate bob ID [--prompt-only]` | hand an agent task to Bob (headless `bob run`, needs `BOB_API_KEY`) |
| `src/investigate playbook` / `step show\|done ID` | the steps, their open items, closing a step |
| `src/investigate frame` | the derived case frame with its sources |
| `src/investigate proposals [--suspect N] [--constraint C] [--pending]` | the tools' proposals and the decisions on them |
| `src/investigate issues [--kind sweep\|adversarial]` | inconsistencies / challenges |
| `src/investigate review ID accept\|reject\|amend\|escalate --note …` | a decision (counter-evidence with `--source/--quote`, verified) |
| `src/investigate dig TARGET` | context pack for a finding, inconsistency, suspect or citation |
| `src/investigate verdict draft …` / `confidence propose …` | the agent's verdict and confidence |
| `src/investigate note "…"` / `mode agent\|autopilot` | journal note / scoring mode |
| `src/investigate agent run\|dig\|log` | Bob over ACP |
| `src/investigate docs [NAME]` | print a generated document |

## Human verification in the UI

Every claim — findings, inconsistencies, tasks, verdict entries, even citations inside the
generated documents — is a link:

- **click the citation** → drawer with the cited line in context, the quote highlighted and its
  verification status (✓ exact, ◐ OCR, ✗ not found / wrong line → suggested line);
- **full doc ↗ / Open full document** → the whole file with original line numbers, scrolled to and
  highlighting the line; scanned PDFs and photos are shown as the original beside the OCR text;
- **Open original file** → the raw file from the bundle (PDF opens at the cited page).

Human tasks are resolved in the UI; the pipeline re-runs with the decision.

## Declared inputs (Rule 2)

Nothing about the case is typed into the code. The tests enforce it
(`test_no_suspect_names_or_identifiers_in_code`, `test_no_plates_cards_or_timestamps_typed_in`).

- **Suspect names** — read from `verdict_template.json` (given by the organisers).
- **Security vocabulary** — `investigator/security_lexicon.py`: how weaknesses are phrased in tickets,
  chat and notes (risk detectors), process-failure signals, a taxonomy of process misdesigns and standard
  remediation playbooks. General security practice; no names, systems or identifiers from the case (a test
  enforces this).
- **Search vocabulary** — `investigator/lexicon.py`, general language only: phrases that signal an
  unreliable source; paraphrases of four operational concepts (failure / deletion / restart /
  duration) matched against the investigator's own list of withheld facts; departure and
  self-location phrasing; ISO 18245 card MCC meanings; German↔English colour words and two
  German vehicle-body words; barrier-log direction words; thresholds (plate-read confidence 70 %,
  clock tolerance 20 min).
- **Heuristic weights** — finding weights and source reliabilities in `analyze.py` /
  `findings.py`, and the confidence formula above.

Every fact the pipeline uses (windows, identities, who said what when) is derived from the bundle
and carries its citation.

## Tests

```bash
python3 -m unittest discover -s src/tests -v
```

Every verdict quote is at its source; all eight judged; one culprit; confidence in range;
misleading suspects are explained, not accused; any unexplained knowledge echo predates every
leak; the answer survives leaving out any single analysis; repeat runs are identical; fake quotes
are rejected; the normalised copy is refused; no case facts in the code.

## Deploy / next steps

- Package as a container (Python + tesseract) behind the investigator's VPN; the UI already binds
  to localhost only and serves the bundle read-only.
- Swap the stdlib server for an authenticated one; keep `resolutions.json` in a signed audit log.
- Bob headless on a schedule: work agent tasks overnight, human reviews in the morning.
- Add a prevention pass (e.g. flag service accounts or roles that outlived their purpose) from the
  same records — the evidence is already indexed.
- Generalise the exporters (other chat/email/badge formats) behind the same record interface.

## Known limits

- OCR drops diacritics; OCR quotes are never used in `verdict.json` until a person confirms them.
- Phrase matching is English/German; other languages need vocabulary.
- Weights are judgement encoded as numbers; they are visible, tested for robustness, and a person
  signs off the final confidence.
