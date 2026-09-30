# Method — retracing the manual investigation, generically

This is how the case was solved by hand, step by step, and how each step became a stage of
the automated investigator. It deliberately contains **no case facts** (no names, times,
plates or conclusions): the system has to find those itself, and Rule 2 forbids typing them in.

## The manual steps and what they became

| # | What we did by hand | What we learned | Automated stage |
|---|---|---|---|
| 1 | Read the kickoff deck and pulled out the case frame: the asset, the incident window, why each person is on the list | The frame fits on one page; everything else hangs off it | **context** — `case.py` derives the frame from the bundle with a citation per fact |
| 2 | Reconciled the team handout: output format, citation syntax, scoring, rules | Quotes are checked automatically against the files *as received* | **verdict** — `verdict.py` builds only from verified quotes; `corpus.verify()` is the gate for everything |
| 3 | Reconciled the bundle README: sixteen sources, nine formats, a warning that timestamps are not normalised | Sources warn about themselves — those warnings are leads | **sweep / hint scan** — every "not proofread", "not normalised", "differs from", "withhold", "confidence %" becomes a check |
| 4 | Normalised timestamps by rewriting a copy of the bundle | Rewriting files shifted line numbers and changed quoted values — most citations built on the copy no longer matched the original. We also assumed one time basis per source family and missed that one exporter wrote UTC and one system clock ignored summer time | **ingest + sweep** — files are never rewritten; each record carries its own time basis; clocks are *tested* against records of the same moment (a chat message vs. a barrier exit, a purchase "on the way in" vs. an entry, a seasonal step in habitual arrival times) and corrected only with evidence and a human sign-off |
| 5 | OCR / vision on the scanned statement and photos | Image text is valuable but error-prone (umlauts, digits) | **ingest** — tesseract OCR, cached; every OCR quote is flagged and gets a human confirmation task; the viewer shows the original beside the machine text |
| 6 | Wrote open questions ("whose vehicle was that?", "who paid that receipt?") and resolved them across sources | Identity lives in different exports: chat handles, e-mail, card numbers, permits, calendars | **context (entity resolution)** + **sweep (uncertain identifications)** — witness descriptions are scored against permits and checked against the barrier log at that moment |
| 7 | Deep dive per suspect: where were they during the window? | Only the *operation* window matters (from the forensic report's own declared time base), not the wider blackout | **analyse / presence** — barrier state at window start and end, card use elsewhere inside or bracketing the window, contemporaneous chat |
| 8 | Compared each person's statements with paperwork | A self-reported narrative that the card or barrier record contradicts is the strongest single signal | **sweep (narratives)** + **analyse / statement** |
| 9 | Final clearance checks | Clearing needs positive evidence, not absence | **argue** — ⚪ only for physical impossibility; "cleared" otherwise requires exonerating records and no unexplained 🔴 |
| — | Argumentation document with 🔴 🟡 🟢 ⚪ per finding | A shared scale makes the reasoning auditable | **argue** + `05_argumentation.md` |
| — | Adversarial review of our own argument | Our review downgraded the strongest finding by assuming another interview came first — it did not. Order of events must be checked, not assumed | **adversarial** — timing check against actual interview times, vocabulary check, leave-one-analysis-out, quote re-verification |
| — | Task lists: mechanical fixes for an agent, judgement calls for a human | The split is the right one; it just has to be regenerated every run | **tasks** — agent tasks (Bob) and human tasks, with persisted decisions that feed back into the next run |
| — | Presentation verdicts | Suspicion → paperwork → judgement per suspect | `09_verdict_summary.md` and the UI's suspect view |

## The ideas that carry the method

1. **Sources as received.** Citations point at the original bytes. Normalisation lives in the
   record layer, never in the files.
2. **Inconsistencies first.** Before arguing, list every place the sources disagree with
   themselves or each other, and fix or flag it. Arguments built on an unfixed clock or an
   unresolved blurry plate are built on sand.
3. **Operation window, not blackout.** The operator had to be at a local console for a known
   stretch of time; presence is judged against that.
4. **Knowledge has a timeline.** When someone "knows what only the thief could know", ask what
   routes existed *before they said it*: public records about this very event, their own earlier
   experience written down at the time, and leaks (a conversation someone next door could hear).
   Generic vocabulary in unrelated chatter is not a route.
5. **Chat is only a lead.** Bob and any other model can propose; only a quote found at its
   source counts. The same gate applies to humans typing findings in.
6. **Honest confidence.** A transparent formula (independent pillars, margin to the next suspect,
   penalties for open judgement calls) — and a human signs it off.

## From pipeline to agent

The first version automated the manual steps as a deterministic pipeline. The method is now
split the way the manual work was actually split:

| Manual role | Now |
|---|---|
| Mechanical extraction, normalisation, cross-referencing | **Tools** — they run in seconds and turn the bundle into *proposals* (findings, inconsistencies, challenges), each with verified citations |
| Reading the proposals, judging them, following leads into other files | **The agent (Bob)** — works a playbook step by step over ACP, reviews every proposal with a note, digs deeper, adds what the tools missed, drafts the verdict |
| Judgement calls (a blurry plate, whether a wall leaks, the final confidence) | **A person** — human tasks, answered in the UI |

The playbook mirrors the manual order: frame → inconsistencies first → one suspect at a time
(suspicion → paperwork → judgement) → cross-check (who knew what, when) → try to break the case →
verdict. Each step has a machine-checkable definition of done, so the orchestrator can send the
agent back to what it skipped. The tools-only result is kept as a baseline, so the effect of the
agent's judgement is visible — and the agent is held to the same quote gate as everyone else.

## From investigation to prevention

The manual work ended with a bonus page on preventing a repeat. The Security Guard makes that a
second agent on the same framework, and runs it without suspects:

1. **Scan** the data for weaknesses the way they are actually written down — standing grants with an
   empty "revoked" column, the same security ticket filed again and again, the same warning posted in
   chat for months, statements in notes and interviews.
2. **State**: is it still open? A later record of a fix counts; a closed ticket alone does not.
3. **Root cause**: which process design keeps producing this kind of risk (grants without expiry,
   issues without escalation, controls relaxed under pressure, fixes deferred for budget, default-open
   sharing, monitoring that fails together with what it monitors). Only accepted if the data shows the
   process failure itself.
4. **Remediate**: standard practice (now / control / process / verify / owner), made specific by the
   agent, approved by a person.
5. **Link back**: risks on the incident's attack path are flagged in both agents.
