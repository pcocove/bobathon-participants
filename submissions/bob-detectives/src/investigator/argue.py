"""Stage 5 — argumentation: constraints per suspect, elimination, verdicts, confidence.

The operator had to (a) be at a console on site for the whole operation window,
(b) know which artifacts were real, and — the discriminating tests — their own account
had to survive the paperwork and their knowledge of withheld facts had to have an
innocent route. Findings are summed per suspect with their reliability; a proven
alibi (⚪) removes a suspect outright.

Confidence is a transparent formula, not a feeling:
    confidence = min(0.95, 0.5 + 0.08 × pillars + 0.10 × min(margin, 2.5)) − penalties
  pillars   independent constraints that point at the culprit
  margin    score gap to the next suspect still standing
  penalties open human tasks and sweep fixes the culprit's case depends on
A human can override it through the calibration task.
"""

from __future__ import annotations

from .engine import Investigation
from .findings import Finding

PILLAR_CONSTRAINTS = ("presence", "statement", "echo", "knowledge", "link")


def profile(inv: Investigation, p) -> dict:
    fs = inv.store.for_suspect(p.key)
    by = lambda c: [f for f in fs if f.constraint == c]  # noqa: E731
    excluded = [f for f in fs if f.cls == "PROVES_INNOCENCE"]
    pres = by("presence")
    pres_score = sum(f.score for f in pres)
    if excluded:
        presence = "excluded"
    elif any(f.cls == "INCRIMINATES" for f in pres):
        presence = "on site"
    elif pres_score <= -0.25:
        presence = "away (likely)"
    else:
        presence = "unknown"
    echo = by("echo")
    explained_keys = {f.explains for f in echo if f.explains}
    if any(f.cls == "INCRIMINATES" for f in echo):
        echo_state = "unexplained"
    elif any(f.key in explained_keys for f in echo):
        echo_state = "explained"
    else:
        echo_state = "none"
    st = by("statement")
    statement = "contradicted" if any(f.cls == "INCRIMINATES" for f in st) else (
        "consistent" if any(f.cls == "EXONERATES" for f in st) else "uncorroborated")
    kn = by("knowledge")
    knowledge = "route" if any(f.cls in ("INCRIMINATES", "WEAKLY_INCRIMINATES") for f in kn) else "none documented"
    link = "direct" if any(f.cls in ("INCRIMINATES", "WEAKLY_INCRIMINATES") for f in by("link")) else "—"
    unexplained_red = [f for f in fs if f.cls == "INCRIMINATES"]
    pillars = sorted({f.constraint for f in fs if f.constraint in PILLAR_CONSTRAINTS and
                      (f.cls == "INCRIMINATES" or (f.cls == "WEAKLY_INCRIMINATES" and f.constraint in ("knowledge", "link")))})
    return {
        "key": p.key, "name": p.name, "score": round(sum(f.score for f in fs), 3),
        "presence": presence, "knowledge": knowledge, "echo": echo_state, "statement": statement, "link": link,
        "excluded_by": [f.key for f in excluded], "red": [f.key for f in unexplained_red],
        "green": [f.key for f in fs if f.cls in ("EXONERATES", "PROVES_INNOCENCE")],
        "pillars": pillars, "misleading": echo_state == "explained",
    }


def run(inv: Investigation, baseline: bool = False) -> dict:
    """baseline=True: every tool proposal counts (what the tools alone conclude).
    baseline=False: only findings the agent accepted or added count (agent mode)."""
    prev = inv.store.include_proposed
    inv.store.include_proposed = baseline or inv.ws.mode == "autopilot"
    try:
        return _run(inv, baseline)
    finally:
        inv.store.include_proposed = prev


def _run(inv: Investigation, baseline: bool) -> dict:
    profiles = [profile(inv, p) for p in inv.case.suspects]
    standing = sorted([x for x in profiles if x["presence"] != "excluded"], key=lambda x: -x["score"])
    top = standing[0] if standing else None
    second = standing[1] if len(standing) > 1 else None
    margin = (top["score"] - (second["score"] if second else 0.0)) if top else 0.0
    penalties = []
    culprit = None
    confidence = 0.0
    if top and top["score"] > 0:
        culprit = top
        base = min(0.95, 0.5 + 0.08 * len(top["pillars"]) + 0.10 * min(max(margin, 0), 2.5))
        for t in inv.tasks.open("human"):
            if t.suspect in (None, top["key"]) and t.topic in ("clock", "plate", "leak", "ocr"):
                affects = t.topic != "leak" or t.suspect == top["key"]
                if affects:
                    d = 0.03 if t.priority == 1 else 0.015
                    penalties.append({"task": t.key, "title": t.title, "minus": d})
        for f in inv.store.for_suspect(top["key"]):
            if f.cls == "INCRIMINATES" and f.caveats and "transcript" in " ".join(f.caveats):
                penalties.append({"finding": f.key, "title": "rests on an unproofread transcript", "minus": 0.01})
        confidence = base - sum(x["minus"] for x in penalties)
        if top["score"] < 1.0 or margin < 0.8:
            penalties.append({"title": "weak lead over the next suspect", "minus": 0.2})
            confidence -= 0.2
    # human calibration override
    cal = inv.tasks.decision("human", "calibration", "confidence")
    override = None
    if cal and cal.get("value") is not None and cal.get("decision") in ("lower", "raise", "set"):
        override = float(cal["value"])
        confidence = override
    confidence = round(max(0.05, min(0.95, confidence)), 2)

    verdicts = {}
    drafts = {} if baseline else inv.ws.drafts.get("suspects", {})
    for x in profiles:
        if culprit and x["key"] == culprit["key"]:
            v = "culprit"
        elif x["presence"] == "excluded":
            v = "cleared"
        elif culprit and confidence >= 0.75 and not x["red"] and x["green"]:
            v = "cleared"
        else:
            v = "unresolved"
        x["computed_verdict"] = v
        d = drafts.get(x["name"]) or drafts.get(x["key"])
        if d:
            v = d["verdict"]          # the agent's judgement, recorded with its reasoning
            x["draft"] = d
        verdicts[x["key"]] = v
        x["verdict"] = v
    agent_culprits = [x for x in profiles if x["verdict"] == "culprit"]
    if drafts and len(agent_culprits) == 1 and agent_culprits[0] is not culprit:
        # the agent disagrees with the scores: its call stands, but the doubt shows in the number
        penalties.append({"title": f"agent names {agent_culprits[0]['name']}, the scores lead with "
                                   f"{culprit['name'] if culprit else 'nobody'}", "minus": 0.25})
        culprit = agent_culprits[0]
        if override is None:
            confidence = round(max(0.05, confidence - 0.25), 2)
    res = {
        "culprit": culprit["key"] if culprit else None,
        "culprit_name": culprit["name"] if culprit else None,
        "confidence": confidence,
        "confidence_formula": {"pillars": culprit["pillars"] if culprit else [], "margin": round(margin, 3),
                               "penalties": penalties, "override": override},
        "profiles": profiles, "standing": [x["key"] for x in standing],
        "misleading": [x["key"] for x in profiles if x["misleading"] and x["verdict"] != "culprit"],
    }
    reviewed = [f for f in inv.store.findings if f.review or f.stage in ("bob", "human")]
    res["basis"] = "tools only (baseline)" if baseline else (
        "tools only (autopilot)" if inv.ws.mode == "autopilot" else
        f"agent-reviewed: {len(reviewed)} of {len(inv.store.findings)} findings reviewed or added by the agent")
    res["agent_confidence"] = None if baseline else inv.ws.drafts.get("confidence")
    inv.results["baseline" if baseline else "argue"] = res
    inv.stage("argue", f"[{'baseline' if baseline else inv.ws.mode}] culprit={res['culprit_name']} "
                       f"confidence={confidence} margin={margin:.2f}")
    return res


def judgement_triples(inv: Investigation, key: str) -> list[dict]:
    """Suspicion → paperwork → judgement, the form the handout asks for."""
    fs = inv.store.for_suspect(key)
    out = []
    for s in fs:
        if s.cls not in ("WEAKLY_INCRIMINATES", "INCRIMINATES"):
            continue
        answer = next((f for f in fs if f.explains == s.key), None)
        if answer is None and s.constraint == "lead":
            answer = next((f for f in fs if f.cls in ("EXONERATES", "PROVES_INNOCENCE")), None)
        out.append({"suspicion": s, "paperwork": answer})
    return out


def finding(inv: Investigation, key: str) -> Finding | None:
    return next((f for f in inv.store.findings if f.key == key), None)
