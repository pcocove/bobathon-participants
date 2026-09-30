"""`investigate dig <target>` — a focused context pack for going deeper.

Given a finding, an inconsistency/challenge, a suspect or a citation, it prints:
  - the item and its reasoning
  - every cited line with the lines around it
  - what the same person did in the hours around each cited moment (all sources, corrected clocks)
  - where the distinctive tokens of the evidence (ids, plates, rooms, tickets) appear elsewhere
  - open questions worth pursuing
The pack is plain text so an agent can read it in one go.
"""

from __future__ import annotations

import re
from datetime import timedelta

from .engine import Investigation
from .util import fmt_dt

TOKEN_RX = re.compile(r"\b(?:[A-Z]{2,5}-\d{2,5}|TX\d{4,}|\d[A-Z]-\d{1,3}|[A-Z]{2} \d{1,3} \d{3}|[a-z]+\.[a-z]+(?:-[a-z]+)?)\b")


def _context_lines(inv: Investigation, source: str, n: int = 3) -> list[str]:
    doc, a, b = inv.corpus.resolve(source)
    if doc is None:
        return [f"   (unknown source {source})"]
    if doc.kind == "text" and a:
        lo, hi = max(1, a - n), min(len(doc.lines), (b or a) + n)
        return [f"   {'>' if a <= i <= (b or a) else ' '}{i:6d}  {doc.lines[i - 1][:220]}" for i in range(lo, hi + 1)]
    if doc.kind == "pdf":
        return ["   " + ln for ln in doc.pages.get(a or 1, "").splitlines()[:30]]
    if doc.kind == "xlsx" and a:
        return [f"   {'>' if r == a else ' '}{r:4d}  " + " · ".join(c) for r, c in doc.rows.items() if abs(r - a) <= 1]
    if doc.kind == "image":
        return ["   (OCR) " + ln for ln in doc.ocr_text.splitlines() if ln.strip()][:20]
    return []


def _events_near(inv: Investigation, source: str, person_keys: set, hours: int = 3) -> list[str]:
    ev = next((e for e in inv.rec.events if e.source == source), None)
    if ev is None or ev.t is None or not person_keys:
        return []
    lo, hi = ev.t - timedelta(hours=hours), ev.t + timedelta(hours=hours)
    out = []
    for e in inv.rec.between(lo, hi):
        if e.source == source:
            continue
        if e.actor in person_keys or inv.resolved_plate(e) in person_keys:
            fix = f" [{e.attrs['clock_fix']}]" if e.attrs.get("clock_fix") else ""
            out.append(f"   {fmt_dt(e.t)}  {e.kind:12s} {e.text[:100]}  ({e.source}){fix}")
    return out[:25]


def _linked(inv: Investigation, text: str, exclude: set) -> list[str]:
    toks = sorted({t for t in TOKEN_RX.findall(text) if not t.endswith((".md", ".txt", ".json", ".csv"))})[:6]
    out = []
    for t in toks:
        hits = [h for h in inv.corpus.search(re.escape(t), limit=40) if h["source"] not in exclude]
        if hits:
            out.append(f"   '{t}' also appears in {len(hits)} place(s):")
            out += [f"      {h['source']}  {h['text'].strip()[:140]}" for h in hits[:5]]
    return out


def pack(inv: Investigation, target: str) -> str:
    L: list[str] = []
    item = inv.store.by_id(target)
    person = inv.case.suspect_by_name(target) or inv.person(target)
    if item is not None and hasattr(item, "claim"):
        f = item
        p = inv.person(f.suspect) if f.suspect else None
        L += [f"# {f.id} {f.icon} {f.title}", f"suspect: {p.name if p else '—'} · constraint: {f.constraint} · "
              f"status: {f.status} · weight {f.weight} · reliability {f.reliability} · by {f.analyzer}",
              f"claim: {f.claim}"]
        if f.reasoning:
            L.append(f"reasoning: {f.reasoning}")
        for c in f.caveats:
            L.append(f"caveat: {c}")
        for h in f.history:
            L.append(f"history: {h}")
        keys = ({p.handle, *p.plates} - {None}) if p else set()
        for e in f.evidence:
            L += ["", f"## {e.source}  [{e.status}]  {e.note}", f'   quote: "{e.quote}"'] + _context_lines(inv, e.source)
            near = _events_near(inv, e.source, keys)
            if near:
                L += [f"   same person within ±3 h:"] + near
        L += ["", "## Where the evidence's identifiers appear elsewhere"] + (
            _linked(inv, " ".join(e.quote for e in f.evidence), {e.source for e in f.evidence}) or ["   (nothing)"])
        L += ["", "## Questions worth pursuing"] + [f"- {q}" for q in _questions(inv, f)]
    elif item is not None:
        i = item
        L += [f"# {i.id} {i.title}", f"{i.kind} · {i.category} · severity {i.severity} · resolution {i.resolution}",
              i.observation]
        if i.fix:
            L.append(f"proposed fix/explanation: {i.fix}")
        if i.effect:
            L.append(f"effect: {i.effect}")
        for e in i.evidence:
            L += ["", f"## {e.source}  [{e.status}]  {e.note}", f'   quote: "{e.quote}"'] + _context_lines(inv, e.source)
        L += ["", "## Questions worth pursuing",
              "- Is there a second, independent record of the same moment that agrees or disagrees?",
              "- Does the fix change where any suspect was during the operation window?",
              "- Do the sources themselves document this problem somewhere else (tickets, interviews, notes)?"]
    elif person is not None:
        p = person
        op0, op1 = inv.op
        L += [f"# {p.name}", f"handle {p.handle} · plates {', '.join(p.plates) or '—'} · cards {', '.join(sorted(p.card_last4)) or '—'} · "
              f"interviews {', '.join(i.path for i in p.interviews)}"]
        L += ["", "## Findings"]
        prev = inv.store.include_proposed
        inv.store.include_proposed = True
        for f in sorted(inv.store.for_suspect(p.key), key=lambda f: -abs(f.score)):
            L.append(f"   {f.id} {f.icon} [{f.constraint}] {f.title} ({f.status}) — {f.claim[:140]}")
        inv.store.include_proposed = prev
        L += ["", f"## Records ±14 h around the operation window ({fmt_dt(op0)} → {fmt_dt(op1)})"]
        for e in inv.events_for(p, ("card", "garage", "slack", "calendar", "email", "jira", "jira_comment", "ticket"),
                                op0 - timedelta(hours=14), op1 + timedelta(hours=14)):
            fix = f" [{e.attrs['clock_fix']}]" if e.attrs.get("clock_fix") else ""
            L.append(f"   {'█' if op0 <= e.t <= op1 else ' '} {fmt_dt(e.t)}  {e.kind:12s} {e.text[:100]}  ({e.source}){fix}")
        L += ["", "## Mentions across the bundle"]
        names = [a for a in p.aliases if len(a) > 3]
        rx = "|".join(re.escape(a) for a in names)
        hits = inv.corpus.search(rf"\b(?:{rx})\b", limit=400) if rx else []
        by = {}
        for h in hits:
            by.setdefault(h["source"].split(":")[0].split("/")[0], []).append(h)
        for src, hs in sorted(by.items(), key=lambda x: -len(x[1])):
            L.append(f"   {src}: {len(hs)} line(s), e.g. {hs[0]['source']}")
    else:
        # a citation
        L += [f"# {target}"] + _context_lines(inv, target, 8)
        ev = next((e for e in inv.rec.events if e.source == target), None)
        if ev:
            L += ["", f"record: {ev.kind} · {fmt_dt(ev.t)} (raw {ev.t_raw}, basis {ev.basis}) · actor {ev.actor}"]
            p = inv.person(ev.actor) or next((q for q in inv.case.people.values() if ev.attrs.get("plate") in q.plates), None)
            if p:
                L += [f"person: {p.name}", "same person within ±3 h:"] + _events_near(inv, target, {p.handle, *p.plates} - {None})
    return "\n".join(L) + "\n"


def _questions(inv: Investigation, f) -> list[str]:
    q = []
    if f.constraint == "presence":
        q += ["Is there an independent record (card, chat, witness) of the same person within an hour of this one?",
              "Could the person have been on site without this record showing it (another car, another entrance)?"]
    if f.constraint == "echo":
        q += ["What exactly did the person say, and when? List every public record about THIS event before that moment.",
              "Who could have heard the investigator discuss the findings before the interview?",
              "Did the person describe their own earlier experience rather than this event?"]
    if f.constraint == "statement":
        q += ["What else did the person say about the same time, in the interview and in chat?",
              "Which record would have to be wrong for the person's account to be true?"]
    if f.constraint == "knowledge":
        q += ["Did the person actually receive/open the document, or just appear on a distribution list?"]
    if f.constraint == "lead":
        q += ["Which record confirms or explains each point of this suspicion? Look in a different file and format."]
    if f.cls in ("EXONERATES", "PROVES_INNOCENCE"):
        q += ["Could this alibi record have been created by someone else (shared card, lent car)?"]
    return q or ["Which other source could confirm or contradict this?"]
