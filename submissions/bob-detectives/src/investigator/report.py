"""Write the context documents — the automated counterpart of the manual Context/ folder."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from . import argue
from .engine import Investigation
from .findings import CLASSES, CONSTRAINTS
from .util import fmt_dt


def _cite(e) -> str:
    q = e.quote.replace("|", "\\|").replace("\n", " ")
    if len(q) > 140:
        q = q[:139] + "…"
    flag = " *(OCR)*" if e.status == "ocr" else ("" if e.usable else f" **[{e.status}]**")
    return f"`{e.source}` — “{q}”{flag}"


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def write_all(inv: Investigation) -> list[Path]:
    prev = inv.store.include_proposed
    inv.store.include_proposed = True     # documents show proposals too, marked as such
    try:
        return _write_all(inv)
    finally:
        inv.store.include_proposed = prev


def _status(f) -> str:
    if f.status == "proposed":
        return " *(proposed — awaiting agent review)*"
    if f.review:
        word = {"accept": "accepted", "reject": "rejected", "amend": "amended"}.get(f.review["decision"], f.review["decision"])
        return f" *({word} by {f.review['by']}: {f.review.get('note', '')[:80]})*"
    if f.stage in ("bob", "human"):
        return f" *(added by {f.provenance})*"
    return ""


def _write_all(inv: Investigation) -> list[Path]:
    d = inv.paths.context_dir
    d.mkdir(parents=True, exist_ok=True)
    docs = {
        "01_case_context.md": case_context(inv),
        "02_inconsistencies.md": inconsistencies(inv),
        "03_evidence_relevance.md": evidence_relevance(inv),
        "04_findings_log.md": findings_log(inv),
        "05_argumentation.md": argumentation(inv),
        "06_adversarial.md": adversarial(inv),
        "07_tasks_agent.md": tasks(inv, "agent"),
        "08_tasks_human.md": tasks(inv, "human"),
        "09_verdict_summary.md": verdict_summary(inv),
        "10_security_remaining.md": security_remaining(inv),
    }
    out = []
    for name, text in docs.items():
        p = d / name
        p.write_text(text, encoding="utf-8")
        out.append(p)
    state = {
        "case": inv.case.summary(),
        "hints": inv.hints,
        "issues": [i.to_dict() for i in inv.store.issues],
        "findings": [f.to_dict() for f in inv.store.findings],
        "tasks": [t.to_dict() for t in inv.tasks.tasks],
        "argue": inv.results.get("argue"),
        "baseline": inv.results.get("baseline"),
        "security": inv.results.get("security"),
        "mode": inv.ws.mode,
        "reviews_summary": inv.results.get("reviews"),
        "agent_findings": inv.results.get("agent_findings"),
        "steps": inv.ws.steps,
        "drafts": inv.ws.drafts,
        "robustness": inv.results.get("robustness"),
        "verification": inv.results.get("verification"),
        "clock_fixes": inv.clock_fixes,
        "plate_resolutions": inv.plate_resolutions,
        "sightings": inv.sightings,
        "leaks": [{"t": lk.t.isoformat(), "room": lk.room, "channel": lk.channel,
                   "audience": [{k: v for k, v in a.items() if k != "evidence"} for a in lk.audience]}
                  for lk in inv.leaks],
        "stages": inv.stage_log,
        "time_basis": inv.rec.time_basis,
        "inventory": inv.corpus.inventory(),
    }
    sp = inv.paths.output / "investigation.json"
    sp.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    out.append(sp)
    return out


# ---------------------------------------------------------------- documents
def case_context(inv: Investigation) -> str:
    c = inv.case
    L = ["# Case context (generated)", "",
         "> Derived from the bundle by the pipeline. Every fact below cites where it came from. "
         "The suspect names are the only typed-in input (from verdict_template.json).", ""]
    L += ["## Frame", "", "| Fact | Value | Source | Quote |", "|---|---|---|---|"]
    for k, f in c.facts.items():
        v = f.value
        if isinstance(v, tuple):
            v = " → ".join(fmt_dt(x) for x in v)
        elif hasattr(v, "isoformat"):
            v = fmt_dt(v)
        L.append(f"| {k} | {_md_escape(str(v))} | `{f.source}` | {_md_escape(f.quote)[:120]} |")
    ops = c.summary().get("operation_points", [])
    if ops:
        L += ["", "### Operation timeline (converted to local time)", ""]
        for pt in ops:
            L.append(f"- {pt['t'][:16].replace('T', ' ')}{' (approx.)' if pt['approx'] else ''} — {pt['text']} (`{pt['source']}`)")
    L += ["", "## Suspects and their identifiers", "",
          "| Suspect | Handle | Title | Plate(s) | Card | Calendar | Interviews | Office |", "|---|---|---|---|---|---|---|---|"]
    for p in c.suspects:
        L.append(f"| {p.name} | {p.handle or '—'} | {p.title} | {', '.join(p.plates) or '—'} | "
                 f"{', '.join(sorted(p.card_last4)) or '—'} | {p.calendar or '—'} | {len(p.interviews)} | "
                 f"{', '.join(o[0] for o in p.offices) or '—'} |")
    L += ["", "## Sources and their time basis", "", "| Source | Kind | Words | Time basis |", "|---|---|---|---|"]
    tb = inv.rec.time_basis
    groups = defaultdict(lambda: [0, 0, set()])
    for row in inv.corpus.inventory():
        path = row["path"]
        key = path.split("/")[0] + "/" if "/" in path else path
        g = groups[key]
        g[0] += 1
        g[1] += row["words"]
        g[2].add(row["kind"])
    for key, (n, words, kinds) in sorted(groups.items()):
        basis = tb.get(key) or next((v for p, v in tb.items() if p.startswith(key)), "—")
        if key == "calendars/":
            basis = "; ".join(sorted({v.split(":")[-1].strip() for p, v in tb.items() if p.startswith(key)}))
        L.append(f"| `{key}` ({n} file{'s' if n > 1 else ''}) | {', '.join(sorted(kinds))} | {words:,} | {_md_escape(basis)} |")
    if c.warnings or inv.rec.warnings or inv.corpus.warnings:
        L += ["", "## Warnings", ""] + [f"- {w}" for w in c.warnings + inv.rec.warnings + inv.corpus.warnings]
    return "\n".join(L) + "\n"


def inconsistencies(inv: Investigation) -> str:
    L = ["# Inconsistency sweep (generated)", "",
         "> Run first, before any argument is built. Hints are places where a source warns about itself; "
         "inconsistencies are two records of the same thing that disagree. Each one is fixed with evidence, "
         "explained, or handed to a person.", ""]
    cats = Counter(h["category"] for h in inv.hints)
    L += ["## Hints found in the sources", "", "| Category | Count | Example |", "|---|---|---|"]
    for cat, n in cats.most_common():
        ex = next(h for h in inv.hints if h["category"] == cat)
        L.append(f"| {cat} | {n} | `{ex['source']}` — {_md_escape(ex['quote'])[:110]} |")
    L += ["", "## Inconsistencies", ""]
    for i in [x for x in inv.store.issues if x.kind == "sweep"]:
        L += [f"### {i.id} · {i.title}", "",
              f"**Category:** {i.category} · **Severity:** {i.severity} · **Resolution:** {i.resolution}", "",
              i.observation, ""]
        if i.fix:
            L += [f"**Fix / resolution:** {i.fix}", ""]
        if i.effect:
            L += [f"**Effect downstream:** {i.effect}", ""]
        if i.evidence:
            L += ["Evidence:", ""] + [f"- {_cite(e)}{(' — ' + e.note) if e.note else ''}" for e in i.evidence] + [""]
    if inv.clock_fixes:
        L += ["## Clock corrections applied", "", "```json", json.dumps(inv.clock_fixes, indent=1, default=str), "```", ""]
    return "\n".join(L) + "\n"


def evidence_relevance(inv: Investigation) -> str:
    use = Counter()
    sus = defaultdict(set)
    for f in inv.store.findings:
        for e in f.evidence:
            key = e.source.split(":")[0]
            key = key.split("/")[0] + "/" if key.startswith(("slack_export/", "calendars/", "interviews/", "evidence_photos/")) else key
            use[key] += abs(f.score) + 0.01
            if f.suspect:
                sus[key].add(inv.person(f.suspect).name.split()[0])
    ranked = use.most_common()
    L = ["# Evidence relevance (generated)", "",
         "> Ranked by how much weight the findings drawn from each source carry. Tier 1 decides the case; "
         "tier 3 was searched but contributes little.", "", "| Tier | Source | Weight carried | Suspects touched |",
         "|---|---|---|---|"]
    n = len(ranked)
    for k, (src, w) in enumerate(ranked):
        tier = "1" if k < max(3, n // 4) else ("2" if k < max(6, n // 2) else "3")
        L.append(f"| {tier} | `{src}` | {w:.2f} | {', '.join(sorted(sus[src]))} |")
    unused = sorted({r['path'].split('/')[0] for r in inv.corpus.inventory()} -
                    {s.split('/')[0].rstrip('/') for s in use})
    if unused:
        L += ["", "Not used by any finding: " + ", ".join(f"`{u}`" for u in unused)]
    return "\n".join(L) + "\n"


def findings_log(inv: Investigation) -> str:
    L = ["# Findings log (generated)", "",
         "> Every finding with its classification, weight and exact sources. Stage = where it was produced "
         "(sweep → analyse → bob/human → adversarial).", ""]
    by_stage = defaultdict(list)
    for f in inv.store.findings:
        by_stage[f.stage].append(f)
    for stage in ("sweep", "analyse", "bob", "human", "adversarial"):
        fs = by_stage.get(stage)
        if not fs:
            continue
        L += [f"## Stage: {stage}", "", "| # | Suspect | | Constraint | Finding | Sources |", "|---|---|---|---|---|---|"]
        for f in fs:
            who = inv.person(f.suspect).name if f.suspect else "—"
            srcs = "<br>".join(_cite(e) for e in f.evidence[:4])
            L.append(f"| {f.id} | {who} | {f.icon} | {f.constraint} | **{_md_escape(f.title)}** — {_md_escape(f.claim)} | {srcs} |")
        L.append("")
    return "\n".join(L) + "\n"


def argumentation(inv: Investigation) -> str:
    res = inv.results["argue"]
    L = ["# Argumentation (generated)", "",
         "> " + " · ".join(f"{v['icon']} {v['label']}" for v in CLASSES.values()), ""]
    op0, op1 = inv.op
    L += [f"Operation window (local): **{fmt_dt(op0)} → {fmt_dt(op1)}**. "
          f"Presence required: **{'yes' if inv.case.fact('presence_required') else 'unknown'}** "
          f"(`{inv.case.facts['presence_required'].source}` — “{inv.case.facts['presence_required'].quote}”)"
          if inv.case.fact("presence_required") else "", ""]
    L += ["## Constraint matrix", "",
          "| Suspect | Score | Presence | Knowledge route | Withheld-fact echo | Own account | Link | Verdict |",
          "|---|---|---|---|---|---|---|---|"]
    for x in sorted(res["profiles"], key=lambda x: -x["score"]):
        L.append(f"| {x['name']} | {x['score']:+.2f} | {x['presence']} | {x['knowledge']} | {x['echo']} | "
                 f"{x['statement']} | {x['link']} | **{x['verdict']}** |")
    L += [""]
    for x in sorted(res["profiles"], key=lambda x: -x["score"]):
        L += [f"## {x['name']} — {x['verdict'].upper()} ({x['score']:+.2f})", "",
              "| | Constraint | Finding | Weight | Reasoning | Evidence |", "|---|---|---|---|---|---|"]
        for f in sorted(inv.store.for_suspect(x["key"]), key=lambda f: -abs(f.score)):
            hist = f" *(was: {'; '.join(f.history)})*" if f.history else ""
            cav = f" ⚠ {'; '.join(f.caveats)}" if f.caveats else ""
            L.append(f"| {f.icon} | {f.constraint} | **{f.id} {_md_escape(f.title)}**{_status(f)} — {_md_escape(f.claim)}{hist} | "
                     f"{f.score:+.2f} | {_md_escape(f.reasoning)}{_md_escape(cav)} | "
                     f"{'<br>'.join(_cite(e) for e in f.evidence[:3])} |")
        triples = argue.judgement_triples(inv, x["key"])
        if triples:
            L += ["", "**Suspicion → paperwork → judgement**", ""]
            for t in triples:
                s, pw = t["suspicion"], t["paperwork"]
                L.append(f"- *Suspicion:* {s.title} ({_cite(s.evidence[0]) if s.evidence else 'no source'})")
                if pw:
                    L.append(f"  *Paperwork:* {pw.title} ({_cite(pw.evidence[0]) if pw.evidence else 'no source'})")
                    L.append(f"  *Judgement:* explained — weight lowered, not erased.")
                else:
                    L.append(f"  *Paperwork:* none found. *Judgement:* stands.")
        L.append("")
    cf = res["confidence_formula"]
    L += ["## Conclusion", "",
          f"**Culprit: {res['culprit_name']} · confidence {res['confidence']}**", "",
          f"- pillars pointing at the culprit: {', '.join(cf['pillars'])} ({len(cf['pillars'])})",
          f"- margin to the next suspect still standing: {cf['margin']:+.2f}",
          "- penalties: " + ("; ".join(f"{p['title']} (−{p['minus']})" for p in cf["penalties"]) or "none"),
          f"- human override: {cf['override'] if cf['override'] is not None else 'none'}", "",
          "Formula: `min(0.95, 0.5 + 0.08·pillars + 0.10·min(margin, 2.5)) − penalties`.", ""]
    if res["misleading"]:
        L += ["**Misleading suspects (looked like they knew what only the thief knew — explained):** "
              + ", ".join(inv.person(k).name for k in res["misleading"]), ""]
    return "\n".join(L) + "\n"


def adversarial(inv: Investigation) -> str:
    L = ["# Adversarial review (generated)", "", "> The pipeline trying to break its own case.", ""]
    for i in [x for x in inv.store.issues if x.kind == "adversarial"]:
        L += [f"## {i.id} · {i.title}", "", f"**Severity:** {i.severity} · **Resolution:** {i.resolution}", "",
              i.observation, ""]
        if i.fix:
            L += [f"**Answer:** {i.fix}", ""]
        if i.effect:
            L += [f"**Effect:** {i.effect}", ""]
        for e in i.evidence[:5]:
            L.append(f"- {_cite(e)}")
        L.append("")
    rob = inv.results.get("robustness") or []
    if rob:
        L += ["## Leave-one-analysis-out", "", "| Without | Top suspect | Same answer | Margin |", "|---|---|---|---|"]
        for r in rob:
            L.append(f"| {r['without']} | {inv.person(r['top']).name} | {'yes' if r['same'] else '**no**'} | {r['margin']:+.2f} |")
    down = [f for f in inv.store.findings if f.history]
    if down:
        L += ["", "## Downgraded / withdrawn findings", ""] + [f"- {f.id} {f.title}: {'; '.join(f.history)}" for f in down]
    return "\n".join(L) + "\n"


def tasks(inv: Investigation, kind: str) -> str:
    title = "Agent tasks — mechanical, source-verifiable" if kind == "agent" else "Human tasks — judgement calls"
    intro = ("> Each can be executed by Bob through the CLI (`investigate search/show/verify-quote/finding add`). "
             "Anything Bob adds is verified against the bundle before it is used."
             if kind == "agent" else
             "> Decisions only a person should make. Resolve in the UI or with "
             "`investigate task resolve <ID> --decision …`; the pipeline re-runs with your decision.")
    L = [f"# {title} (generated)", "", intro, ""]
    for t in [x for x in inv.tasks.tasks if x.kind == kind]:
        status = "✅ RESOLVED" if t.resolution else "OPEN"
        L += [f"## {t.id} · {status} · {t.title}", "",
              f"**Priority:** {t.priority} · **Topic:** {t.topic}" + (f" · **Suspect:** {inv.person(t.suspect).name}" if t.suspect and inv.person(t.suspect) else ""), "",
              f"**Why:** {t.why}", "", f"**Question:** {t.question}", ""]
        if t.read:
            L += ["**Read:**", ""] + [f"- `{r['source']}` — “{_md_escape(r['quote'])[:160]}”" + (f" ({r['note']})" if r.get("note") else "") for r in t.read] + [""]
        if t.options:
            L += ["**Options:** " + " · ".join(f"`{o}` → {t.effect.get(o, '')}" for o in t.options), ""]
        if t.resolution:
            L += [f"**Resolution:** `{t.resolution['decision']}` by {t.resolution.get('by')} at {t.resolution.get('at')}"
                  + (f" — {t.resolution['note']}" if t.resolution.get('note') else ""), ""]
    return "\n".join(L) + "\n"


def verdict_summary(inv: Investigation) -> str:
    res = inv.results["argue"]
    ver = inv.results.get("verification") or {}
    L = ["# Verdict summary (generated)", "",
         f"## {res['culprit_name']} — culprit · confidence {res['confidence']}", ""]
    c = res["culprit"]
    for f in sorted([f for f in inv.store.for_suspect(c) if f.cls == "INCRIMINATES"], key=lambda f: -f.score):
        L.append(f"- {f.icon} **{f.title}** — {f.claim}")
        for e in f.evidence[:2]:
            L.append(f"  - {_cite(e)}")
    L += ["", "## Everyone else", "", "| Suspect | Verdict | Why |", "|---|---|---|"]
    for x in res["profiles"]:
        if x["key"] == c:
            continue
        fs = inv.store.for_suspect(x["key"])
        top = sorted([f for f in fs if f.cls in ("PROVES_INNOCENCE", "EXONERATES")], key=lambda f: f.score)[:2]
        why = "; ".join(f"{f.icon} {f.title}" for f in top) or "—"
        if x["misleading"]:
            why += " · *misleading: echo of withheld facts explained*"
        L.append(f"| {x['name']} | {x['verdict']} | {_md_escape(why)} |")
    if ver:
        L += ["", f"**Quote check:** {ver.get('total')} quotes in verdict.json → {ver.get('counts')}"]
    return "\n".join(L) + "\n"


def security_remaining(inv: Investigation) -> str:
    sec = inv.results.get("security")
    if not sec:
        return "# Remaining security flaws\n\n(not computed)\n"
    icon = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "⬜"}
    L = ["# Remaining security flaws (generated)", "",
         "> The Security Guard's scanner run on the same data. First: weaknesses the incident exposed that are still in "
         "place. Then everything else still open, the process misdesign that lets these exist, and the remediations. "
         "IDs match the Security Guard (`src/guard`), where Bob triages them.", "",
         f"**{sec['open']} open** of {sec['total']} · " + " · ".join(f"{icon[s]} {s}: {n}" for s, n in sec["by_severity"].items()), ""]
    inc = [r for r in sec["risks"] if r["incident"] and r["state"] in ("open", "check")]
    L += ["## Exposed by this incident and still open", ""]
    for r in inc or []:
        L += [f"### {r['id']} · {icon[r['severity']]} {r['severity']} · {r['title']}", "", r["claim"], "",
              f"*Why it matters:* {r['reasoning']}", ""] + [f"- `{e['source']}` — “{_md_escape(e['quote'])[:150]}”" for e in r["evidence"][:3]] + [""]
    if not inc:
        L += ["None found on the attack path.", ""]
    L += ["## Everything else still open", "", "| ID | Severity | Risk | First source |", "|---|---|---|---|"]
    for r in [x for x in sec["risks"] if not x["incident"] and x["state"] in ("open", "check")]:
        e = r["evidence"][0] if r["evidence"] else {"source": "", "quote": ""}
        L.append(f"| {r['id']} | {icon[r['severity']]} {r['severity']} | {_md_escape(r['title'])} | `{e['source']}` |")
    L += ["", "## Process misdesign behind them", ""]
    for rc in sec["rootcauses"]:
        L += [f"- **{rc['id']} {rc['title']}** ({rc['severity']}; risks {', '.join(rc['risks'])}) — fix the process: {rc['fix']}"]
    L += ["", "## Remediations", ""]
    for m in sorted(sec["remediations"], key=lambda m: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(m["severity"], 9)):
        p = m["plan"]
        L += [f"- **{m['id']} {m['title']}** — owner {p.get('owner', '?')}. Now: {p.get('now', '')} Verify: {p.get('verify', '')}"]
    return "\n".join(L) + "\n"
