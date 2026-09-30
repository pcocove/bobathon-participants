"""The Security Guard's playbook — same shape as the investigator's (steps_for / progress / find).

scope → triage:<category> (one per risk category) → hunt → rootcause → remediate → challenge → report
"""

from __future__ import annotations

from .playbook import Step

CLI = "src/guard"


def _risks(state: dict) -> list[dict]:
    return [f for f in state["findings"] if (f.get("meta") or {}).get("kind") == "risk" and f["status"] != "withdrawn"]


def steps_for(state: dict) -> list[Step]:
    cats = sorted({(f.get("meta") or {}).get("category") for f in _risks(state) if f["stage"] in ("sweep", "analyse")})
    out = [Step("scope", "Scope the scan",
                "Understand what data was scanned, what the posture looks like and which records can be trusted.",
                f"""1. Run `{CLI} status` and `{CLI} issues --kind sweep` (records that disagree or warn about themselves).
2. Decide each inconsistency: `{CLI} review I-xx accept|reject|escalate --note "..."` — can this record be used as security evidence?
3. Write what the organisation is, which systems appear in the data and the scan's limits into
   investigation/notes/security_memory.md.
4. `{CLI} step done scope --summary "..."`""")]
    for c in cats:
        out.append(Step(
            f"triage:{c}", f"Triage: {c}",
            f"Decide for every '{c}' risk whether it is real, how severe, and whether it is still open.",
            f"""1. `{CLI} proposals --constraint {c}` — the tools' risk proposals (S-xxx) with severity and state.
2. For each: `{CLI} dig S-xxx`, check the sources, then decide:
   - real as proposed: `{CLI} review S-xxx accept --note "..."`
   - real but different: `{CLI} review S-xxx amend --severity critical|high|medium|low --state open|addressed --note "..."`
   - not a security risk / duplicate: `{CLI} review S-xxx reject --note "..."`
3. Is it still open? Search for a later record of a fix (`{CLI} search "<subject>"`). A closed ticket is not proof;
   a later line showing the control working is.
4. `{CLI} step done triage:{c} --summary "..."`"""))
    out += [
        Step("hunt", "Hunt for what the tools missed",
             "Find weaknesses the detectors did not catch: other systems, other phrasings, other sources.",
             f"""1. Search the data for weak spots in other words: shared accounts, exceptions granted "temporarily", data
   leaving via e-mail or personal devices, vendors with standing access, monitoring that nobody reads.
   (`{CLI} search "<regex>" --in <prefix>`, `{CLI} show <path:line> -C 5`)
2. Add each real risk: `{CLI} finding add --category <category> --severity <sev> --state open --subject "<system/account>"
   --title "..." --claim "..." --source <path:line> --quote "<exact text>"` (the quote is verified).
3. `{CLI} step done hunt --summary "..."`"""),
        Step("rootcause", "Root causes: how the process lets this happen",
             "For each process misdesign the tools propose, decide whether the evidence supports it; add the ones they missed.",
             f"""1. `{CLI} issues --kind rootcause` — P-xx with the risks it produces and the process evidence.
2. `{CLI} dig P-xx`; decide `{CLI} review P-xx accept|reject --note "..."`. Accept only if the data shows the
   process failure (pressure, deferral, missing owner, default-open settings, re-filed tickets), not just the risk.
3. Missing a root cause? Note it with `{CLI} note "..."` and record it in investigation/notes/security_memory.md.
4. `{CLI} step done rootcause --summary "..."`"""),
        Step("remediate", "Remediation plans",
             "Make every remediation specific to this organisation: which accounts, which rooms, which tickets, who owns it.",
             f"""1. `{CLI} issues --kind remediation` — M-xx: now / control / process / verify, per root cause.
2. For each, make it concrete from the data (names of accounts, tickets, rooms, owners) and record it:
   `{CLI} review M-xx accept --note "<the refined, specific plan>"` (or `reject --note "why"`).
3. Order them: what must happen this week, this quarter.
4. `{CLI} step done remediate --summary "..."`"""),
        Step("challenge", "Challenge the findings",
             "Try to break the register: false positives, risks already fixed, severities inflated or understated.",
             f"""1. `{CLI} proposals` — take every critical and high open risk and look for evidence that it is fixed or
   not exploitable; amend or reject with a note and a counter-citation (`--source/--quote`) where you find one.
2. Check the risks marked `check` (a later line may show a fix).
3. `{CLI} step done challenge --summary "what survived, what changed"`"""),
        Step("report", "Executive summary",
             "Write the security summary a board can act on.",
             f"""1. `{CLI} run --quiet` then `{CLI} status`.
2. `{CLI} step done report --summary "<5 sentences: the most dangerous open risks, the process failures behind them,
   the three remediations to do first, what was exposed by the incident>"`."""),
    ]
    return out


def progress(step: Step, state: dict, ws) -> dict:
    reviews = ws.reviews
    missing: list[str] = []
    if step.id == "scope":
        missing = [f"{i['id']} not decided: {i['title']}" for i in state["issues"]
                   if i["kind"] == "sweep" and i["key"] not in reviews]
    elif step.id.startswith("triage:"):
        cat = step.id.split(":", 1)[1]
        missing = [f"{f['id']} not reviewed: {f['title']}" for f in _risks(state)
                   if (f.get("meta") or {}).get("category") == cat and f["stage"] in ("sweep", "analyse")
                   and f["key"] not in reviews]
    elif step.id in ("rootcause", "remediate"):
        kind = "rootcause" if step.id == "rootcause" else "remediation"
        missing = [f"{i['id']} not reviewed: {i['title']}" for i in state["issues"]
                   if i["kind"] == kind and i["key"] not in reviews]
    st = ws.step_state(step.id)
    return {"id": step.id, "title": step.title, "status": st.get("status", "pending"),
            "summary": st.get("summary"), "missing": missing, "complete": not missing and st.get("status") == "done"}


def find(state: dict, step_id: str) -> Step | None:
    return next((s for s in steps_for(state) if s.id == step_id), None)
