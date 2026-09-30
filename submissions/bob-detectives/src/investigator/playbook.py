"""The investigation playbook — the steps the agent works through.

Tools propose; the agent decides. Each step says what to look at, which commands to use,
and what "done" means in terms the machine can check (every proposal reviewed, every
inconsistency decided, a verdict drafted for everyone). The agent may always go deeper
than the step asks — `dig`, `search`, `timeline` — and add its own findings.
"""

from __future__ import annotations

from dataclasses import dataclass

CLI = "src/investigate"


@dataclass
class Step:
    id: str
    title: str
    goal: str
    instructions: str
    suspect: str | None = None


def steps_for(state: dict) -> list[Step]:
    """Build the playbook from the last run's state (investigation.json)."""
    suspects = state["case"]["suspects"]
    out = [
        Step("frame", "Establish the case frame",
             "Know the incident, the operation window, the people and what the operator needed, each with a source.",
             f"""1. Run `{CLI} frame` and read every derived fact.
2. Open the sources behind the facts that matter most (`{CLI} show <source> -C 4`): the operation window,
   what was withheld, the secret the operator needed.
3. If a fact looks wrong or incomplete, check it (`{CLI} search`, `{CLI} dig <source>`) and record what you
   found with `{CLI} note "..."`.
4. Write the frame in your own words into investigation/notes/case_memory.md (create it if missing).
5. Finish with `{CLI} step done frame --summary "<two sentences>"`."""),
        Step("sweep", "Inconsistencies first",
             "Before arguing anything, decide every place where the sources disagree or warn about themselves.",
             f"""1. Run `{CLI} issues --kind sweep`. For each inconsistency I-xx:
   - open its evidence (`{CLI} dig I-xx`), check the proposed fix or explanation against the sources;
   - decide: `{CLI} review I-xx accept --note "..."` (fix/explanation holds),
     `reject --note "..."` (it does not — say why, cite), or `escalate --note "..."` (a person must decide).
2. Look for inconsistencies the sweep missed: records of the same moment that disagree, statements that
   contradict records, sources that warn about themselves. Add what you find with `{CLI} finding add`.
3. Finish with `{CLI} step done sweep --summary "..."`."""),
    ]
    for s in suspects:
        name, key = s["name"], s["handle"] or s["name"]
        out.append(Step(
            f"suspect:{key}", f"Suspect: {name}",
            f"Decide what the paperwork says about {name}: suspicion → paperwork → judgement.",
            f"""1. Run `{CLI} proposals --suspect "{name}"`. These are the tools' proposals; none counts until you review it.
2. For each proposal F-xxx: open its sources (`{CLI} dig F-xxx`), then
   `{CLI} review F-xxx accept --note "..."`, or `amend --class <CLASS> [--weight w] --note "..."`,
   or `reject --note "..."` (with a counter-citation: `--source <path:line> --quote "<exact text>"`).
3. Go deeper where it matters: for every suspicion (why {name} is on the list, anything they seemed to know),
   search for the record that confirms or explains it — often in a different file and format
   (`{CLI} search`, `{CLI} timeline --suspect "{name}"`). Add what you find with `{CLI} finding add`.
4. Append 3–5 lines on {name} to investigation/notes/case_memory.md.
5. Finish with `{CLI} step done suspect:{key} --summary "suspicion → paperwork → judgement"`.""",
            suspect=name))
    out += [
        Step("crosscheck", "Cross-check across suspects",
             "Compare suspects against each other: who was on site, who knew what and when, which suspicions "
             "turned out to be misleading.",
             f"""1. Run `{CLI} status` and `{CLI} proposals --constraint echo` and `{CLI} proposals --constraint presence`.
2. Put the interviews, leaks and public records in time order: could anyone have learned the withheld
   details innocently BEFORE they spoke? (`{CLI} dig F-xxx` on each echo, `{CLI} issues --kind sweep` for leaks.)
3. Check that exactly one person satisfies every constraint. If two do, or none, say so with evidence.
4. Record your comparison in investigation/notes/case_memory.md and finish with
   `{CLI} step done crosscheck --summary "..."`."""),
        Step("challenge", "Try to break the case",
             "Attack the leading hypothesis before anyone else does.",
             f"""1. Run `{CLI} issues --kind adversarial` and answer each R-xx with `{CLI} review R-xx accept|reject|escalate --note "..."`.
2. Take the leading suspect's three strongest findings. For each, look hard for an innocent explanation
   (`{CLI} dig F-xxx`, `{CLI} search`). If you find one, add it with `{CLI} finding add` (EXONERATES, cited).
3. Finish with `{CLI} step done challenge --summary "what survived, what did not"`."""),
        Step("verdict", "Draft the verdict",
             "Write the verdict for every suspect in your own words, citing the findings you rely on.",
             f"""1. Run `{CLI} run --quiet` then `{CLI} status`.
2. For each of the eight suspects:
   `{CLI} verdict draft --suspect "<name>" --verdict <culprit|cleared|unresolved> --reasoning "<one or two sentences>" --cite F-xxx --cite F-yyy`
   Clear someone only with exonerating evidence; say "unresolved" if the paperwork does not decide it.
   Explain the misleading suspects explicitly (what made them look guilty, which record explains it).
3. Propose a confidence with `{CLI} confidence propose <0.05–0.95> --why "..."` (a person signs it off).
4. Finish with `{CLI} step done verdict --summary "..."`."""),
    ]
    return out


def progress(step: Step, state: dict, ws) -> dict:
    """What is still missing for a step to be done."""
    reviews = ws.reviews
    missing: list[str] = []
    if step.id == "sweep":
        for i in state["issues"]:
            if i["kind"] == "sweep" and i["key"] not in reviews:
                missing.append(f"{i['id']} not decided: {i['title']}")
    elif step.id.startswith("suspect:"):
        key = step.id.split(":", 1)[1]
        for f in state["findings"]:
            if f["suspect"] == key and f["stage"] in ("sweep", "analyse") and f["key"] not in reviews \
                    and f["status"] != "withdrawn":
                missing.append(f"{f['id']} not reviewed: {f['title']}")
    elif step.id == "challenge":
        for i in state["issues"]:
            if i["kind"] == "adversarial" and i["key"] not in reviews:
                missing.append(f"{i['id']} not answered: {i['title']}")
    elif step.id == "verdict":
        drafted = set(ws.drafts.get("suspects", {}))
        for s in state["case"]["suspects"]:
            if s["name"] not in drafted and (s["handle"] or "") not in drafted:
                missing.append(f"no verdict drafted for {s['name']}")
    st = ws.step_state(step.id)
    return {"id": step.id, "title": step.title, "status": st.get("status", "pending"),
            "summary": st.get("summary"), "missing": missing, "complete": not missing and st.get("status") == "done"}


def find(state: dict, step_id: str) -> Step | None:
    return next((s for s in steps_for(state) if s.id == step_id), None)
