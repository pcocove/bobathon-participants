"""Orchestration and configuration discovery."""

from __future__ import annotations

import json
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import adversarial, analyze, argue, report, sweep, verdict
from .engine import Investigation, Paths
from .findings import Evidence, Finding

STAGES = ["ingest", "context", "sweep", "analyse", "agent-findings", "reviews", "adversarial", "argue", "verdict", "report"]


def find_repo() -> Path:
    """The folder that holds src/ and .bob/: Bob works here and the workdirs live here."""
    return Path(__file__).resolve().parents[2]


def find_data_root(home: Path) -> Path:
    """Where the case material lives: the home itself, or the nearest folder above it with the
    suspect template or a case bundle (the code may sit in a submissions/<team>/ folder)."""
    chain = [home, *home.parents]
    for q in chain:
        if (q / "verdict_template.json").exists():
            return q
    for q in chain:
        if (q / "case_bundle").is_dir() or any(q.glob("*/case_bundle")):
            return q
    return home


def _is_normalised(d: Path) -> bool:
    """A rewritten copy says so in its title; the original may say its times are *not* normalised."""
    r = d / "README.md"
    if not r.exists():
        return False
    head = " ".join(r.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]).upper()
    return bool(re.search(r"(?<!NOT )\bNORMALI[SZ]ED\b", head))


def find_bundle(repo: Path, workdir: Path) -> Path:
    """The bundle exactly as received. A rewritten ('normalised') copy is refused: its line
    numbers and timestamps no longer match what the scorer checks."""
    candidates = [repo / "case_bundle"]
    candidates += sorted(repo.glob("*/case_bundle")) + sorted(repo.glob("*/*/case_bundle"))
    candidates = [c for c in candidates if "submissions" not in c.relative_to(repo).parts]   # never another team's copy
    for c in candidates:
        if c.is_dir() and any(c.iterdir()) and not _is_normalised(c):
            return c
    for z in sorted(repo.glob("*.zip")) + sorted(repo.glob("*/*.zip")):
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            root = next((n.split("case_bundle/")[0] + "case_bundle" for n in names if "case_bundle/" in n), None)
            if root:
                dest = workdir / "state" / "bundle"
                if not (dest / root).exists():
                    zf.extractall(dest)
                return dest / root
    raise SystemExit("No case bundle found. Pass --bundle PATH (the unmodified case_bundle directory).")


def find_briefs(repo: Path, bundle: Path) -> list[Path]:
    out = []
    for name in ("team_handout.md", "README_bundle.md"):
        out += [p for p in repo.rglob(name)
                if not {"node_modules", "investigation", "submissions"} & set(p.relative_to(repo).parts)][:1]
    if (bundle / "README.md").exists():
        out.append(bundle / "README.md")
    return out


def make_paths(bundle: str | None = None, workdir: str | None = None, repo: str | None = None) -> Paths:
    r = Path(repo).resolve() if repo else find_repo()
    data = find_data_root(r)
    wd = Path(workdir).resolve() if workdir else r / "investigation"
    b = Path(bundle).resolve() if bundle else find_bundle(data, wd)
    if _is_normalised(b):
        raise SystemExit(f"{b} is a rewritten copy; citations must use the bundle as received.")
    t = data / "verdict_template.json"
    return Paths(repo=r, bundle=b, template=t if t.exists() else None, briefs=find_briefs(data, b), workdir=wd)


def load_agent_findings(inv: Investigation) -> None:
    """Findings added by Bob or a human through the CLI. Verified before they count."""
    path = inv.paths.state / "agent_findings.jsonl"
    rejected = []
    if not path.exists():
        inv.results["agent_findings"] = {"accepted": 0, "rejected": []}
        return
    accepted = 0
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        ev = [inv.evidence(e["source"], quote=e.get("quote", ""), note=e.get("note", "")) for e in d.get("evidence", [])]
        ok = [e for e in ev if e.usable or e.status == "ocr"]
        p = inv.person(d.get("suspect")) if d.get("suspect") else None
        if not ok or (d.get("suspect") and not p):
            rejected.append({"title": d.get("title"), "why": "no evidence verified" if not ok else "unknown suspect",
                             "evidence": [{"source": e.source, "status": e.status} for e in ev]})
            continue
        inv.add(Finding(
            suspect=p.key if p else None, analyzer=f"{d.get('by', 'agent')}-added", constraint=d.get("constraint", "lead"),
            cls=d.get("cls", "NEUTRAL"), title=d.get("title", "agent finding"), claim=d.get("claim", ""),
            evidence=ok, reasoning=d.get("reasoning", ""), weight=float(d.get("weight", 0.3)),
            reliability=d.get("reliability", "derived"), provenance=d.get("by", "agent"),
            stage="bob" if d.get("by") == "bob" else "human", explains=d.get("explains"),
            caveats=[f"added by {d.get('by', 'agent')} at {d.get('added_at', '?')}; quotes verified"],
            meta=({"kind": "risk", "severity": d["severity"], "state": d.get("state") or "open",
                   "category": d.get("constraint", "other"), "subject": d.get("subject"), "incident": False}
                  if d.get("severity") else {}),
        ))
        accepted += 1
    inv.results["agent_findings"] = {"accepted": accepted, "rejected": rejected}
    inv.stage("agent-findings", f"{accepted} accepted, {len(rejected)} rejected (quotes not found)")


def apply_reviews(inv: Investigation) -> None:
    """The agent's decisions on the tools' proposals. In agent mode an unreviewed proposal
    does not count yet; in autopilot mode every proposal counts."""
    ws = inv.ws
    agent_mode = ws.mode == "agent"
    counts = {"accepted": 0, "rejected": 0, "amended": 0, "proposed": 0}
    for f in inv.store.findings:
        if f.stage in ("bob", "human"):
            continue  # added by the agent/human through the verified gate
        r = ws.reviews.get(f.key)
        if r is None:
            if agent_mode:
                f.status = "proposed"
                counts["proposed"] += 1
            continue
        f.review = r
        d = r["decision"]
        if d == "reject":
            f.status = "withdrawn"
            f.history.append(f"rejected by {r['by']}: {r['note']}")
            counts["rejected"] += 1
        elif d == "amend":
            for k in ("severity", "state"):
                if r.get(k) and f.meta.get(k) != r[k]:
                    f.history.append(f"{k} {f.meta.get(k)} → {r[k]} by {r['by']}: {r['note']}")
                    f.meta[k] = r[k]
            if r.get("cls") and r["cls"] != f.cls:
                f.history.append(f"{f.cls} → {r['cls']} by {r['by']}: {r['note']}")
                f.cls = r["cls"]
            if r.get("weight") is not None:
                f.weight = float(r["weight"])
            f.caveats.append(f"amended by {r['by']}: {r['note']}")
            counts["amended"] += 1
        else:
            if r.get("note"):
                f.caveats.append(f"accepted by {r['by']}: {r['note']}")
            counts["accepted"] += 1
    from .tasks import Task
    for i in inv.store.issues:
        r = ws.reviews.get(i.key)
        if r:
            i.review = r
            if r["decision"] == "escalate":
                inv.task(Task(
                    kind="human", topic="escalation", subject=i.key, priority=1,
                    suspect=i.affects[0] if len(i.affects) == 1 else None,
                    title=f"Escalated by {r['by']}: {i.title}", why=r["note"],
                    question="The agent could not settle this from the records. Decide it.",
                    read=[{"source": e.source, "quote": e.quote, "note": e.note} for e in i.evidence[:6]],
                    options=["accept", "reject"],
                    effect={"accept": "the sweep's resolution stands", "reject": "treat as unresolved"}))
    inv.results["reviews"] = counts
    inv.stage("reviews", f"mode={ws.mode}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))


def guard_workdir(paths: Paths):
    """The Security Guard workspace paired with an investigation: `security/` next to the default
    `investigation/`, or `<workdir>/security` for a custom workdir."""
    default = (paths.repo / "investigation").resolve()
    return paths.repo / "security" if paths.workdir.resolve() == default else paths.workdir / "security"


def security_section(inv: Investigation) -> None:
    """The same scanner the Security Guard uses: flaws the incident exposed that are still open,
    the process misdesign behind them, and remediations. IDs and review decisions are shared
    with the Guard's workspace, so both agents talk about the same S-/P-/M- items."""
    from . import security
    from .findings import FindingStore
    from .workspace import Workspace
    culprit = (inv.results.get("argue") or {}).get("culprit") or (inv.results.get("baseline") or {}).get("culprit")
    store = FindingStore()
    security.scan(inv, store, security.incident_from_investigation(inv, culprit))
    security.root_causes(inv, store)
    security.remediations(inv, store, make_tasks=False)
    guard_ws = Workspace(guard_workdir(inv.paths) / "state")
    store.number(guard_ws, finding_prefix="S")
    inv.results["security"] = security.summarize(store, guard_ws.reviews)


def run(paths: Paths, team: str = "bob-investigator", ocr: bool = True, log=print) -> Investigation:
    t0 = time.time()
    inv = Investigation(paths, ocr=ocr, log=log)
    inv.stage("ingest", f"{len(inv.corpus.docs)} files, {len(inv.rec.events)} dated records from {paths.bundle}")
    op = inv.case.op_window
    inv.stage("context", f"{len(inv.case.suspects)} suspects; operation window "
                         f"{op[0].strftime('%a %d.%m %H:%M')} → {op[1].strftime('%a %d.%m %H:%M')}" if op else "no window")
    sweep.run(inv)
    analyze.run(inv)
    load_agent_findings(inv)
    apply_reviews(inv)
    rv = inv.results["reviews"]
    untouched = inv.ws.mode == "agent" and not (rv["accepted"] or rv["rejected"] or rv["amended"]) \
        and not inv.results["agent_findings"]["accepted"] and not inv.ws.drafts.get("suspects")
    adversarial.run(inv, baseline=untouched)
    inv.store.number(inv.ws)
    argue.run(inv, baseline=True)
    argue.run(inv)
    inv.tasks.number()
    if untouched:
        inv.results["argue"] = dict(inv.results["baseline"],
                                    basis="tools only — the agent has not reviewed anything yet")
    v = verdict.build(inv, team, baseline=untouched)
    verdict.write(inv, v)
    security_section(inv)
    verdict.write(inv, verdict.build(inv, team, baseline=True), name="verdict_baseline.json")
    report.write_all(inv)
    inv.stage("report", f"context docs in {paths.context_dir} ({time.time() - t0:.1f}s)")
    meta = {"finished": datetime.now().isoformat(timespec="seconds"), "bundle": str(paths.bundle),
            "team": team, "seconds": round(time.time() - t0, 1)}
    (paths.output / "run.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return inv


def add_agent_finding(paths: Paths, data: dict) -> dict:
    """Append a finding from Bob/human; verified immediately so the caller sees the result."""
    from .corpus import Corpus
    corpus = Corpus(paths.bundle, cache_dir=paths.state / "ocr_cache")
    checks = [corpus.verify(e["source"], e.get("quote", "")) for e in data.get("evidence", [])]
    data["added_at"] = datetime.now().isoformat(timespec="seconds")
    data["checks"] = [{"source": c["source"], "status": c["status"], "detail": c["detail"]} for c in checks]
    ok = [c for c in checks if c["status"] in ("verified", "whitespace", "ocr")]
    if ok:
        paths.state.mkdir(parents=True, exist_ok=True)
        with (paths.state / "agent_findings.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False) + "\n")
    return {"accepted": bool(ok), "checks": data["checks"]}
