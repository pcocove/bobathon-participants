"""Security Guard analysis: current risks, the process misdesign behind them, remediations.

Shares the investigator's engine: the same corpus and records, the same quote gate
(`inv.evidence`), the same Finding/Issue/Task types, the same inconsistency sweep. It needs
no suspects — it reads the data for weaknesses that are still open.

  scan()          risk proposals (Finding with meta.severity/state/subject), grouped per subject
  root_causes()   process misdesign that lets those risks exist (Issue kind="rootcause")
  remediations()  standard remediations per root cause, tied to the risks (Issue kind="remediation")
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime

from . import security_lexicon as SL
from .engine import Investigation
from .findings import Evidence, Finding, FindingStore, Issue
from .tasks import Task
from .util import fmt_dt, norm_space

RESOLVED = re.compile(r"\b(revoked|fixed|resolved|closed|installed|replaced|rotated|removed|re-?scoped)\b", re.I)
TICKET_KEY = re.compile(r"\b([A-Z]{2,5}-\d{2,5})\b")
BACKTICK = re.compile(r"`([A-Za-z][\w./-]{2,40})`")


def _norm_chat(text: str) -> str:
    t = text.lower()
    t = re.sub(r"^(?:psa|reminder|fyi|update|again|honestly|small thing|quick one|for the record|ok so|"
               r"not to be dramatic but)[:,]?\s*", "", t)
    t = re.sub(r"\s*(?:lol|:\)|\(again\)|thanks all|send help|sorry|will update|more later|see [a-z]+-\d+|cc \w+)\s*$", "", t)
    return norm_space(t)


class _Group:
    def __init__(self, detector: str, subject: str | None, where: str):
        self.detector = detector
        self.subject = subject
        self.where = where
        self.hits: list[tuple[str, str, datetime | None, str]] = []  # (source, needle, t, text)
        self.extra: dict = {}

    def add(self, source, needle, t, text):
        if all(h[0] != source for h in self.hits):
            self.hits.append((source, needle, t, text))


def _ticket_index(inv: Investigation) -> list[dict]:
    """Every ticket (issue tracker + helpdesk) with status, dates and line numbers."""
    tickets = []
    for path, doc in inv.corpus.docs.items():
        if doc.kind != "text":
            continue
        if path.endswith(".json") and doc.lines and '"issues"' in "\n".join(doc.lines[:4]):
            cur = None
            for i, ln in enumerate(doc.lines, 1):
                s = ln.strip()
                m = re.match(r'"key":\s*"([^"]+)"', s)
                if m:
                    cur = {"system": "tracker", "id": m.group(1), "path": path, "line": i, "status": "", "title": "",
                           "title_line": i, "body": "", "comments": [], "created": None}
                    tickets.append(cur)
                    continue
                if cur is None:
                    continue
                for field, key in (("summary", "title"), ("status", "status"), ("description", "body")):
                    m = re.match(rf'"{field}":\s*"(.*)",?$', s)
                    if m and not cur.get(f"_{field}"):
                        cur[key] = m.group(1)
                        cur[f"_{field}"] = True
                        if field == "summary":
                            cur["title_line"] = i
                        if field == "description":
                            cur["body_line"] = i
                m = re.match(r'"created":\s*"([^"]+)"', s)
                if m and cur["created"] is None:
                    cur["created"] = datetime.fromisoformat(m.group(1))
                m = re.match(r'"body":\s*"(.*)",?$', s)
                if m:
                    cur["comments"].append((i, m.group(1)))
        elif path.endswith(".md"):
            cur = None
            for i, ln in enumerate(doc.lines, 1):
                m = re.match(r"^### ([A-Z]{2,4}-\d+) · (.+)$", ln)
                if m:
                    cur = {"system": "helpdesk", "id": m.group(1), "path": path, "line": i, "title": m.group(2),
                           "title_line": i, "status": "", "body": "", "comments": [], "created": None}
                    tickets.append(cur)
                    continue
                if cur is None:
                    continue
                if ln.startswith("### ") or ln.startswith("# "):
                    cur = None
                    continue
                m = re.search(r"Opened:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*·\s*Status:\s*(.+)$", ln)
                if m:
                    cur["created"] = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=inv.rec.zone)
                    cur["status"] = m.group(2).strip()
                    continue
                if ln.strip():
                    cur["body"] += " " + ln.strip()
                    cur["comments"].append((i, ln.strip()))
    return tickets


def _as_of(inv: Investigation) -> datetime | None:
    ts = [e.t for e in inv.rec.events if e.t]
    return max(ts) if ts else None


def _topic(t: dict) -> str:
    return re.sub(SL.RECURRENCE_SUFFIX, "", t["title"].strip(), flags=re.I).strip().lower()


def scan(inv: Investigation, store: FindingStore | None = None, incident: dict | None = None) -> list[Finding]:
    """incident = {"sources": citations on the incident's attack path, "text": their quotes}"""
    store = store or inv.store
    groups: dict[tuple, _Group] = {}
    ev_by_source = {e.source: e for e in inv.rec.events}
    tickets = _ticket_index(inv)
    topics: dict[str, list] = defaultdict(list)
    ticket_at, topic_of = {}, {}
    for t in tickets:
        topics[_topic(t)].append(t)
        topic_of[t["id"]] = _topic(t)
        for ln in [t["line"], t["title_line"], t.get("body_line", 0)] + [c[0] for c in t["comments"]]:
            ticket_at[f"{t['path']}:{ln}"] = t

    def group(det: str, key: str, subject: str | None, where: str) -> _Group:
        return groups.setdefault((det, key), _Group(det, subject, where))

    compiled = {d: [re.compile(p, re.I) for p in spec["patterns"]] for d, spec in SL.DETECTORS.items()}
    chat_counts: dict[tuple, list] = defaultdict(list)
    free: dict[str, list] = defaultdict(list)

    # 1 · line-level detectors: attach each hit to the ticket topic or identifier it concerns
    for path, doc in inv.corpus.docs.items():
        is_chat = path.startswith("slack_export/")
        for cite, text in doc.unit_lines():
            for det, rxs in compiled.items():
                if is_chat and det not in SL.CHAT_DETECTORS:
                    continue
                m = next((r.search(text) for r in rxs if r.search(text)), None)
                if not m:
                    continue
                ev = ev_by_source.get(cite)
                t = ev.t if ev else None
                if is_chat:
                    chat_counts[(det, _norm_chat(ev.text if ev else text))].append((cite, m.group(0), t, ev.text if ev else text))
                    continue
                tk = ticket_at.get(cite)
                if tk:
                    topic = topic_of[tk["id"]]
                    g = group(det, "topic:" + topic, topics[topic][0]["title"], tk["path"])
                    g.extra["topic"] = topic
                    g.add(cite, m.group(0), t or tk["created"], text)
                    continue
                ids = BACKTICK.findall(text) + TICKET_KEY.findall(text)
                if ids:
                    sid = ids[0]
                    # a mention joins the ticket's topic only while that work is still open — a closed
                    # ticket does not close a different weakness that merely mentions it
                    tk_open = sid in topic_of and any(
                        x["status"].lower() not in SL.TICKET_DONE for x in topics[topic_of[sid]])
                    if tk_open:
                        g = group(det, "topic:" + topic_of[sid], sid, path)
                        g.extra["topic"] = topic_of[sid]
                    else:
                        g = group(det, "id:" + sid, sid, path)
                    g.add(cite, m.group(0), t, text)
                else:
                    free[det].append((cite, m.group(0), t, text))

    # recurring chat lines: one risk per recurring message, with how long it has been going on
    for (det, norm), hits in chat_counts.items():
        if len(hits) < SL.DETECTORS[det].get("repeat", 1):
            continue
        g = group(det, "chat:" + norm[:60], None, "chat")
        hits.sort(key=lambda h: h[2] or datetime.min.replace(tzinfo=inv.rec.zone))
        for h in hits[:2] + hits[-1:]:
            g.add(*h)
        g.extra.update(occurrences=len(hits), first=hits[0][2], last=hits[-1][2], chat_text=norm)

    # statements in notes, interviews and mails without an identifier: one corroborating risk per category
    for det, hits in free.items():
        g = group(det, "statements", None, "statements")
        for h in hits[:6]:
            g.add(*h)
        g.extra["statements"] = len(hits)

    # 2 · grant tables with an empty revoke/expiry column: one risk per table
    for path, doc in inv.corpus.docs.items():
        if doc.kind != "text" or not path.endswith(".md"):
            continue
        cols, header_line = None, 0
        for i, ln in enumerate(doc.lines, 1):
            if not ln.startswith("|"):
                cols = None
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            nxt = doc.lines[i] if i < len(doc.lines) else ""
            if nxt.startswith("|") and set(nxt.replace("|", "").strip()) <= {"-", " ", ":"}:
                cols, header_line = [c.lower() for c in cells], i
                continue
            if cols is None or set(ln.replace("|", "").strip()) <= {"-", " ", ":"}:
                continue
            gcol = next((j for j, c in enumerate(cols) if any(k in c for k in SL.GRANT_COLUMNS)), None)
            if gcol is None or gcol >= len(cells) or cells[gcol].lower() not in SL.EMPTY_CELL:
                continue
            g = group("grant-table", f"{path}:{header_line}", None, path)
            g.add(f"{path}:{i}", cells[0], None, ln)
            g.extra.setdefault("grants", []).append(dict(zip(cols, cells)))

    # 3 · security work items by content, grouped across re-filings; merged into a detector's topic group
    term_rx = [re.compile(p, re.I) for p in SL.SECURITY_TICKET_TERMS]
    routine = [re.compile(p, re.I) for p in SL.ROUTINE_TICKETS]
    for topic, ts in topics.items():
        ts.sort(key=lambda t: t["created"] or datetime.min.replace(tzinfo=inv.rec.zone))
        info = [{"id": t["id"], "status": t["status"], "created": t["created"].isoformat() if t["created"] else None}
                for t in ts]
        attached = [g for (d, k), g in groups.items() if k == "topic:" + topic]
        for g in attached:
            g.extra["tickets"] = info
            g.extra["title"] = ts[0]["title"]
        if attached:
            continue
        text = " ".join(f"{t['title']} {t['body']}" for t in ts)
        if not any(r.search(text) for r in term_rx) or any(r.search(ts[0]["title"]) for r in routine):
            continue
        g = group("security-ticket", "topic:" + topic, ts[0]["id"] if len(ts) == 1 else None, ts[0]["path"])
        for t in ts[:4]:
            g.add(f"{t['path']}:{t['title_line']}", t["title"][:25], t["created"], t["title"])
        for ln, body in ts[-1]["comments"][-1:]:
            g.add(f"{ts[-1]['path']}:{ln}", None, None, body)
        g.extra.update(tickets=info, title=ts[0]["title"])

    # 4 · what the sweep established (record integrity, audible rooms) corroborates those categories
    for i in inv.store.issues:
        det = {"clock": "record-integrity", "leak_channel": "information-leak"}.get(i.category)
        if i.kind != "sweep" or not det or i.resolution not in ("fixed", "explained") or not i.evidence:
            continue
        if "calendar" in i.title.lower() or "card feed" in i.title.lower():
            continue
        g = group(det, "sweep:" + i.key, None, "sweep")
        for e in i.evidence[:3]:
            g.add(e.source, None, None, e.quote)
        g.extra["from_sweep"] = i.title

    # a group whose lines are all inside another group adds nothing
    items = list(groups.items())
    for k, g in items:
        mine = {h[0] for h in g.hits}
        for k2, g2 in items:
            if k2 != k and k2 in groups and k in groups and mine and mine < {h[0] for h in g2.hits}:
                del groups[k]
                break

    # --------------------------------------------------------------- build
    as_of = _as_of(inv)
    out = []
    for key, g in groups.items():
        f = _finding(inv, g, as_of, incident or {"sources": set(), "text": ""})
        if f and f.evidence:
            out.append(store.add(f))
    _dedupe_same_lines(store)
    inv.stage("scan", f"{len(out)} risk proposals from {len(groups)} signal groups (as of {fmt_dt(as_of)})")
    return out


def _dedupe_same_lines(store: FindingStore) -> None:
    """Two detectors firing on the same line produce one risk: keep the more severe."""
    seen: dict[str, Finding] = {}
    for f in [x for x in store.findings if x.meta.get("kind") == "risk"]:
        k = "|".join(sorted(e.source for e in f.evidence))
        prev = seen.get(k)
        if prev is None:
            seen[k] = f
            continue
        a, b = SL.SEVERITY[prev.meta["severity"]], SL.SEVERITY[f.meta["severity"]]
        loser = f if a >= b else prev
        loser.status = "withdrawn"
        loser.history.append("duplicate of a more severe risk on the same lines")
        if loser is prev:
            seen[k] = f


def _state_of(inv: Investigation, g: _Group, as_of) -> tuple[str, str]:
    if g.extra.get("tickets"):
        sts = [t["status"].lower() for t in g.extra["tickets"]]
        if all(s in SL.TICKET_DONE for s in sts):
            return "addressed", "every ticket on this topic is closed as done — verify the fix"
        open_ = [s for s in sts if s not in SL.TICKET_DONE and s not in SL.TICKET_DROPPED]
        if open_:
            return "open", f"{len(open_)} of {len(sts)} ticket(s) still {', '.join(sorted(set(open_)))}"
        return "open", f"tickets closed as {', '.join(sorted({s for s in sts if s in SL.TICKET_DROPPED}))} without a fix"
    if g.detector == "grant-table":
        return "open", f"{len(g.extra['grants'])} grant(s) with an empty revoke/expiry column"
    if g.extra.get("occurrences"):
        return "open", f"reported {g.extra['occurrences']} times, last {fmt_dt(g.extra['last'])}"
    if g.subject:
        latest = max((h[2] for h in g.hits if h[2]), default=None)
        for h in inv.corpus.search(re.escape(g.subject), limit=200):
            if any(h["source"] == x[0] for x in g.hits):
                continue
            pos = h["text"].find(g.subject)
            # the fix word must be about this subject: within a few words of it
            m = next((mm for mm in RESOLVED.finditer(h["text"]) if abs(mm.start() - pos) <= 40), None)
            if not m:
                continue
            if re.search(r"\b(?:never|not|no|without|isn'?t|wasn'?t|hasn'?t|until)\b[^.]{0,25}$", h["text"][:m.start()], re.I):
                continue
            return "check", f"a later line about {g.subject} may report a fix ({h['source']}) — verify"
        return "open", f"no record of a fix for {g.subject}" + (f" as of {fmt_dt(as_of)}" if as_of else "")
    return "open", "no record of a fix in the data" + (f" as of {fmt_dt(as_of)}" if as_of else "")


def _finding(inv: Investigation, g: _Group, as_of, incident: dict) -> Finding | None:
    spec = SL.DETECTORS.get(g.detector)
    if g.detector == "grant-table":
        ids = [str(next(iter(x.values()))).strip("`") for x in g.extra["grants"]]
        title = f"{len(ids)} standing grant(s) with no end date: {', '.join(ids[:5])}"
        severity, why, category = "critical", "A grant with no revocation or expiry date stays usable indefinitely.", "stale-access"
    elif g.detector == "security-ticket":
        tickets = g.extra["tickets"]
        title = f"Security work not done: {g.extra['title'][:70]}"
        hot = re.search(r"revok|credential|permission|access|password|audit|secret|token", g.extra["title"], re.I)
        severity = "high" if hot else "medium"
        why = "Security work that is raised and not finished leaves the weakness in place."
        category = "security-ticket"
    else:
        label = g.extra.get("title") or g.subject
        if g.extra.get("chat_text"):
            label = (f"recurring report \"{g.extra['chat_text'][:60]}\"" if g.extra.get("occurrences", 1) > 1
                     else f"reported in chat \"{g.extra['chat_text'][:60]}\"")
        elif g.extra.get("statements"):
            label = "said in notes, interviews and mail"
        elif g.extra.get("from_sweep"):
            label = "established by the inconsistency sweep"
        title = spec["title"] + (f": {label}" if label else "")
        severity, why, category = spec["severity"], spec["why"], g.detector
    state, state_note = _state_of(inv, g, as_of)
    if state == "addressed":
        severity = "low"
    ev = []
    for src, needle, t, text in g.hits[:5]:
        e = inv.evidence(src, needle, note=fmt_dt(t) if t else "")
        if e.usable or e.status == "ocr":
            ev.append(e)
    if not ev:
        return None
    linked = any(e.source in incident["sources"] for e in ev) or bool(g.subject and g.subject in incident["text"])
    if linked and severity != "critical" and state == "open":
        severity = {"low": "medium", "medium": "high", "high": "critical"}[severity]
    times = [h[2] for h in g.hits if h[2]]
    claim_bits = [state_note]
    if g.extra.get("tickets"):
        claim_bits.insert(0, "; ".join(f"{t['id']} {t['status']}" for t in g.extra["tickets"][:6])
                          + (f" (+{len(g.extra['tickets']) - 6})" if len(g.extra["tickets"]) > 6 else ""))
        if len(g.extra["tickets"]) >= 3:
            claim_bits.append(f"filed {len(g.extra['tickets'])} times — the issue keeps coming back")
    if g.extra.get("from_sweep"):
        claim_bits.insert(0, f"established by the inconsistency sweep: {g.extra['from_sweep']}")
    if g.extra.get("grants"):
        claim_bits.insert(0, "; ".join(" · ".join(f"{k}: {v}" for k, v in x.items() if v)[:140] for x in g.extra["grants"][:3]))
    return Finding(
        suspect=None, analyzer=f"guard:{g.detector}", constraint=category, cls="NEUTRAL",
        title=title, claim="; ".join(claim_bits), evidence=ev, reasoning=why,
        weight=SL.SEVERITY[severity] / 4, reliability="document", stage="analyse",
        meta={"kind": "risk", "severity": severity, "state": state, "subject": g.subject, "category": category,
              "first_seen": min(times).isoformat() if times else None,
              "last_seen": max(times).isoformat() if times else None,
              "occurrences": g.extra.get("occurrences") or len(g.extra.get("tickets", [])) or len(g.hits),
              "incident": linked, "tickets": g.extra.get("tickets")},
    )


# --------------------------------------------------------------- root causes
def root_causes(inv: Investigation, store: FindingStore | None = None) -> list[Issue]:
    store = store or inv.store
    risks = [f for f in store.findings if f.meta.get("kind") == "risk" and f.status != "withdrawn"
             and f.meta.get("state") != "addressed"]
    signal_rx = {k: [re.compile(p, re.I) for p in v] for k, v in SL.PROCESS_SIGNALS.items()}
    out = []
    for rc_id, rc in SL.ROOT_CAUSES.items():
        def feeds(f):
            if f.meta["category"] in rc["from"] or (f.analyzer == "guard:grant-table" and "grant-table" in rc["from"]):
                return True
            # any risk with unfinished tickets behind it is "security work" for escalation/recurrence purposes
            return "security-ticket" in rc["from"] and bool(f.meta.get("tickets"))
        contrib = [f for f in risks if feeds(f)]
        if rc.get("needs_recurrence"):
            contrib = [f for f in contrib if len(f.meta.get("tickets") or []) >= rc["needs_recurrence"]]
        if not contrib:
            continue
        # evidence of the process failure: signal phrases in the same documents/tickets as the risks
        docs = {e.source.rsplit(":", 1)[0] for f in contrib for e in f.evidence}
        subjects = {f.meta.get("subject") for f in contrib if f.meta.get("subject")}
        sig_ev: list[Evidence] = []
        for sig in rc["signals"]:
            for path in sorted(docs):
                doc = inv.corpus.get(path)
                if doc is None or doc.kind != "text" or path.startswith("slack_export/"):
                    continue
                for i, ln in enumerate(doc.lines, 1):
                    m = next((r.search(ln) for r in signal_rx[sig] if r.search(ln)), None)
                    if not m:
                        continue
                    near_subject = not subjects or any(s and s in "\n".join(doc.lines[max(0, i - 25):i + 5]) for s in subjects)
                    if near_subject:
                        e = inv.evidence(f"{path}:{i}", m.group(0), note=f"process signal: {sig}")
                        if e.usable and all(x.source != e.source for x in sig_ev):
                            sig_ev.append(e)
                    if len(sig_ev) >= 4:
                        break
        sev = max((f.meta["severity"] for f in contrib), key=lambda s: SL.SEVERITY[s])
        risk_ev = [f.evidence[0] for f in sorted(contrib, key=lambda f: -SL.SEVERITY[f.meta["severity"]])[:4]]
        issue = Issue(
            kind="rootcause", category=rc_id, title=rc["title"], severity=sev,
            observation=f"{rc['explain']} Seen in {len(contrib)} risk(s): " +
                        "; ".join(f.title for f in contrib[:5]) + (" …" if len(contrib) > 5 else ""),
            evidence=sig_ev[:4] + risk_ev, resolution="open",
            affects=[f.key for f in contrib],
            fix=SL.REMEDIATIONS.get(rc_id, {}).get("process", ""),
        )
        out.append(store.issue(issue))
    inv.stage("rootcause", f"{len(out)} process misdesigns behind the open risks")
    return out


# -------------------------------------------------------------- remediations
def remediations(inv: Investigation, store: FindingStore | None = None, make_tasks: bool = True) -> list[Issue]:
    store = store or inv.store
    out = []
    for rc in [i for i in store.issues if i.kind == "rootcause"]:
        r = SL.REMEDIATIONS.get(rc.category)
        if not r:
            continue
        affected = [f for f in store.findings if f.key in rc.affects]
        listing = "; ".join(f"{f.title}" for f in affected[:6])
        issue = Issue(
            kind="remediation", category=rc.category, title=f"Remediate: {rc.title}", severity=rc.severity,
            observation=f"NOW: {r['now']}  CONTROL: {r['control']}  PROCESS: {r['process']}  "
                        f"OWNER: {r['owner']}.  Applies to: {listing}",
            evidence=[e for f in affected[:3] for e in f.evidence[:1]],
            resolution="proposed", fix=r["now"], effect=f"Verify: {r['verify']}",
            affects=[rc.key] + [f.key for f in affected],
        )
        issue = store.issue(issue)
        out.append(issue)
        if make_tasks and SL.SEVERITY[rc.severity] >= SL.SEVERITY["high"]:
            inv.task(Task(
                kind="human", topic="remediation", subject=issue.key, priority=1 if rc.severity == "critical" else 2,
                title=f"Approve remediation: {rc.title}",
                why="Remediations change systems, budgets and people's access; an accountable person approves them.",
                question=f"Approve this plan (owner: {r['owner']})? NOW: {r['now']}",
                read=[{"source": e.source, "quote": e.quote, "note": e.note} for e in issue.evidence[:5]],
                options=["approve", "reject", "accept-risk"],
                effect={"approve": "plan goes to the owner", "reject": "the agent revises the plan",
                        "accept-risk": "risk accepted in writing, review date set"},
            ))
    inv.stage("remediate", f"{len(out)} remediation plans")
    return out


def summarize(store: FindingStore, reviews: dict | None = None) -> dict:
    """A compact view for the investigator: what is still weak, why, and what to do."""
    reviews = reviews or {}
    risks = []
    for f in store.findings:
        if f.meta.get("kind") != "risk" or f.status == "withdrawn":
            continue
        r = reviews.get(f.key)
        if r and r["decision"] == "reject":
            continue
        m = dict(f.meta)
        if r and r["decision"] == "amend":
            m.update({k: r[k] for k in ("severity", "state") if r.get(k)})
        risks.append({"id": f.id, "key": f.key, "title": f.title, "claim": f.claim, "reasoning": f.reasoning,
                      "severity": m["severity"], "state": m["state"], "category": m["category"],
                      "incident": m.get("incident"), "review": r,
                      "evidence": [{"source": e.source, "quote": e.quote, "note": e.note, "status": e.status}
                                   for e in f.evidence[:4]]})
    risks.sort(key=lambda x: (-SL.SEVERITY[x["severity"]], not x["incident"], x["id"]))
    rcs = [{"id": i.id, "key": i.key, "title": i.title, "severity": i.severity, "observation": i.observation,
            "fix": i.fix, "risks": [f.id for f in store.findings if f.key in i.affects],
            "evidence": [{"source": e.source, "quote": e.quote, "note": e.note, "status": e.status} for e in i.evidence[:4]]}
           for i in store.issues if i.kind == "rootcause"]
    rems = [{"id": i.id, "key": i.key, "title": i.title, "severity": i.severity, "category": i.category,
             "plan": SL.REMEDIATIONS.get(i.category, {}), "risks": [f.id for f in store.findings if f.key in i.affects]}
            for i in store.issues if i.kind == "remediation"]
    open_ = [r for r in risks if r["state"] in ("open", "check")]
    return {"open": len(open_), "total": len(risks),
            "incident_open": [r["id"] for r in open_ if r["incident"]],
            "by_severity": {s: sum(1 for r in open_ if r["severity"] == s) for s in ("critical", "high", "medium", "low")},
            "risks": risks, "rootcauses": rcs, "remediations": rems}


def incident_from_state(st: dict) -> dict:
    """The incident's attack path: the culprit's findings, knowledge leaks and the case frame."""
    src, text = set(), []
    culprit = ((st.get("argue") or {}).get("culprit")) or ((st.get("baseline") or {}).get("culprit"))
    for f in st.get("findings", []):
        if f.get("status") != "withdrawn" and f.get("suspect") and (f.get("suspect") == culprit or f.get("constraint") == "echo"):
            for e in f.get("evidence", []):
                src.add(e["source"])
                text.append(e.get("quote", ""))
    for f in (st.get("case", {}).get("facts") or {}).values():
        src.add(f.get("source", ""))
        text.append(str(f.get("quote", "")))
    return {"sources": src, "text": "\n".join(text)}


def incident_from_investigation(inv: Investigation, culprit: str | None = None) -> dict:
    src, text = set(), []
    for f in inv.store.findings:
        if f.suspect and f.status != "withdrawn" and (f.suspect == culprit or f.constraint == "echo"):
            for e in f.evidence:
                src.add(e.source)
                text.append(e.quote)
    for f in inv.case.facts.values():
        src.add(f.source)
        text.append(str(f.quote))
    return {"sources": src, "text": "\n".join(text)}
