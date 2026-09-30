"""The Security Guard pipeline — the investigator's framework pointed at current risks.

  ingest → context (no suspects) → sweep (shared) → scan → root causes → remediations
         → agent findings + reviews (shared gate) → quote re-check → report

Tools propose risks, process misdesigns and remediations; the agent (Bob, in the
securityguard mode) triages them, digs deeper, adds what was missed; a person approves
remediations. If an investigation exists, risks on its attack path are marked.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from . import adversarial, security, sweep
from . import security_lexicon as SL
from .engine import Investigation, Paths
from .pipeline import apply_reviews, load_agent_findings
from .tasks import Task


def posture(inv: Investigation) -> dict:
    risks = [f for f in inv.store.findings if f.meta.get("kind") == "risk" and f.status != "withdrawn"]
    by = lambda key: {k: sum(1 for f in risks if f.meta.get(key) == k) for k in sorted({f.meta.get(key) for f in risks})}  # noqa
    open_ = [f for f in risks if f.meta.get("state") in ("open", "check")]
    confirmed = [f for f in risks if f.review or f.stage in ("bob", "human")]
    top = sorted(open_, key=lambda f: (-SL.SEVERITY[f.meta["severity"]], f.id))[:8]
    return {
        "risks": len(risks), "open": len(open_), "confirmed_by_agent": len(confirmed),
        "by_severity": {s: sum(1 for f in open_ if f.meta["severity"] == s) for s in ("critical", "high", "medium", "low")},
        "by_state": by("state"), "by_category": by("category"),
        "incident_linked": [f.id for f in risks if f.meta.get("incident")],
        "top": [{"id": f.id, "title": f.title, "severity": f.meta["severity"], "state": f.meta["state"]} for f in top],
        "rootcauses": len([i for i in inv.store.issues if i.kind == "rootcause"]),
        "remediations": len([i for i in inv.store.issues if i.kind == "remediation"]),
        "as_of": security._as_of(inv).isoformat() if security._as_of(inv) else None,
    }


def run(paths: Paths, team: str = "", ocr: bool = True, log=print) -> Investigation:
    t0 = time.time()
    inv = Investigation(paths, ocr=ocr, log=log, suspects=False, agent="guard")
    inv.stage("ingest", f"{len(inv.corpus.docs)} files, {len(inv.rec.events)} dated records from {paths.bundle}")
    inv.stage("context", f"{len(inv.case.people)} people in the directory; no suspects (proactive scan)")
    sweep.run(inv, profile="guard")
    incident = {"sources": set(), "text": ""}
    inv_state = paths.repo / "investigation" / "output" / "investigation.json"
    if inv_state.exists():
        try:
            incident = security.incident_from_state(json.loads(inv_state.read_text(encoding="utf-8")))
        except Exception:
            pass
    security.scan(inv, inv.store, incident)
    security.root_causes(inv, inv.store)
    security.remediations(inv, inv.store)
    load_agent_findings(inv)
    apply_reviews(inv)
    prev = inv.store.include_proposed
    inv.store.include_proposed = True
    adversarial.check_quotes(inv)
    inv.store.include_proposed = prev
    for f in inv.store.findings:
        if f.meta.get("state") == "check" and f.status != "withdrawn":
            inv.task(Task(kind="agent", topic="verify-fix", subject=f.key, priority=2,
                          title=f"Is it really fixed? {f.title[:80]}",
                          why="A later line may report a fix; confirm it or keep the risk open.",
                          question=f"Dig into {f.title} and decide its state with `review <ID> amend --state open|addressed`.",
                          read=[{"source": e.source, "quote": e.quote, "note": e.note} for e in f.evidence[:3]]))
    inv.store.number(inv.ws, finding_prefix="S")
    inv.tasks.number()
    inv.results["posture"] = posture(inv)
    from . import report_guard
    report_guard.write_all(inv)
    inv.stage("report", f"security docs in {paths.context_dir} ({time.time() - t0:.1f}s)")
    (paths.output / "run.json").write_text(json.dumps({"finished": datetime.now().isoformat(timespec="seconds"),
                                                       "agent": "guard", "seconds": round(time.time() - t0, 1)}, indent=1),
                                           encoding="utf-8")
    return inv
