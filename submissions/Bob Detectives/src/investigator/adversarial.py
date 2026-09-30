"""Stage 6 — adversarial review: try to break the case before anyone else does.

Every rule either confirms a finding, downgrades it, or raises a task. The review is
re-runnable and its output is part of the report.
"""

from __future__ import annotations

from . import argue
from . import lexicon as L
from .engine import Investigation
from .findings import Issue
from .tasks import Task
from .util import fmt_dt


def run(inv: Investigation, baseline: bool = False) -> None:
    """baseline=True reviews the tools-only result (nothing reviewed by the agent yet)."""
    prev = inv.store.include_proposed
    inv.store.include_proposed = baseline or inv.ws.mode == "autopilot"
    try:
        check_quotes(inv)
        check_absence_only(inv)
        check_echo_specificity(inv)
        check_echo_order(inv)
        first = argue.run(inv, baseline=baseline)
        robustness(inv, first)
        acknowledge_exculpatory(inv, first)
    finally:
        inv.store.include_proposed = prev
    n = len([i for i in inv.store.issues if i.kind == "adversarial"])
    inv.stage("adversarial", f"{n} review points")


def check_quotes(inv: Investigation) -> None:
    bad, ocr = [], []
    for f in inv.store.findings:
        for e in f.evidence:
            if e.status in ("not-found", "bad-source", "wrong-line", "no-quote"):
                bad.append((f, e))
            elif e.status == "ocr":
                ocr.append((f, e))
        if f.evidence and not any(e.usable or e.status == "ocr" for e in f.evidence):
            f.status = "withdrawn"
            f.history.append("withdrawn: no evidence verified")
    if bad:
        inv.issue(Issue(kind="adversarial", category="quotes", severity="high",
                        title=f"{len(bad)} quote(s) failed verification",
                        observation="; ".join(f"{e.source}: {e.status}" for _, e in bad[:10]),
                        evidence=[e for _, e in bad[:10]], resolution="needs-human"))
        for f, e in bad:
            inv.task(Task(kind="agent", topic="quote", subject=f"{e.source}|{e.quote[:40]}", suspect=f.suspect,
                          priority=1, title=f"Repair quote at {e.source}",
                          why="A quote that is not at its source counts against the whole verdict.",
                          question="Open the source, find the exact text, fix the citation or drop the evidence.",
                          read=[{"source": e.source, "quote": e.quote, "note": e.status}]))
    else:
        total = sum(len(f.evidence) for f in inv.store.findings)
        inv.issue(Issue(kind="adversarial", category="quotes", severity="low",
                        title="Every quote checked against the bundle as received",
                        observation=f"{total} evidence quotes; 0 missing; {len(ocr)} rest on OCR text.",
                        resolution="accepted"))
    seen = set()
    for f, e in ocr:
        if e.source in seen:
            continue
        seen.add(e.source)
        inv.task(Task(
            kind="human", topic="ocr", subject=e.source, suspect=f.suspect, priority=3,
            title=f"Confirm OCR text of {e.source}",
            why="The image has no text layer; the machine reading may be wrong (umlauts, digits). A quote from an "
                "image is only safe once a person has compared it to the picture.",
            question=f"Does the image really say: \"{e.quote}\"? If not, type the correct text.",
            read=[{"source": e.source, "quote": e.quote, "note": "OCR"}],
            options=["confirm", "correct"],
            effect={"confirm": "OCR quote may be used in verdict.json", "correct": "use the corrected text"},
        ))


def check_absence_only(inv: Investigation) -> None:
    for p in inv.case.suspects:
        fs = [f for f in inv.store.for_suspect(p.key) if f.cls in ("EXONERATES", "PROVES_INNOCENCE")]
        if fs and all(f.reliability in ("absence", "self") for f in fs):
            inv.issue(Issue(kind="adversarial", category="weak-clearance", severity="medium", affects=[p.key],
                            title=f"{p.name} is cleared only by absence or self-report",
                            observation="; ".join(f.title for f in fs),
                            resolution="accepted", effect="Verdict should read 'lowered, not cleared'."))
        for f in inv.store.for_suspect(p.key):
            if f.reliability == "absence" and f.cls == "INCRIMINATES":
                f.downgrade("WEAKLY_INCRIMINATES", "absence of a record is not incriminating on its own")


def check_echo_specificity(inv: Investigation) -> None:
    """Break the strongest finding type: is the vocabulary just common engineering talk?"""
    withheld = inv.case.fact("withheld") or []
    for f in inv.store.findings:
        if f.constraint != "echo" or f.cls != "INCRIMINATES":
            continue
        common = {}
        for e in inv.rec.by_kind("slack", "jira_comment", "jira"):
            for c in L.concept_hits(e.text, withheld):
                common.setdefault(c, []).append(e)
        busy = {c: v for c, v in common.items() if len(v) >= 5}
        if busy:
            ex = next(iter(busy.values()))[0]
            inv.issue(Issue(
                kind="adversarial", category="echo", severity="medium", affects=[f.suspect],
                title="The withheld details use everyday engineering vocabulary",
                observation=f"Phrases for {', '.join(busy)} occur {sum(len(v) for v in busy.values())} times in "
                            f"chat/tickets about other jobs (e.g. '{ex.text[:80]}').",
                evidence=[inv.ev_event(ex)],
                resolution="accepted",
                fix="The finding does not rest on the words but on the combination: this job, this night, told "
                    "as an experience before any record or leak about this event existed.",
                effect="Kept as 🔴 with the caveat attached.",
            ))
            f.caveats.append("vocabulary is common; the finding rests on the combination and timing")


def check_echo_order(inv: Investigation) -> None:
    for f in inv.store.findings:
        if f.constraint != "echo" or f.cls != "INCRIMINATES":
            continue
        p = inv.person(f.suspect)
        t_spoke = min((iv.started for iv in p.interviews if iv.started), default=None)
        leaks_before = [lk for lk in inv.leaks if t_spoke and lk.t < t_spoke]
        first_leak = min((lk.t for lk in inv.leaks), default=None)
        inv.issue(Issue(
            kind="adversarial", category="echo", severity="low" if not leaks_before else "high",
            affects=[f.suspect],
            title=f"Timing check: {p.name} spoke {'before' if not leaks_before else 'after'} the first known leak",
            observation=f"Interview at {fmt_dt(t_spoke)}; first known leak {fmt_dt(first_leak) if first_leak else 'none'}.",
            resolution="accepted" if not leaks_before else "needs-human",
            effect="Order of events supports the finding." if not leaks_before else "A leak predates the interview.",
        ))


def robustness(inv: Investigation, first: dict) -> None:
    """Drop one kind of analysis at a time: does the answer change?"""
    rows = []
    culprit = first["culprit"]
    analyzers = sorted({f.analyzer for f in inv.store.findings})
    for a in analyzers:
        scores = {}
        for p in inv.case.suspects:
            fs = [f for f in inv.store.for_suspect(p.key) if f.analyzer != a]
            if any(f.cls == "PROVES_INNOCENCE" for f in fs):
                continue
            scores[p.key] = sum(f.score for f in fs)
        if not scores:
            continue
        top = max(scores, key=scores.get)
        ranked = sorted(scores.values(), reverse=True)
        rows.append({"without": a, "top": top, "same": top == culprit,
                     "margin": round(ranked[0] - (ranked[1] if len(ranked) > 1 else 0), 2)})
    flips = [r for r in rows if not r["same"]]
    inv.results["robustness"] = rows
    inv.issue(Issue(
        kind="adversarial", category="robustness", severity="high" if flips else "low",
        title="Leave-one-analysis-out test",
        observation=(f"Removing any single analysis leaves {inv.person(culprit).name if culprit else '—'} on top "
                     f"({len(rows)} runs; smallest margin {min((r['margin'] for r in rows), default=0)})."
                     if not flips else f"The answer flips without: {', '.join(r['without'] for r in flips)}."),
        resolution="accepted" if not flips else "needs-human",
        effect="No single source of evidence carries the verdict alone." if not flips else
        "The verdict depends on one kind of evidence; treat confidence accordingly.",
    ))


def acknowledge_exculpatory(inv: Investigation, first: dict) -> None:
    c = first["culprit"]
    if not c:
        return
    greens = [f for f in inv.store.for_suspect(c) if f.cls in ("EXONERATES", "PROVES_INNOCENCE")]
    if greens:
        inv.issue(Issue(
            kind="adversarial", category="counter-evidence", severity="medium", affects=[c],
            title=f"Evidence in {inv.person(c).name}'s favour",
            observation="; ".join(f"{f.title}: {f.claim[:120]}" for f in greens),
            evidence=[e for f in greens for e in f.evidence[:1]],
            resolution="accepted",
            effect="Reported alongside the verdict, not hidden.",
        ))
    inv.task(Task(
        kind="human", topic="calibration", subject="confidence", priority=1, suspect=c,
        title="Sign off the confidence number",
        why="The score is judged on honesty. The formula is transparent, but the final number is a judgement.",
        question=f"The pipeline proposes {first['confidence']} for {inv.person(c).name}. Accept, or set a value.",
        options=["accept", "lower", "raise", "set"],
        effect={"accept": "keep the computed value", "lower": "use the value you give", "raise": "use the value you give",
                "set": "use the value you give"},
    ))
