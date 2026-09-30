"""Command line — the interface Bob (and a human) works through.

  investigate run                 full pipeline → investigation/output/{verdict.json, context/*.md}
  investigate serve               local UI on http://127.0.0.1:8765
  investigate status              culprit, confidence, open tasks
  investigate search REGEX        citable hits (path:line)
  investigate show SOURCE         read around a citation
  investigate verify-quote S Q    is Q really at S?
  investigate verify [FILE]       check every quote of a verdict.json
  investigate repair FILE         fix a verdict file's citations against the bundle as received
  investigate export [PATH]       copy the investigator's verified verdict.json to PATH
  investigate timeline            records around the operation window
  investigate suspect NAME        one suspect's findings
  investigate tasks               open tasks (human + agent)
  investigate task resolve ID     record a human decision
  investigate finding add …       add a finding (quotes verified first)
  investigate bob ID              hand an agent task to Bob (headless)
  investigate docs [NAME]         print a generated context document

The same CLI serves the Security Guard: `src/guard <command>` (proactive risk scan, no suspects).

Agent workflow (tools propose, the agent decides):
  investigate playbook            the steps and what is still open in each
  investigate step show ID        goal, instructions and open items of a step
  investigate step done ID --summary "…"
  investigate frame               the derived case frame with sources
  investigate proposals [--suspect N] [--constraint C] [--pending]
  investigate review ID accept|reject|amend|escalate --note "…" [--class C] [--weight W] [--source S --quote Q]
  investigate issues [--kind sweep|adversarial]
  investigate dig TARGET          context pack for a finding, inconsistency, suspect or citation
  investigate verdict draft --suspect N --verdict V --reasoning "…" [--cite F-001 …]
  investigate confidence propose VALUE --why "…"
  investigate note "…"            add a reasoning note to the journal
  investigate mode agent|autopilot
  investigate agent run [--steps …] [--depth quick|normal|deep]   Bob works the playbook (ACP, your login)
  investigate agent dig TARGET [--question "…"]                   Bob goes deeper on one thing
  investigate agent log [RUN]     Bob's messages, commands and outputs
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from . import bob as bobmod
from . import pipeline, profiles
from .corpus import Corpus
from .tasks import Task, TaskBook
from .util import fmt_dt
from .workspace import Workspace, actor

PROFILE = profiles.get()
CLI = PROFILE["cli"]
GUARD = PROFILE["id"] == "guard"


def _paths(a):
    workdir = getattr(a, "workdir", None) or os.environ.get("INVESTIGATE_WORKDIR")
    if not workdir:
        workdir = str(pipeline.find_repo() / PROFILE["workdir"])
    return pipeline.make_paths(getattr(a, "bundle", None), workdir)


def _playbook():
    if GUARD:
        from . import guard_playbook as pb
    else:
        from . import playbook as pb
    return pb


def _run_pipeline(paths, **kw):
    if GUARD:
        from . import guard
        return guard.run(paths, **{k: v for k, v in kw.items() if k in ("ocr", "log")})
    return pipeline.run(paths, **kw)


def _print_posture(p: dict, st_or_inv_tasks, paths) -> None:
    print()
    print(f"SECURITY POSTURE  {p['open']} open risks of {p['risks']} · confirmed by the agent {p['confirmed_by_agent']}")
    print("   " + " · ".join(f"{s} {n}" for s, n in p["by_severity"].items()) +
          f"   · root causes {p['rootcauses']} · remediations {p['remediations']}")
    if p["incident_linked"]:
        print(f"   exposed by the incident: {', '.join(p['incident_linked'])}")
    print()
    for t in p["top"]:
        print(f"   {t['id']}  {t['severity']:8s} {t['state']:9s} {t['title'][:90]}")
    tasks = st_or_inv_tasks.tasks if hasattr(st_or_inv_tasks, "tasks") else st_or_inv_tasks
    op = [t for t in tasks if (t.status if hasattr(t, "status") else t["status"]) == "open"]
    h = sum(1 for t in op if (t.kind if hasattr(t, "kind") else t["kind"]) == "human")
    print(f"\nopen tasks: {h} human, {len(op) - h} agent   →  {CLI} tasks")
    print(f"outputs:    {paths.context_dir}/  ·  {paths.output}/risk_register.csv")


def _state(paths) -> dict:
    p = paths.output / "investigation.json"
    if not p.exists():
        sys.exit("No investigation yet. Run: investigate run")
    return json.loads(p.read_text(encoding="utf-8"))


def _corpus(paths) -> Corpus:
    return Corpus(paths.bundle, cache_dir=paths.state / "ocr_cache")


def cmd_run(a):
    paths = _paths(a)
    log = (lambda m: None) if a.quiet else (lambda m: print(m, file=sys.stderr))
    inv = _run_pipeline(paths, team=a.team, ocr=not a.no_ocr, log=log)
    if GUARD:
        _print_posture(inv.results["posture"], inv.tasks, paths)
        return
    _print_summary(inv.results["argue"], inv.results.get("verification"), inv.tasks, paths, inv.results.get("baseline"))
    if a.export:
        _export(paths, a.export)


def _export(paths, target: str) -> None:
    """Copy the investigator's verdict.json to where it will be submitted, re-verified."""
    from .verdict import verify_file
    src = paths.output / "verdict.json"
    if not src.exists():
        sys.exit("No verdict yet. Run: investigate run")
    dst = Path(target)
    if not dst.is_absolute():
        dst = paths.repo / dst
    if dst.is_dir() or target.endswith("/"):
        dst = dst / "verdict.json"
    v = json.loads(src.read_text(encoding="utf-8"))
    rep = verify_file(_corpus(paths), v)
    if not rep["all_verified"]:
        sys.exit(f"refusing to export: {rep['counts']}")
    if dst.exists() and dst.resolve() != src.resolve():
        backup = paths.state / "backups" / f"{dst.name}.{_stamp()}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(dst.read_bytes())
        print(f"previous {dst.name} backed up to {backup}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"exported {dst}  ({rep['total']} quotes, all verified)")


def _stamp() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def cmd_export(a):
    if GUARD:
        sys.exit("not available for the Security Guard (it has no suspects or verdict)")
    _export(_paths(a), a.to)


def cmd_repair(a):
    from .repair import repair_verdict
    from .verdict import verify_file
    paths = _paths(a)
    f = Path(a.file)
    v = json.loads(f.read_text(encoding="utf-8"))
    corpus = _corpus(paths)
    new, log = repair_verdict(corpus, v)
    for row in log:
        print(f"[{row['action']}] {row['suspect']}: {row['from']['source']} → {row['to']['source']}  ({row['why']})")
    rep = verify_file(corpus, new)
    print(f"\nafter repair: {rep['total']} quotes {rep['counts']}")
    need = [r for r in log if r["action"] == "needs-human"]
    if need:
        print(f"{len(need)} item(s) need a person — left unchanged")
    out = f if a.in_place else Path(a.out or f.with_name(f.stem + ".repaired.json"))
    if a.in_place:
        backup = paths.state / "backups" / f"{f.name}.{_stamp()}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(f.read_bytes())
        print(f"original backed up to {backup}")
    out.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logp = paths.output / f"repair_{f.stem}.json"
    logp.parent.mkdir(parents=True, exist_ok=True)
    logp.write_text(json.dumps({"file": str(f), "changes": log, "after": rep["counts"]}, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    print(f"wrote {out}\nchange log {logp}")


def _print_summary(res, ver, tasks_or_list, paths, baseline=None):
    print()
    print(f"CULPRIT  {res['culprit_name']}   confidence {res['confidence']}")
    if res.get("basis"):
        print(f"basis    {res['basis']}")
    if baseline and baseline.get("culprit") != res.get("culprit"):
        print(f"tools-only baseline says: {baseline['culprit_name']} ({baseline['confidence']})")
    print()
    print(f"{'suspect':22s} {'verdict':11s} {'score':>6s}  presence        echo         own account     knowledge")
    for x in sorted(res["profiles"], key=lambda x: -x["score"]):
        flag = "  ← misleading, explained" if x["misleading"] else ""
        print(f"{x['name']:22s} {x['verdict']:11s} {x['score']:+6.2f}  {x['presence']:15s} {x['echo']:12s} "
              f"{x['statement']:15s} {x['knowledge']}{flag}")
    if ver:
        print(f"\nquotes in verdict.json: {ver['total']}  {ver['counts']}")
    tasks = tasks_or_list.tasks if hasattr(tasks_or_list, "tasks") else tasks_or_list
    op = [t for t in tasks if (t.status if hasattr(t, "status") else t["status"]) == "open"]
    h = sum(1 for t in op if (t.kind if hasattr(t, "kind") else t["kind"]) == "human")
    print(f"open tasks: {h} human, {len(op) - h} agent   →  {CLI} tasks")
    print(f"outputs:    {paths.output}/verdict.json  ·  {paths.context_dir}/")


def cmd_status(a):
    paths = _paths(a)
    st = _state(paths)
    if GUARD:
        _print_posture(st["posture"], st["tasks"], paths)
        return
    _print_summary(st["argue"], st.get("verification"), st["tasks"], paths, st.get("baseline"))
    rv = st.get("reviews_summary") or {}
    if rv:
        print(f"mode: {st.get('mode')} · proposals: {rv.get('accepted', 0)} accepted, {rv.get('amended', 0)} amended, "
              f"{rv.get('rejected', 0)} rejected, {rv.get('proposed', 0)} awaiting review · "
              f"agent findings: {(st.get('agent_findings') or {}).get('accepted', 0)}")


def cmd_search(a):
    paths = _paths(a)
    hits = _corpus(paths).search(a.pattern, regex=not a.fixed, path_prefix=a.in_ or "", limit=a.limit)
    for h in hits:
        t = h["text"].strip()
        print(f"{h['source']}\t{t[:220]}{' [OCR]' if h['ocr'] else ''}")
    if not hits:
        print("(no hits)")


def cmd_files(a):
    """What is in the data, so searches can be narrowed with --in."""
    paths = _paths(a)
    if a.prefix:
        rows = [r for r in _corpus(paths).inventory() if any(x in r["path"] for x in a.prefix.split(","))]
        for r in rows:
            print(f"{r['path']:60s} {r['words']:8,d} words  {r['kind']}{'  (OCR)' if r['ocr'] else ''}")
        if not rows:
            print(f"no file path contains {a.prefix!r} — run `files` without an argument for the groups")
        return
    groups = {}
    for row in _corpus(paths).inventory():
        top = row["path"].split("/")[0] + ("/" if "/" in row["path"] else "")
        g = groups.setdefault(top, {"files": 0, "words": 0, "kinds": set(), "ocr": False})
        g["files"] += 1
        g["words"] += row["words"]
        g["kinds"].add(row["kind"])
        g["ocr"] |= row["ocr"]
    for top, g in sorted(groups.items()):
        print(f"{top:34s} {g['files']:4d} file(s) {g['words']:8,d} words  {', '.join(sorted(g['kinds']))}{'  (OCR)' if g['ocr'] else ''}")
    print(f"\nNarrow a search with --in <any part of a path>, e.g. {CLI} search \"revoke\" --in jira")


def cmd_show(a):
    paths = _paths(a)
    c = _corpus(paths)
    doc, s, e = c.resolve(a.source)
    if doc is None:
        sys.exit(f"unknown source {a.source}")
    if doc.kind == "text":
        s = s or 1
        e = e or s
        for i in range(max(1, s - a.context), min(len(doc.lines), e + a.context) + 1):
            mark = ">" if s <= i <= e else " "
            print(f"{mark}{i:6d}  {doc.lines[i - 1]}")
    elif doc.kind == "pdf":
        for p, t in doc.pages.items():
            if s is None or p == s:
                print(f"--- page {p}{' (OCR)' if doc.page_ocr.get(p) else ''} ---\n{t}")
    elif doc.kind == "xlsx":
        for r, cells in doc.rows.items():
            if s is None or abs(r - s) <= a.context:
                print(f"{'>' if r == s else ' '}{r:4d}  " + " · ".join(cells))
    elif doc.kind == "image":
        print(f"--- {doc.path} (OCR text, confirm against the image) ---\n{doc.ocr_text}")


def cmd_verify_quote(a):
    paths = _paths(a)
    r = _corpus(paths).verify(a.source, a.quote)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r["status"] in ("verified", "whitespace") else 1)


def cmd_verify(a):
    from .verdict import verify_file
    paths = _paths(a)
    f = Path(a.file) if a.file else paths.output / "verdict.json"
    v = json.loads(f.read_text(encoding="utf-8"))
    rep = verify_file(_corpus(paths), v)
    for r in rep["rows"]:
        mark = "OK " if r["status"] == "verified" else "!! "
        extra = f"  → {r['suggestion']}" if r.get("suggestion") else ""
        print(f"{mark}{r['status']:12s} {r['source']:48s} {r['quote'][:60]!r}{extra}")
    print(f"\n{f}: {rep['total']} quotes {rep['counts']} · suspects listed: {rep['suspects']}")
    sys.exit(0 if rep["all_verified"] else 1)


def cmd_time(a):
    """Convert a raw time value (chat epoch, UTC ISO, card-feed Z time) to UTC and the case's local time."""
    from datetime import datetime
    from .records import Records
    from .util import UTC
    zone = Records(_corpus(_paths(a))).zone
    for raw in a.values:
        try:
            if raw.replace(".", "", 1).isdigit():
                dt = datetime.fromtimestamp(float(raw), tz=UTC)
            else:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    print(f"{raw}: no zone given — say whether it is UTC (…Z) or local")
                    continue
        except ValueError:
            print(f"{raw}: not an epoch or ISO time")
            continue
        loc = dt.astimezone(zone)
        print(f"{raw:>26s}  UTC {dt.astimezone(UTC):%a %d.%m.%Y %H:%M:%S}   local {loc:%a %d.%m.%Y %H:%M:%S} ({zone}, UTC{loc:%z})")


def cmd_timeline(a):
    from .engine import Investigation
    paths = _paths(a)
    inv = Investigation(paths)
    from . import sweep
    sweep.run(inv)  # timeline shows the fixed (clock-corrected) view
    op0, op1 = inv.op
    lo = op0 - timedelta(hours=a.hours)
    hi = op1 + timedelta(hours=a.hours)
    who = inv.case.suspect_by_name(a.suspect) if a.suspect else None
    kinds = tuple(a.kinds.split(",")) if a.kinds else ("card", "garage", "slack", "calendar", "email", "jira", "jira_comment", "ticket")
    evs = inv.events_for(who, kinds, lo, hi) if who else inv.rec.between(lo, hi, kinds)
    print(f"operation window {fmt_dt(op0)} → {fmt_dt(op1)}   (± {a.hours} h)")
    for e in evs:
        mark = "█" if op0 <= e.t <= op1 else " "
        fix = f" [{e.attrs['clock_fix']}]" if e.attrs.get("clock_fix") else ""
        print(f"{mark} {fmt_dt(e.t)}  {e.kind:12s} {str(e.actor or '')[:18]:18s} {e.text[:90]}  ({e.source}){fix}")


def cmd_suspect(a):
    if GUARD:
        sys.exit("not available for the Security Guard (it has no suspects or verdict)")
    paths = _paths(a)
    st = _state(paths)
    name = a.name.lower()
    prof = next((x for x in st["argue"]["profiles"] if name in x["name"].lower() or name == x["key"]), None)
    if not prof:
        sys.exit("unknown suspect")
    print(f"{prof['name']} — {prof['verdict']} (score {prof['score']:+.2f})")
    print(f"presence: {prof['presence']} · knowledge: {prof['knowledge']} · echo: {prof['echo']} · "
          f"own account: {prof['statement']} · link: {prof['link']}\n")
    for f in sorted([f for f in st["findings"] if f["suspect"] == prof["key"]], key=lambda f: -abs(f["score"])):
        print(f"{f['id']} {f['icon']} [{f['constraint']}] {f['title']} ({f['score']:+.2f})")
        print(f"      {f['claim']}")
        for e in f["evidence"][:3]:
            print(f"      - {e['source']} :: {e['quote'][:110]!r} [{e['status']}]")


def cmd_tasks(a):
    paths = _paths(a)
    st = _state(paths)
    book = TaskBook(paths.state)
    for t in st["tasks"]:
        res = book.resolutions.get(t["key"])
        if not a.all and res:
            continue
        if a.kind and t["kind"] != a.kind:
            continue
        s = f"✅ {res['decision']}" if res else "open"
        print(f"{t['id']:5s} p{t['priority']} {t['kind']:6s} {t['topic']:12s} {s:12s} {t['title']}")


def _find_task(paths, ident):
    st = _state(paths)
    t = next((t for t in st["tasks"] if t["id"] == ident or t["key"] == ident), None)
    if not t:
        sys.exit(f"no task {ident}")
    return t


def cmd_task(a):
    paths = _paths(a)
    t = _find_task(paths, a.id)
    if a.action == "show":
        print(json.dumps(t, ensure_ascii=False, indent=1))
        return
    book = TaskBook(paths.state)
    obj = Task(**{k: t[k] for k in ("kind", "topic", "title", "why", "question", "read", "options", "effect",
                                     "subject", "suspect", "priority", "id")})
    book.add(obj)
    if a.action == "reopen":
        book.reopen(obj.key)
        print(f"{t['id']} reopened")
    else:
        extra = {}
        if a.value is not None:
            extra["value"] = a.value
        if a.text:
            extra["text"] = a.text
        book.resolve(obj.key, a.decision, a.note or "", by=a.by, extra=extra)
        print(f"{t['id']} resolved: {a.decision}")
    if a.rerun:
        inv = _run_pipeline(paths, log=lambda m: None)
        if GUARD:
            _print_posture(inv.results["posture"], inv.tasks, paths)
        else:
            _print_summary(inv.results["argue"], inv.results.get("verification"), inv.tasks, paths)
    else:
        print(f"re-run to apply: {CLI} run")


def cmd_finding_add(a):
    paths = _paths(a)
    if len(a.source) != len(a.quote):
        sys.exit("give one --quote per --source")
    if GUARD:
        if not a.severity:
            sys.exit("the Security Guard needs --severity (and usually --category/--state/--subject)")
        a.constraint = a.category or a.constraint
    elif not a.suspect:
        sys.exit("--suspect is required for the investigator")
    data = {"suspect": a.suspect, "constraint": a.constraint, "cls": a.cls, "title": a.title, "claim": a.claim,
            "severity": a.severity, "state": a.state, "subject": a.subject,
            "reasoning": a.reasoning or "", "weight": a.weight, "by": a.by or actor(), "explains": a.explains,
            "reliability": a.reliability,
            "evidence": [{"source": s, "quote": q} for s, q in zip(a.source, a.quote)]}
    res = pipeline.add_agent_finding(paths, data)
    for c in res["checks"]:
        print(f"{c['status']:12s} {c['source']}  {c['detail']}")
    print("ACCEPTED — will be used on the next run" if res["accepted"] else "REJECTED — no quote was found at its source")
    if res["accepted"]:
        Workspace(paths.state).log(a.by or actor(), "finding", {"suspect": a.suspect, "cls": a.cls, "title": a.title,
                                                                "sources": a.source})
    sys.exit(0 if res["accepted"] else 1)


# ---------------------------------------------------------------- agent workflow
def _item(st, ident):
    for f in st["findings"]:
        if f["id"] == ident or f["key"] == ident:
            return "finding", f
    for i in st["issues"]:
        if i["id"] == ident or i["key"] == ident:
            return "issue", i
    return None, None


def cmd_frame(a):
    st = _state(_paths(a))
    c = st["case"]
    print("FRAME (derived from the bundle)\n")
    for k, f in c["facts"].items():
        v = f["value"]
        v = " → ".join(v) if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and "T" in v[0] else v
        print(f"{k:22s} {v}\n{'':22s} {f['source']}  “{f['quote'][:110]}”  {f.get('note', '')}")
    print("\nSUSPECTS")
    for s in c["suspects"]:
        print(f"  {s['name']:20s} handle {s['handle']}  plates {', '.join(s['plates']) or '—'}  cards "
              f"{', '.join(s['card_last4']) or '—'}  interviews {len(s['interviews'])}  offices {', '.join(s['offices']) or '—'}")
    print("\nOPERATION TIMELINE")
    for pt in c.get("operation_points", []):
        print(f"  {pt['t'][:16]}  {pt['text'][:90]}  ({pt['source']})")


def cmd_proposals(a):
    paths = _paths(a)
    st = _state(paths)
    ws = Workspace(paths.state)
    key = None
    if a.suspect:
        s = next((s for s in st["case"]["suspects"] if a.suspect.lower() in s["name"].lower() or a.suspect == s["handle"]), None)
        if not s:
            sys.exit("unknown suspect")
        key = s["handle"]
    rows = [f for f in st["findings"] if (key is None or f["suspect"] == key)
            and (not a.constraint or f["constraint"] == a.constraint)]
    if a.pending:
        rows = [f for f in rows if f["key"] not in ws.reviews and f["stage"] in ("sweep", "analyse")]
    sev = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for f in sorted(rows, key=lambda f: (sev.get((f.get("meta") or {}).get("severity"), 9), f["suspect"] or "",
                                         f["constraint"], -abs(f["score"]))):
        r = ws.reviews.get(f["key"])
        status = f"{r['decision']} ({r['by']})" if r else ("added by " + f["provenance"] if f["stage"] in ("bob", "human") else "PROPOSED")
        m = f.get("meta") or {}
        if m.get("kind") == "risk":
            flag = " · INCIDENT" if m.get("incident") else ""
            print(f"{f['id']} [{m['severity']}/{m['state']}] [{f['constraint']}] {f['title']}{flag}  — {status}")
        else:
            who = next((s["name"] for s in st["case"]["suspects"] if s["handle"] == f["suspect"]), "—")
            print(f"{f['id']} {f['icon']} [{f['constraint']}] {who}: {f['title']}  — {status}")
        print(f"      {f['claim'][:200]}")
        for e in f["evidence"][:2]:
            print(f"      · {e['source']}  “{e['quote'][:100]}”  [{e['status']}]")
    print(f"\n{len(rows)} item(s). Review with: {CLI} review <ID> accept|reject|amend --note \"…\"")


def cmd_issues(a):
    paths = _paths(a)
    st = _state(paths)
    ws = Workspace(paths.state)
    for i in st["issues"]:
        if a.kind and i["kind"] != a.kind:
            continue
        r = ws.reviews.get(i["key"])
        print(f"{i['id']} [{i['category']}] {i['severity']}/{i['resolution']} — {i['title']}"
              f"  → {r['decision'] + ' (' + r['by'] + ')' if r else 'UNDECIDED'}")
        print(f"      {i['observation'][:260]}")
        if i.get("fix"):
            print(f"      fix: {i['fix'][:200]}")


def cmd_review(a):
    paths = _paths(a)
    st = _state(paths)
    kind, item = _item(st, a.id)
    if item is None:
        sys.exit(f"no finding/issue {a.id} — run `{CLI} proposals` or `{CLI} issues`")
    if not a.note:
        sys.exit("a decision needs --note explaining why")
    if kind == "finding" and a.decision == "escalate":
        sys.exit("findings are accepted, rejected or amended; escalate is for inconsistencies/challenges")
    if kind == "issue" and a.decision == "amend" and item["kind"] not in ("remediation", "rootcause"):
        sys.exit("inconsistencies/challenges are accepted, rejected or escalated")
    if (a.severity or a.state) and a.decision != "amend":
        sys.exit("--severity/--state change a risk: use `amend`")
    counter = None
    if a.source:
        if not a.quote:
            sys.exit("--source needs --quote")
        r = _corpus(paths).verify(a.source, a.quote)
        print(f"{r['status']:12s} {a.source}  {r['detail']}")
        if r["status"] not in ("verified", "whitespace", "ocr"):
            sys.exit("REJECTED — the counter-citation's quote is not at its source")
        counter = {"source": a.source, "quote": a.quote, "status": r["status"]}
    ws = Workspace(paths.state)
    ws.review(item["key"], a.decision, a.note, by=a.by or actor(), cls=a.cls, weight=a.weight, counter=counter, id=a.id,
              severity=a.severity, state=a.state)
    extra = " A human task is created on the next run." if a.decision == "escalate" else ""
    print(f"{a.id}: {a.decision} recorded.{extra} Re-run (`{CLI} run --quiet`) to see the effect.")


def cmd_dig(a):
    from .dig import pack
    paths = _paths(a)
    inv = _run_pipeline(paths, log=lambda m: None)
    print(pack(inv, a.target))
    Workspace(paths.state).log(actor(), "dig", {"target": a.target})


def cmd_playbook(a):
    playbook = _playbook()
    paths = _paths(a)
    st = _state(paths)
    ws = Workspace(paths.state)
    for s in playbook.steps_for(st):
        p = playbook.progress(s, st, ws)
        mark = "✓" if p["complete"] else ("…" if p["status"] in ("in_progress", "incomplete") else " ")
        print(f"[{mark}] {s.id:28s} {p['status']:12s} {len(p['missing']):3d} open   {s.title}")
    print(f"\nmode: {ws.mode}   ·   next: {CLI} step show <ID>")


def cmd_step(a):
    playbook = _playbook()
    paths = _paths(a)
    st = _state(paths)
    ws = Workspace(paths.state)
    step = playbook.find(st, a.id)
    if not step:
        sys.exit(f"no step {a.id} — see `{CLI} playbook`")
    p = playbook.progress(step, st, ws)
    if a.action == "show":
        print(f"STEP {step.id} — {step.title}\nGOAL: {step.goal}\n\n{step.instructions}\n")
        print(f"status: {p['status']}" + (f" · summary: {p['summary']}" if p.get("summary") else ""))
        for m in p["missing"]:
            print(f"  open: {m}")
        return
    if a.action == "done":
        if p["missing"] and not a.force:
            print("Not done yet — still open:")
            for m in p["missing"]:
                print(f"  - {m}")
            sys.exit(1)
        if not a.summary:
            sys.exit("--summary is required")
        ws.set_step(step.id, "done", a.summary, by=a.by or actor())
        print(f"{step.id}: done")
    elif a.action == "reset":
        ws.set_step(step.id, "pending", by=a.by or actor())
        print(f"{step.id}: reset")


def cmd_verdict(a):
    if GUARD:
        sys.exit("not available for the Security Guard (it has no suspects or verdict)")
    paths = _paths(a)
    st = _state(paths)
    s = next((s for s in st["case"]["suspects"] if a.suspect.lower() in s["name"].lower() or a.suspect == s["handle"]), None)
    if not s:
        sys.exit("unknown suspect")
    ids = {f["id"] for f in st["findings"]}
    bad = [c for c in a.cite or [] if c not in ids]
    if bad:
        sys.exit(f"unknown finding id(s): {bad}")
    Workspace(paths.state).draft_verdict(s["name"], a.verdict, a.reasoning, a.cite or [], by=a.by or actor())
    print(f"{s['name']}: {a.verdict} drafted. Re-run to rebuild verdict.json.")


def cmd_confidence(a):
    if GUARD:
        sys.exit("not available for the Security Guard (it has no suspects or verdict)")
    paths = _paths(a)
    if not 0.05 <= a.value <= 0.95:
        sys.exit("confidence must be between 0.05 and 0.95")
    Workspace(paths.state).propose_confidence(a.value, a.why, by=a.by or actor())
    print(f"proposed {a.value}; a person signs it off (human task 'Sign off the confidence number').")


def cmd_memory(a):
    """The agent's working memory across steps (investigation/notes/<agent>_memory.md)."""
    paths = _paths(a)
    f = paths.repo / PROFILE["notes"]
    f.parent.mkdir(parents=True, exist_ok=True)
    if a.action == "show":
        print(f.read_text(encoding="utf-8") if f.exists() else "(no memory yet — add with `memory add`)")
        return
    text = " ".join(a.text or []).strip()
    if not text:
        sys.exit("memory add needs text")
    from datetime import datetime
    header = f"\n## {a.section or 'note'} · {datetime.now():%Y-%m-%d %H:%M} · {a.by or actor()}\n"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(header + text.replace("\\n", "\n") + "\n")
    Workspace(paths.state).log(a.by or actor(), "memory", {"section": a.section, "text": text[:300]})
    print(f"added to {PROFILE['notes']}")


def cmd_note(a):
    paths = _paths(a)
    Workspace(paths.state).log(a.by or actor(), "note", {"text": a.text, "step": a.step})
    print("noted")


def cmd_mode(a):
    paths = _paths(a)
    ws = Workspace(paths.state)
    if a.mode:
        ws.set_mode(a.mode)
    print(f"mode: {ws.mode}  ({'only findings the agent reviewed or added count' if ws.mode == 'agent' else 'every tool proposal counts'})")


def cmd_agent(a):
    from . import agent
    paths = _paths(a)
    if a.action == "log":
        runs = agent.list_runs(paths)
        if not runs:
            sys.exit("no agent runs yet")
        run = a.target or runs[0]["run"]
        evs, _ = agent.read_events(paths, run)
        for e in evs:
            t = e.get("type")
            step = e.get("step", "")
            if t == "tool_call":
                print(f"[{step}] $ {e.get('command') or e.get('title')}")
            elif t == "tool_result":
                print("   " + (e.get("output") or "").strip().replace("\n", "\n   ")[:1200])
            elif t == "permission" and not e.get("allowed"):
                print(f"[{step}] ✗ denied: {e.get('command') or e.get('title')} ({e.get('why')})")
            elif t in ("message", "prompt", "system"):
                label = {"message": "BOB", "prompt": "ORCHESTRATOR", "system": "·"}[t]
                print(f"[{step}] {label}: {e.get('text', '')[:2000]}")
        return
    orch = agent.Orchestrator(paths, log=print, profile=PROFILE["id"])
    try:
        if a.action == "run":
            steps = [s.strip() for s in a.steps.split(",")] if a.steps else None
            res = orch.run_playbook(steps, depth=a.depth, max_nudges=a.nudges, redo=a.redo)
        elif a.action == "dig":
            if not a.target:
                sys.exit("agent dig needs a TARGET (F-001, I-02, a suspect name or path:line)")
            res = orch.dig(a.target, a.question, depth=a.depth)
        else:
            sys.exit("unknown action")
    except KeyboardInterrupt:
        orch.cancel()
        sys.exit("cancelled")
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"\ntrace: {CLI} agent log {res['run']}")
    if res.get("error"):
        print(f"\n✗ {res['error']}")
        sys.exit(1)


def cmd_bob(a):
    paths = _paths(a)
    if a.id == "status":
        print(json.dumps(bobmod.status(), indent=1))
        return
    t = _find_task(paths, a.id)
    obj = Task(**{k: t[k] for k in ("kind", "topic", "title", "why", "question", "read", "options", "effect",
                                     "subject", "suspect", "priority", "id")})
    if a.prompt_only:
        print(bobmod.prompt_for(obj, CLI))
        return
    res = bobmod.dispatch(obj, paths.repo, paths.state, cli=CLI, max_turns=a.max_turns)
    print(json.dumps({k: v for k, v in res.items() if k != "prompt"}, indent=1, ensure_ascii=False))
    if not res.get("ok") and res.get("prompt"):
        print("\n--- paste this into `bob chat` (Investigator mode) ---\n")
        print(res["prompt"])


def cmd_docs(a):
    paths = _paths(a)
    d = paths.context_dir
    files = sorted(d.glob("*.md"))
    if not a.name:
        for f in files:
            print(f.name)
        return
    f = next((f for f in files if a.name in f.name), None)
    if not f:
        sys.exit("no such document")
    print(f.read_text(encoding="utf-8"))


def cmd_serve(a):
    from .server import serve
    serve(_paths(a), host=a.host, port=a.port, open_browser=a.open, team=a.team)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="investigate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", help="case_bundle directory exactly as received (auto-detected)")
    ap.add_argument("--workdir", help="where state and outputs go (default: <repo>/investigation)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run the whole pipeline")
    p.add_argument("--team", default="bob-investigator")
    p.add_argument("--no-ocr", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--export", metavar="PATH", help="also write the verified verdict.json here (e.g. submissions/<team>/)")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("export", help="copy the investigator's verdict.json to PATH (verified first)")
    p.add_argument("to", nargs="?", default="verdict_investigator.json")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("repair", help="fix citations of any verdict.json against the bundle as received")
    p.add_argument("file")
    p.add_argument("--out")
    p.add_argument("--in-place", action="store_true", help="overwrite FILE (a backup is kept)")
    p.set_defaults(fn=cmd_repair)

    p = sub.add_parser("serve", help="local web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true")
    p.add_argument("--team", default="bob-investigator")
    p.set_defaults(fn=cmd_serve)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    p = sub.add_parser("search", help="regex search with citations")
    p.add_argument("pattern")
    p.add_argument("--in", dest="in_", help="any part of a path, comma-separated: slack_export/, interviews, card_feed")
    p.add_argument("--fixed", action="store_true", help="plain text, not regex")
    p.add_argument("--limit", type=int, default=60)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("files", help="what is in the data (for --in); `files <part>` lists the files in a group")
    p.add_argument("prefix", nargs="?")
    p.set_defaults(fn=cmd_files)

    p = sub.add_parser("show", help="read a citation in context")
    p.add_argument("source")
    p.add_argument("-C", "--context", type=int, default=3)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("verify-quote")
    p.add_argument("source")
    p.add_argument("quote")
    p.set_defaults(fn=cmd_verify_quote)

    p = sub.add_parser("verify", help="check every quote in a verdict.json")
    p.add_argument("file", nargs="?")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("time", help="convert epoch / UTC times to the case's local time")
    p.add_argument("values", nargs="+")
    p.set_defaults(fn=cmd_time)

    p = sub.add_parser("timeline")
    p.add_argument("--suspect")
    p.add_argument("--hours", type=int, default=12)
    p.add_argument("--kinds", help="comma list: card,garage,slack,calendar,email,jira,ticket")
    p.set_defaults(fn=cmd_timeline)

    p = sub.add_parser("suspect")
    p.add_argument("name")
    p.set_defaults(fn=cmd_suspect)

    p = sub.add_parser("tasks")
    p.add_argument("--kind", choices=["human", "agent"])
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_tasks)

    p = sub.add_parser("task")
    p.add_argument("action", choices=["show", "resolve", "reopen"])
    p.add_argument("id")
    p.add_argument("--decision")
    p.add_argument("--note")
    p.add_argument("--value", type=float, help="confidence value for the calibration task")
    p.add_argument("--text", help="corrected quote for an OCR task")
    p.add_argument("--by", default="human")
    p.add_argument("--rerun", action="store_true")
    p.set_defaults(fn=cmd_task)

    p = sub.add_parser("finding", help="add a finding (quotes are verified first)")
    p.add_argument("action", choices=["add"])
    p.add_argument("--suspect")
    p.add_argument("--constraint", default="lead",
                   choices=["presence", "statement", "echo", "knowledge", "link", "lead", "capability"])
    p.add_argument("--category", help="Security Guard: risk category, e.g. stale-access, logging-gap")
    p.add_argument("--severity", choices=["critical", "high", "medium", "low"])
    p.add_argument("--state", choices=["open", "addressed", "check"], default=None)
    p.add_argument("--subject", help="Security Guard: the system/account/room the risk is about")
    p.add_argument("--class", dest="cls", default="NEUTRAL",
                   choices=["INCRIMINATES", "WEAKLY_INCRIMINATES", "EXONERATES", "PROVES_INNOCENCE", "NEUTRAL"])
    p.add_argument("--title", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--source", action="append", required=True)
    p.add_argument("--quote", action="append", required=True)
    p.add_argument("--reasoning")
    p.add_argument("--weight", type=float, default=0.3)
    p.add_argument("--reliability", default="derived")
    p.add_argument("--explains", help="key of the finding this explains")
    p.add_argument("--by")
    p.set_defaults(fn=cmd_finding_add)

    p = sub.add_parser("frame", help="the derived case frame with sources")
    p.set_defaults(fn=cmd_frame)

    p = sub.add_parser("proposals", help="the tools' proposals and the agent's decisions")
    p.add_argument("--suspect")
    p.add_argument("--constraint")
    p.add_argument("--pending", action="store_true")
    p.set_defaults(fn=cmd_proposals)

    p = sub.add_parser("issues", help="inconsistencies, challenges, root causes, remediations")
    p.add_argument("--kind", choices=["sweep", "adversarial", "rootcause", "remediation"])
    p.set_defaults(fn=cmd_issues)

    p = sub.add_parser("review", help="the agent's decision on a proposal, inconsistency or challenge")
    p.add_argument("id")
    p.add_argument("decision", choices=["accept", "reject", "amend", "escalate"])
    p.add_argument("--note")
    p.add_argument("--class", dest="cls",
                   choices=["INCRIMINATES", "WEAKLY_INCRIMINATES", "EXONERATES", "PROVES_INNOCENCE", "NEUTRAL"])
    p.add_argument("--weight", type=float)
    p.add_argument("--severity", choices=["critical", "high", "medium", "low"], help="Security Guard: re-rate a risk")
    p.add_argument("--state", choices=["open", "addressed", "check"], help="Security Guard: open or fixed")
    p.add_argument("--source", help="counter-citation (verified)")
    p.add_argument("--quote")
    p.add_argument("--by")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("dig", help="context pack for going deeper")
    p.add_argument("target")
    p.set_defaults(fn=cmd_dig)

    sub.add_parser("playbook", help="the steps and what is still open").set_defaults(fn=cmd_playbook)

    p = sub.add_parser("step")
    p.add_argument("action", choices=["show", "done", "reset"])
    p.add_argument("id")
    p.add_argument("--summary")
    p.add_argument("--force", action="store_true")
    p.add_argument("--by")
    p.set_defaults(fn=cmd_step)

    p = sub.add_parser("verdict", help="the agent's verdict drafts")
    p.add_argument("action", choices=["draft"])
    p.add_argument("--suspect", required=True)
    p.add_argument("--verdict", required=True, choices=["culprit", "cleared", "unresolved"])
    p.add_argument("--reasoning", required=True)
    p.add_argument("--cite", action="append")
    p.add_argument("--by")
    p.set_defaults(fn=cmd_verdict)

    p = sub.add_parser("confidence")
    p.add_argument("action", choices=["propose"])
    p.add_argument("value", type=float)
    p.add_argument("--why", required=True)
    p.add_argument("--by")
    p.set_defaults(fn=cmd_confidence)

    p = sub.add_parser("memory", help="the agent's case memory across steps: show | add \"text\"")
    p.add_argument("action", choices=["show", "add"])
    p.add_argument("text", nargs="*")
    p.add_argument("--section", help="heading, e.g. the step id")
    p.add_argument("--by")
    p.set_defaults(fn=cmd_memory)

    p = sub.add_parser("note", help="add a reasoning note to the journal")
    p.add_argument("text")
    p.add_argument("--step")
    p.add_argument("--by")
    p.set_defaults(fn=cmd_note)

    p = sub.add_parser("mode")
    p.add_argument("mode", nargs="?", choices=["agent", "autopilot"])
    p.set_defaults(fn=cmd_mode)

    p = sub.add_parser("agent", help="Bob works the playbook (ACP, uses your Bob login)")
    p.add_argument("action", choices=["run", "dig", "log"])
    p.add_argument("target", nargs="?")
    p.add_argument("--steps", help="comma list: frame,sweep,suspect,crosscheck,challenge,verdict or suspect:<handle>")
    p.add_argument("--depth", default="normal", choices=["quick", "normal", "deep"])
    p.add_argument("--nudges", type=int, default=2)
    p.add_argument("--redo", action="store_true")
    p.add_argument("--question")
    p.set_defaults(fn=cmd_agent)

    p = sub.add_parser("bob", help="hand an agent task to Bob (headless), or `bob status`")
    p.add_argument("id")
    p.add_argument("--prompt-only", action="store_true")
    p.add_argument("--max-turns", type=int, default=30)
    p.set_defaults(fn=cmd_bob)

    p = sub.add_parser("docs")
    p.add_argument("name", nargs="?")
    p.set_defaults(fn=cmd_docs)

    a = ap.parse_args(argv)
    if a.cmd == "task" and a.action == "resolve" and not a.decision:
        ap.error("task resolve needs --decision")
    a.fn(a)


if __name__ == "__main__":
    main()
