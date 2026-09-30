"""The Security Guard's documents (shares the investigator's inconsistency and task writers)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from . import report
from . import security_lexicon as SL
from .engine import Investigation
from .util import fmt_dt

SEV_ICON = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "⬜"}


def _risks(inv: Investigation, include_proposed: bool = True):
    out = [f for f in inv.store.findings if f.meta.get("kind") == "risk" and f.status != "withdrawn"]
    if not include_proposed:
        out = [f for f in out if f.status != "proposed"]
    return sorted(out, key=lambda f: (-SL.SEVERITY[f.meta["severity"]], f.meta.get("state") != "open", f.id))


def _status(f) -> str:
    if f.status == "proposed":
        return "proposed"
    if f.review:
        return f"{f.review['decision']} by {f.review['by']}"
    if f.stage in ("bob", "human"):
        return f"added by {f.provenance}"
    return "tools"


def write_all(inv: Investigation) -> list[Path]:
    d = inv.paths.context_dir
    d.mkdir(parents=True, exist_ok=True)
    prev = inv.store.include_proposed
    inv.store.include_proposed = True
    try:
        docs = {
            "01_security_posture.md": posture_doc(inv),
            "02_risk_register.md": register_doc(inv),
            "03_root_causes.md": rootcause_doc(inv),
            "04_remediation_plan.md": remediation_doc(inv),
            "05_inconsistencies.md": report.inconsistencies(inv),
            "06_tasks_agent.md": report.tasks(inv, "agent"),
            "07_tasks_human.md": report.tasks(inv, "human"),
        }
    finally:
        inv.store.include_proposed = prev
    out = []
    for name, text in docs.items():
        (d / name).write_text(text, encoding="utf-8")
        out.append(d / name)
    (inv.paths.output / "risk_register.csv").write_text(register_csv(inv), encoding="utf-8")
    state = {
        "agent": "guard",
        "case": inv.case.summary(),
        "posture": inv.results.get("posture"),
        "hints": inv.hints,
        "issues": [i.to_dict() for i in inv.store.issues],
        "findings": [f.to_dict() for f in inv.store.findings],
        "tasks": [t.to_dict() for t in inv.tasks.tasks],
        "mode": inv.ws.mode,
        "reviews_summary": inv.results.get("reviews"),
        "agent_findings": inv.results.get("agent_findings"),
        "steps": inv.ws.steps,
        "drafts": inv.ws.drafts,
        "stages": inv.stage_log,
        "time_basis": inv.rec.time_basis,
        "clock_fixes": inv.clock_fixes,
        "inventory": inv.corpus.inventory(),
        "argue": None, "baseline": None, "verification": None,
    }
    sp = inv.paths.output / "investigation.json"
    sp.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    out.append(sp)
    return out


def posture_doc(inv: Investigation) -> str:
    p = inv.results["posture"]
    L = ["# Security posture (generated)", "",
         f"> Proactive scan of the data — no suspects. As of **{fmt_dt(__import__('datetime').datetime.fromisoformat(p['as_of'])) if p['as_of'] else '?'}**, "
         f"the latest dated record. Tools propose; in agent mode a risk counts as confirmed once the agent has reviewed it.", "",
         f"**{p['open']} open risks** of {p['risks']} · confirmed by the agent: {p['confirmed_by_agent']} · "
         + " · ".join(f"{SEV_ICON[s]} {s}: {n}" for s, n in p["by_severity"].items()), "",
         f"Root causes (process misdesign): **{p['rootcauses']}** · remediation plans: **{p['remediations']}**", ""]
    if p["incident_linked"]:
        L += [f"**Exposed by the incident under investigation:** {', '.join(p['incident_linked'])} — these weaknesses "
              f"were on the attack path and are still in place.", ""]
    L += ["## Most urgent open risks", "", "| ID | Severity | State | Risk | Source |", "|---|---|---|---|---|"]
    for f in [x for x in _risks(inv) if x.meta["state"] in ("open", "check")][:12]:
        L.append(f"| {f.id} | {SEV_ICON[f.meta['severity']]} {f.meta['severity']} | {f.meta['state']} | "
                 f"{report._md_escape(f.title)}{' · **incident**' if f.meta.get('incident') else ''} | {report._cite(f.evidence[0])} |")
    L += ["", "## By category", ""] + [f"- {k}: {v}" for k, v in p["by_category"].items()]
    return "\n".join(L) + "\n"


def register_doc(inv: Investigation) -> str:
    L = ["# Risk register (generated)", "", "> Every risk with its state, severity and exact sources. "
         "`proposed` = found by the tools, not yet reviewed by the agent.", ""]
    for f in _risks(inv):
        m = f.meta
        L += [f"## {f.id} · {SEV_ICON[m['severity']]} {m['severity']} · {m['state']} · {f.title}", "",
              f"**Category:** {m['category']} · **Subject:** {m.get('subject') or '—'} · **Review:** {_status(f)}"
              + (" · **on the incident's attack path**" if m.get("incident") else ""), "",
              f.claim, "", f"*Why it matters:* {f.reasoning}", ""]
        for h in f.history:
            L.append(f"- ↳ {h}")
        L += [f"- {report._cite(e)}{(' — ' + e.note) if e.note else ''}" for e in f.evidence] + [""]
    return "\n".join(L) + "\n"


def register_csv(inv: Investigation) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "severity", "state", "category", "title", "subject", "incident", "review", "first_source", "quote"])
    for f in _risks(inv):
        m = f.meta
        w.writerow([f.id, m["severity"], m["state"], m["category"], f.title, m.get("subject") or "", m.get("incident"),
                    _status(f), f.evidence[0].source if f.evidence else "", f.evidence[0].quote if f.evidence else ""])
    return buf.getvalue()


def rootcause_doc(inv: Investigation) -> str:
    L = ["# Root causes — how the process lets these risks exist (generated)", "",
         "> A risk is a symptom; the root cause is the process design that keeps producing it. "
         "Fixing the risk without the process means it comes back.", ""]
    for i in [x for x in inv.store.issues if x.kind == "rootcause"]:
        risks = [f for f in inv.store.findings if f.key in i.affects]
        L += [f"## {i.id} · {SEV_ICON.get(i.severity, '')} {i.title}", "", i.observation, "",
              f"**Risks it produces:** " + ", ".join(f"{f.id}" for f in risks), "",
              f"**Process fix:** {i.fix}", ""]
        if i.review:
            L += [f"**Agent review:** {i.review['decision']} — {i.review.get('note', '')}", ""]
        L += ["Evidence of the process failure:", ""] + [f"- {report._cite(e)}{(' — ' + e.note) if e.note else ''}" for e in i.evidence] + [""]
    return "\n".join(L) + "\n"


def remediation_doc(inv: Investigation) -> str:
    rems = sorted([x for x in inv.store.issues if x.kind == "remediation"], key=lambda i: -SL.SEVERITY.get(i.severity, 0))
    L = ["# Remediation plan (generated)", "",
         "> Standard practice mapped onto this organisation's open risks. The agent refines each plan; an accountable "
         "person approves it (human tasks). Order: critical first.", ""]
    for n, i in enumerate(rems, 1):
        r = SL.REMEDIATIONS.get(i.category, {})
        rc = next((x for x in inv.store.issues if x.key in i.affects and x.kind == "rootcause"), None)
        risks = [f for f in inv.store.findings if f.key in i.affects]
        approval = next((t for t in inv.tasks.tasks if t.subject == i.key), None)
        L += [f"## {n}. {i.id} · {SEV_ICON.get(i.severity, '')} {i.title}", "",
              f"**Owner:** {r.get('owner', '?')} · **Root cause:** {rc.id if rc else '—'} · **Risks:** "
              + ", ".join(f.id for f in risks)
              + (f" · **Approval:** {approval.id} ({approval.resolution['decision'] if approval.resolution else 'open'})" if approval else ""), "",
              f"1. **Now (containment):** {r.get('now', i.fix)}",
              f"2. **Control:** {r.get('control', '')}",
              f"3. **Process change:** {r.get('process', '')}",
              f"4. **{i.effect}**", ""]
        if i.review:
            L += [f"**Agent refinement ({i.review['decision']}):** {i.review.get('note', '')}", ""]
    return "\n".join(L) + "\n"
