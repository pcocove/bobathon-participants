"""Stage 4 — analysis on the swept (fixed) view of the evidence.

Constraints, each producing classified findings per suspect:
  presence   barrier log, card feed, contemporaneous chat — relative to the operation window
  statement  what the person said vs what the paperwork shows
  echo       knowledge of withheld facts, checked against every innocent route (public record,
             own experience, leaks) that existed BEFORE the person spoke
  knowledge  documented routes to the secret the operator needed
  link       contact with the party that received the stolen asset
  lead       why the investigator listed the person, and what the file says about it
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import garage as G
from . import lexicon as L
from .engine import Investigation
from .findings import Finding
from .tasks import Task
from .util import fmt_dt


def run(inv: Investigation) -> None:
    for p in inv.case.suspects:
        garage_presence(inv, p)
        card_presence(inv, p)
        chat_presence(inv, p)
        interview_statements(inv, p)
        knowledge_echoes(inv, p)
    secret_routes(inv)
    receiver_links(inv)
    leads(inv)
    n = len(inv.store.findings)
    inv.stage("analyse", f"{n} findings across {len(inv.case.suspects)} suspects")


# ------------------------------------------------------------------ presence
def garage_presence(inv: Investigation, p) -> None:
    op0, op1 = inv.op
    if not p.plates:
        inv.add(Finding(
            suspect=p.key, analyzer="garage", constraint="presence", cls="NEUTRAL",
            title="No parking permit on file",
            claim=f"{p.name} holds no permit; the barrier log cannot place them either way.",
            weight=0.0, reliability="absence",
        ))
        return
    for plate in p.plates:
        permit = next(pm for pm in p.permits if pm.plate == plate)
        state, last = G.state_at(inv, plate, op0)
        nxt = G.next_event(inv, plate, op0)
        during = [e for e in G.plate_events(inv, plate) if op0 < e.t <= op1]
        ev = [inv.evidence(permit.source, plate, note=f"{p.name}'s permit")]
        if last:
            ev.append(inv.ev_event(last, None, note=f"last record before the window ({fmt_dt(last.t)}"
                                                    + (f", corrected {last.attrs['clock_fix']}" if last.attrs.get("clock_fix") else "") + ")"))
        if nxt:
            deg = inv.plate_resolutions.get(nxt.source)
            ev.append(inv.ev_event(nxt, None, note=f"next record ({fmt_dt(nxt.t)})"
                                                   + (" — degraded read, resolved by elimination" if deg else "")))
        caveats = []
        if any(e.attrs.get("clock_fix") for e in ([last] if last else []) + ([nxt] if nxt else [])):
            caveats.append("relies on the barrier-clock correction (see sweep)")
        if nxt and inv.plate_resolutions.get(nxt.source):
            caveats.append("the exit is a degraded plate read resolved by elimination")
        if state == "inside" and not during:
            inv.add(Finding(
                suspect=p.key, analyzer="garage", constraint="presence", cls="INCRIMINATES",
                title="Car inside for the entire operation window",
                claim=f"{plate} entered {fmt_dt(last.t)} and its next movement is "
                      f"{nxt.attrs.get('direction') + ' ' + fmt_dt(nxt.t) if nxt else 'not recorded'} — "
                      f"inside from before {fmt_dt(op0, False)} until after {fmt_dt(op1, False)}.",
                evidence=ev, weight=0.6, reliability="machine", caveats=caveats,
                reasoning="The car was on site throughout. A car on site is not proof the person was, "
                          "but the operator needed to bring and take away a portable drive.",
                depends_on=[k for k in inv.clock_fixes],
            ))
        elif state == "inside" and during:
            e0 = during[0]
            inv.add(Finding(
                suspect=p.key, analyzer="garage", constraint="presence", cls="WEAKLY_INCRIMINATES",
                title="Car on site when the operation began",
                claim=f"{plate} was inside at {fmt_dt(op0, False)} and moved at {fmt_dt(e0.t)} ({e0.attrs.get('direction')}).",
                evidence=ev + [inv.ev_event(e0)], weight=0.35, reliability="machine", caveats=caveats,
            ))
        elif during and any(G.is_entry(e) for e in during):
            e0 = next(e for e in during if G.is_entry(e))
            inv.add(Finding(
                suspect=p.key, analyzer="garage", constraint="presence", cls="INCRIMINATES",
                title="Car arrived during the operation window",
                claim=f"{plate} entered at {fmt_dt(e0.t)}, inside the window.",
                evidence=ev + [inv.ev_event(e0)], weight=0.6, reliability="machine", caveats=caveats,
            ))
        elif state == "outside" and last and (op0 - last.t) < timedelta(hours=20):
            inv.add(Finding(
                suspect=p.key, analyzer="garage", constraint="presence", cls="EXONERATES",
                title="Car left before the operation and was not back until after it",
                claim=f"{plate} left at {fmt_dt(last.t)}; next record "
                      f"{nxt.attrs.get('direction') + ' ' + fmt_dt(nxt.t) if nxt else 'none in the log'}.",
                evidence=ev, weight=0.45, reliability="machine", caveats=caveats + [
                    "a car's absence does not prove the person's absence"],
                reasoning="The operation needed hours at a console and a portable drive carried in and out; "
                          "the car was gone for all of it.",
            ))
        else:
            inv.add(Finding(
                suspect=p.key, analyzer="garage", constraint="presence", cls="EXONERATES",
                title="Car not in the garage around the incident",
                claim=f"{plate}: last record {fmt_dt(last.t) if last else 'none'}, next "
                      f"{fmt_dt(nxt.t) if nxt else 'none'} — not on site that night.",
                evidence=ev, weight=0.25, reliability="absence",
                caveats=["absence of a record; the person could have come another way"],
            ))


def card_presence(inv: Investigation, p) -> None:
    op0, op1 = inv.op
    txns = [e for e in inv.events_for(p, ("card",), op0 - timedelta(hours=14), op1 + timedelta(hours=14))]
    if not txns:
        inv.add(Finding(
            suspect=p.key, analyzer="card", constraint="presence", cls="NEUTRAL",
            title="No card use around the incident",
            claim=f"No corporate-card transaction for {p.name} between {fmt_dt(op0 - timedelta(hours=14))} "
                  f"and {fmt_dt(op1 + timedelta(hours=14))}.",
            weight=0.0, reliability="absence",
        ))
        return
    away_before = [e for e in txns if e.t <= op0 and not inv.is_site(e.attrs.get("city", ""))]
    away_during = [e for e in txns if op0 < e.t <= op1 and not inv.is_site(e.attrs.get("city", ""))]
    away_after = [e for e in txns if e.t > op1 and not inv.is_site(e.attrs.get("city", ""))]
    site_during = [e for e in txns if op0 < e.t <= op1 and inv.is_site(e.attrs.get("city", ""))]

    def gap(a, b):
        return int(abs((a - b).total_seconds()) // 60)

    def ev_of(e, note):
        return inv.ev_event(e, e.attrs.get("merchant"), note=note)
    if away_during:
        e = away_during[0]
        inv.add(Finding(
            suspect=p.key, analyzer="card", constraint="presence", cls="PROVES_INNOCENCE",
            title=f"Paid in {e.attrs.get('city')} during the operation",
            claim=f"Card used at {e.attrs.get('merchant')}, {e.attrs.get('city')} at {fmt_dt(e.t)} — "
                  f"inside the operation window, away from {inv.site}.",
            evidence=[ev_of(x, f"{fmt_dt(x.t)} local (feed is UTC)") for x in away_during[:2]] +
                     [ev_of(x, f"{fmt_dt(x.t)} local") for x in away_before[-1:]],
            weight=1.0, reliability="bank",
            reasoning="The operator was at a console in the building for the whole window; this person was "
                      "paying for something elsewhere in the middle of it.",
        ))
        return
    near_before = [e for e in away_before if gap(e.t, op0) <= 45]
    near_after = [e for e in away_after if gap(e.t, op1) <= 45]
    if near_before and near_after:
        a, b = near_before[-1], near_after[0]
        inv.add(Finding(
            suspect=p.key, analyzer="card", constraint="presence", cls="PROVES_INNOCENCE",
            title="Card use elsewhere brackets the operation window",
            claim=f"In {a.attrs.get('city')} {gap(a.t, op0)} min before the job started ({fmt_dt(a.t)}) and in "
                  f"{b.attrs.get('city')} {gap(b.t, op1)} min after it ended ({fmt_dt(b.t)}).",
            evidence=[ev_of(a, f"{fmt_dt(a.t)} local"), ev_of(b, f"{fmt_dt(b.t)} local")],
            weight=1.0, reliability="bank",
            reasoning="The job had to be started and ended at a console on site; the person was in another "
                      "town minutes before the start and minutes after the end.",
        ))
        return
    if near_before and gap(near_before[-1].t, op0) <= 15:
        a = near_before[-1]
        inv.add(Finding(
            suspect=p.key, analyzer="card", constraint="presence", cls="PROVES_INNOCENCE",
            title=f"In {a.attrs.get('city')} minutes before the job started",
            claim=f"Card used in {a.attrs.get('city')} at {fmt_dt(a.t)}, {gap(a.t, op0)} min before the job "
                  f"started on site.",
            evidence=[ev_of(a, f"{fmt_dt(a.t)} local")], weight=1.0, reliability="bank",
        ))
        return
    if near_before or near_after:
        a = (near_before or near_after)[-1]
        inv.add(Finding(
            suspect=p.key, analyzer="card", constraint="presence", cls="EXONERATES",
            title=f"In {a.attrs.get('city')} close to the operation window",
            claim=f"Card used in {a.attrs.get('city')} at {fmt_dt(a.t)} ({gap(a.t, op0 if a.t <= op0 else op1)} "
                  f"min from the window edge).",
            evidence=[ev_of(a, f"{fmt_dt(a.t)} local")], weight=0.7, reliability="bank",
            caveats=["travel time to the site is a judgement — see human task"],
        ))
        _travel_task(inv, p, a)
        return
    lodging = [e for e in away_before if L.MCC.get(e.attrs.get("mcc", "")) == "lodging" and e.t.date() == op0.date()]
    if lodging:
        a = lodging[-1]
        decision = inv.tasks.decision("human", "travel", f"{p.key}|{a.source}")
        cls = "PROVES_INNOCENCE" if decision and decision["decision"] == "impossible" else "EXONERATES"
        inv.add(Finding(
            suspect=p.key, analyzer="card", constraint="presence", cls=cls,
            title=f"Checked into lodging in {a.attrs.get('city')} the evening of the operation",
            claim=f"Hotel charge at {a.attrs.get('merchant')}, {a.attrs.get('city')} at {fmt_dt(a.t)} "
                  f"({gap(a.t, op0) // 60} h before the job started in {inv.site}).",
            evidence=[ev_of(a, f"{fmt_dt(a.t)} local; MCC {a.attrs.get('mcc')} = lodging")],
            weight=0.75, reliability="bank",
            caveats=[] if cls == "PROVES_INNOCENCE" else ["whether they could reach the site in time is a human judgement"],
            reasoning="An overnight lodging charge elsewhere on the evening of the operation.",
        ))
        _travel_task(inv, p, a)
        return
    if site_during:
        e = site_during[0]
        inv.add(Finding(
            suspect=p.key, analyzer="card", constraint="presence", cls="WEAKLY_INCRIMINATES",
            title=f"Card used in {inv.site} during the operation",
            claim=f"{e.attrs.get('merchant')} at {fmt_dt(e.t)}.",
            evidence=[ev_of(e, f"{fmt_dt(e.t)} local")], weight=0.3, reliability="bank",
        ))
        return
    before = [e for e in txns if e.t <= op0]
    after = [e for e in txns if e.t > op1]
    parts = []
    ev = []
    if before:
        parts.append(f"last before: {before[-1].attrs.get('merchant')}, {before[-1].attrs.get('city')} {fmt_dt(before[-1].t)}")
        ev.append(ev_of(before[-1], fmt_dt(before[-1].t)))
    if after:
        parts.append(f"first after: {after[0].attrs.get('merchant')}, {after[0].attrs.get('city')} {fmt_dt(after[0].t)}")
        ev.append(ev_of(after[0], fmt_dt(after[0].t)))
    inv.add(Finding(
        suspect=p.key, analyzer="card", constraint="presence", cls="NEUTRAL",
        title="Card use around the window does not decide presence",
        claim="; ".join(parts), evidence=ev, weight=0.0, reliability="bank",
    ))


def _travel_task(inv, p, e) -> None:
    op0, _ = inv.op
    inv.task(Task(
        kind="human", topic="travel", subject=f"{p.key}|{e.source}", suspect=p.key, priority=2,
        title=f"Could {p.name} get from {e.attrs.get('city')} to {inv.site} by {fmt_dt(op0, False)}?",
        why="Travel feasibility needs world knowledge (distances, last flights/trains) that is not in the bundle.",
        question=f"Card shows {p.name} in {e.attrs.get('city')} at {fmt_dt(e.t)}. Was it possible to be at a console "
                 f"in {inv.site} at {fmt_dt(op0)}?",
        read=[{"source": e.source, "quote": inv.ev_event(e, e.attrs.get('merchant')).quote, "note": fmt_dt(e.t)}],
        options=["impossible", "possible"],
        effect={"impossible": "upgrade to ⚪ proves innocence", "possible": "keep as 🟢 exonerates"},
    ))


def chat_presence(inv: Investigation, p) -> None:
    op0, op1 = inv.op
    msgs = inv.events_for(p, ("slack",), op0 - timedelta(hours=36), op1 + timedelta(hours=36))
    away_rx = L.compile_all(L.SELF_LOCATION_AWAY)
    on_rx = L.compile_all(L.SELF_LOCATION_ONSITE)
    for m in msgs:
        away = next((r.search(m.text) for r in away_rx if r.search(m.text)), None)
        on = next((r.search(m.text) for r in on_rx if r.search(m.text)), None)
        rel = "during" if op0 <= m.t <= op1 else ("before" if m.t < op0 else "after")
        if away:
            close = op0 - timedelta(hours=6) <= m.t <= op1 + timedelta(hours=12)
            inv.add(Finding(
                suspect=p.key, analyzer="chat", constraint="presence", cls="EXONERATES",
                title=f"Said in chat they were away ({fmt_dt(m.t)})",
                claim=f"Posted '{m.text}' in #{m.attrs.get('channel')} at {fmt_dt(m.t)} ({rel} the operation).",
                evidence=[inv.ev_event(m, away.group(0), note=f"{fmt_dt(m.t)}, user {m.attrs.get('user_id')}")],
                weight=0.35 if close else 0.2, reliability="chat",
                caveats=["self-reported, but written at the time, not after the fact"],
            ))
        elif on:
            cls = "INCRIMINATES" if rel == "during" else "EXONERATES"
            inv.add(Finding(
                suspect=p.key, analyzer="chat", constraint="presence", cls=cls,
                title=(f"Said they were on site during the operation" if rel == "during"
                       else f"On site {rel} the window, not during it ({fmt_dt(m.t)})"),
                claim=f"'{m.text}' at {fmt_dt(m.t)} — {rel} the operation window.",
                evidence=[inv.ev_event(m, on.group(0), note=f"{fmt_dt(m.t)}, user {m.attrs.get('user_id')}")],
                weight=0.5 if rel == "during" else 0.2, reliability="chat",
                reasoning=("" if rel == "during" else
                           "The record puts them in the building, but outside the window. It explains why they "
                           "were 'in the building that weekend' without placing them at the console."),
            ))
        elif op0 <= m.t <= op1:
            inv.add(Finding(
                suspect=p.key, analyzer="chat", constraint="presence", cls="NEUTRAL",
                title=f"Active in chat during the window ({fmt_dt(m.t, False)})",
                claim=f"'{m.text}' — location not stated.",
                evidence=[inv.ev_event(m, note=fmt_dt(m.t))], weight=0.0, reliability="chat",
            ))


# ----------------------------------------------------------------- statement
_WHEREABOUTS_Q = re.compile(r"where were you|friday|evening|night|weekend|the tenth|leave|left|arriv|home", re.I)


def interview_statements(inv: Investigation, p) -> None:
    presence = [f for f in inv.store.for_suspect(p.key) if f.constraint == "presence"]
    on_site = [f for f in presence if f.cls == "INCRIMINATES" and f.analyzer == "garage"]
    away = [f for f in presence if f.cls in ("PROVES_INNOCENCE", "EXONERATES") and f.analyzer in ("card", "chat")]
    places = set()
    for f in away:
        for e in f.evidence:
            places.update(w.lower()[:4] for w in re.findall(r"[A-ZÀ-Ý][a-zà-ÿ]{3,}", f.claim))
    tag = inv.case.interviewer_tag
    for iv in p.interviews:
        for k, ln in enumerate(iv.lines):
            if ln["speaker"] == tag or k == 0:
                continue
            q = iv.lines[k - 1]
            if q["speaker"] != tag or not _WHEREABOUTS_Q.search(q["text"]):
                continue
            text = ln["text"]
            departs = any(re.search(w, text, re.I) for w in L.DEPARTURE_WORDS)
            named = {w.lower()[:4] for w in re.findall(r"[A-ZÀ-Ý][a-zà-ÿ]{3,}", text)}
            src = f"{iv.path}:{ln['line']}"
            if on_site and departs:
                f0 = on_site[0]
                inv.add(Finding(
                    suspect=p.key, analyzer="interview-vs-records", constraint="statement", cls="INCRIMINATES",
                    title="Interview account contradicted by the barrier log",
                    claim=f"Says: '{_short(text)}' — but their car was inside for the whole operation window.",
                    evidence=[inv.evidence(src, _key_phrase(text)), *f0.evidence[1:3]],
                    weight=0.6, reliability="derived",
                    reasoning="The account puts them elsewhere; the machine record puts their car on site.",
                    caveats=["transcript not proofread"] + f0.caveats,
                ))
                break
            if away and named & places:
                inv.add(Finding(
                    suspect=p.key, analyzer="interview-vs-records", constraint="statement", cls="EXONERATES",
                    title="Interview account matches the records",
                    claim=f"Says: '{_short(text)}' — consistent with {away[0].title.lower()}.",
                    evidence=[inv.evidence(src, _key_phrase(text)), away[0].evidence[0]],
                    weight=0.3, reliability="derived",
                ))
                break


def _short(s: str, n: int = 170) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _key_phrase(text: str) -> str | None:
    for w in ("drove", "flew", "train", "went", "left", "stayed", "home", "was"):
        m = re.search(rf"\b{w}\b", text, re.I)
        if m:
            return m.group(0)
    return None


# ---------------------------------------------------------------------- echo
def _own_earlier_event(text: str, incident: datetime) -> bool:
    # e.g. "In <other month> I had a job die halfway…": the speaker dates the story to another event
    months = [m for m in L.MONTHS if re.search(rf"\bin {m}\w*\b", text, re.I)]
    return any(L.MONTHS[m] != incident.month for m in months) or bool(re.search(r"\blast year\b", text, re.I))


def knowledge_echoes(inv: Investigation, p) -> None:
    withheld = inv.case.fact("withheld")
    if not withheld:
        return
    tag = inv.case.interviewer_tag
    op0, _ = inv.op
    subject_tokens = _subject_tokens(inv)
    for iv in p.interviews:
        if iv.started is None:
            continue
        for ln in iv.lines:
            if ln["speaker"] == tag:
                continue
            hits = L.concept_hits(ln["text"], withheld)
            if len(hits) < L.ECHO_MIN_CONCEPTS or not (set(hits) & L.ECHO_CORE_CONCEPTS):
                continue
            T = ln["t"] or iv.started
            src = f"{iv.path}:{ln['line']}"
            key_needle = hits.get("restart") or hits.get("failure") or next(iter(hits.values()))
            echo_ev = inv.evidence(src, key_needle, note=f"said {fmt_dt(T)}; phrases: {', '.join(hits.values())}")
            own = _own_earlier_event(ln["text"], op0)
            routes = []          # (label, concepts, evidence list, strength)
            # 1. public record before T, after the operation happened (or the person's own earlier record)
            pub_cov: dict[str, list] = {}
            for e in inv.rec.events:
                if e.t is None or e.t >= T or e.kind not in ("slack", "jira", "jira_comment", "email", "ticket_comment", "meeting_note"):
                    continue
                if e.kind == "email":
                    continue  # subject lines only; bodies are handled via inv.rec.emails below
                if not own and e.t < op0:
                    continue
                if own and e.actor != p.handle:
                    continue
                about = (e.text + " " + (e.attrs.get("summary") or "")).lower()
                cov = L.concept_hits(e.text, list(hits))
                if own and len(cov) < 2:
                    continue  # one's own record must describe the same sequence, not a stray word
                if not own and not any(tok in about for tok in subject_tokens):
                    continue
                for c in cov:
                    pub_cov.setdefault(c, []).append(e)
            for em in inv.rec.emails:
                if em.date is None or em.date >= T or (not own and em.date < op0):
                    continue
                if p.email not in ([em.sender] + em.recipients):
                    continue
                body = em.body_text()
                if own or not any(tok in (body + " " + em.subject).lower() for tok in subject_tokens):
                    continue
                for c in L.concept_hits(body, list(hits)):
                    pub_cov.setdefault(c, []).append(em)
            if pub_cov:
                ev = []
                by_src: dict = {}
                for c, docs in pub_cov.items():
                    d0 = docs[0]
                    if hasattr(d0, "source") and hasattr(d0, "kind"):
                        by_src.setdefault(d0.source, (d0, []))[1].append(c)
                for d0, cs in by_src.values():
                    ev.append(inv.ev_event(d0, L.concept_hits(d0.text, cs).get(cs[0]),
                                           note=f"covers {'/'.join(cs)} ({d0.kind}, {fmt_dt(d0.t)}, by {d0.actor})"))
                authored = any(getattr(d, "actor", None) == p.handle for ds in pub_cov.values() for d in ds)
                routes.append(("own earlier experience, written down at the time" if own else
                               ("own public record" if authored else "public record (chat/tickets) before the interview"),
                               set(pub_cov), ev, "strong" if authored or own else "medium"))
            # 2. leaks: withheld facts exposed to this person before T
            for lk in inv.leaks:
                if lk.t >= T:
                    continue
                for a in lk.audience:
                    if a["person"] != p.key or a["present"] == "outside":
                        continue
                    decision = inv.tasks.decision("human", "leak", f"{p.key}|{lk.t.isoformat()}")
                    if decision and decision["decision"] == "reject":
                        continue
                    routes.append((f"could overhear the {fmt_dt(lk.t)} call ({lk.channel})", set(hits),
                                   lk.evidence + a["evidence"], "medium"))
            explained = set()
            for _, cov, _, _ in routes:
                explained |= cov
            unexplained = [c for c in hits if c not in explained]
            base = dict(suspect=p.key, analyzer="withheld-knowledge", constraint="echo")
            wh = inv.case.facts["withheld"]
            wh_ev = inv.evidence(wh.source, "WITHHOLD", note="the investigator withheld these facts")
            if unexplained:
                f = inv.add(Finding(
                    **base, cls="INCRIMINATES",
                    title="Knew withheld details with no innocent route",
                    claim=f"At {fmt_dt(T)} described {', '.join(unexplained)} of the operation — facts the "
                          f"investigator had withheld. No record, leak or own experience before that moment explains "
                          f"{'them' if len(unexplained) > 1 else 'it'}.",
                    evidence=[echo_ev, wh_ev] + [e for r in routes for e in r[2][:1]],
                    weight=0.85, reliability="derived",
                    reasoning="Only the operator (and the investigator) knew these details when this person spoke. "
                              + (f"Routes checked and insufficient: {'; '.join(r[0] + ' → ' + '/'.join(sorted(r[1])) for r in routes)}."
                                 if routes else "No public mention, no leak and no own experience was found before the interview."),
                    caveats=["automatic transcript, not proofread"],
                ))
                inv.task(Task(
                    kind="agent", topic="echo", subject=f.key, suspect=p.key, priority=1,
                    title=f"Hunt for an innocent route to {p.name}'s knowledge of {', '.join(unexplained)}",
                    why="An unexplained echo is the strongest kind of finding; before relying on it, look harder for "
                        "anything that could have told them (chat, tickets, e-mail, meetings, leaks) before "
                        f"{fmt_dt(T)}.",
                    question=f"Search every source dated before {fmt_dt(T)} for {', '.join(unexplained)}. "
                             "Add any route found with `investigate finding add` (it is verified before use).",
                    read=[{"source": echo_ev.source, "quote": echo_ev.quote, "note": echo_ev.note}],
                ))
            else:
                susp = inv.add(Finding(
                    **base, cls="WEAKLY_INCRIMINATES",
                    title="Seemed to know withheld details",
                    claim=f"At {fmt_dt(T)} described {', '.join(hits)} of the operation — details the investigator "
                          f"had withheld.",
                    evidence=[echo_ev, wh_ev], weight=0.4, reliability="derived",
                    reasoning="This is exactly what makes a suspect look like the thief.",
                ))
                label, cov, rev, strength = max(routes, key=lambda r: (len(r[1]), r[3] == "strong"))
                inv.add(Finding(
                    **base, cls="EXONERATES", explains=susp.key,
                    title=f"Innocent route: {label}",
                    claim=f"Before {fmt_dt(T)}, {p.name} could learn {', '.join(sorted(cov))} via {label}.",
                    evidence=rev[:5], weight=0.45 if strength == "strong" else 0.4, reliability="derived",
                    reasoning="The knowledge predates the interview and has an explanation that does not require "
                              "being the operator. The suspicion is explained, not proven false.",
                ))
            break  # one echo per interview is enough


def _subject_tokens(inv) -> list[str]:
    """Specific identifiers of the incident (e.g. the quoted device name in the forensic scope).

    A public record only counts as a route to withheld facts if it is about THIS event, so
    generic words ('copy job failed, restarting') in routine chatter do not qualify.
    """
    toks = set()
    for path, doc in inv.corpus.docs.items():
        if doc.kind == "pdf":
            for txt in doc.pages.values():
                for m in re.finditer(r"'([a-z][a-z0-9]+-\d+)'", txt):
                    toks.add(m.group(1).lower())
    return sorted(toks)


# ----------------------------------------------------------------- knowledge
def secret_routes(inv: Investigation) -> None:
    pats = [re.compile(p, re.I) for p in getattr(inv.case, "secret_patterns", [])]
    if not pats:
        return
    strong = [p for p in pats if "real" in p.pattern]
    routes: dict[str, list] = {p.key: [] for p in inv.case.suspects}
    # e-mail: who sent or received the mapping; who was asked to delete a copy
    for em in inv.rec.emails:
        hit = next(((ln, t) for ln, t in em.body if any(r.search(t) for r in strong)), None)
        if not hit:
            continue
        ln, text = hit
        asked_to_delete = re.search(r"\b(pull|delete|remove|destroy)\b.*\b(copy|slide|file)|should not circulate", em.body_text(), re.I)
        for addr in [em.sender] + em.recipients:
            p = inv.person(addr)
            if not p or not p.suspect:
                continue
            role = "sender" if addr == em.sender else "recipient"
            path = em.source.split(":")[0]
            ev = [inv.evidence(f"{path}:{ln}", _secret_needle(text, strong)),
                  inv.evidence(f"{path}:{em.headers['from'][0]}", "From"),
                  inv.evidence(f"{path}:{em.headers['to'][0]}", "To")]
            if asked_to_delete and role == "recipient":
                routes[p.key].append(("asked to delete their copy of the mapping", 0.5, ev,
                                      f"{fmt_dt(em.date)} — '{em.subject}'"))
            else:
                routes[p.key].append((f"{role} of an e-mail containing the mapping", 0.4 if role == "sender" else 0.3,
                                      ev, f"{fmt_dt(em.date)} — '{em.subject}'"))
    # replies from the person that concede a copy is still out there
    for em in inv.rec.emails:
        p = inv.person(em.sender)
        if not p or not p.suspect or not em.subject.lower().startswith("re:"):
            continue
        orig = next((o for o in inv.rec.emails if o.subject and em.subject[3:].strip().lower() == o.subject.lower()
                     and p.email in o.recipients), None)
        if orig and any(r.search(orig.body_text()) for r in strong):
            ln = next((l for l, t in em.body if re.search(r"can'?t|cannot|still|have the", t, re.I)), em.body[0][0] if em.body else None)
            if ln:
                path = em.source.split(":")[0]
                routes[p.key].append(("replied that copies could not be recalled", 0.2,
                                      [inv.evidence(f"{path}:{ln}")], f"{fmt_dt(em.date)} — '{em.subject}'"))
    # the investigator's own list of who could know
    for e in inv.rec.by_kind("notebook"):
        if not any(r.search(e.text) for r in strong):
            continue
        path, line = e.source.rsplit(":", 1)
        doc = inv.corpus.get(path)
        i = int(line)
        while i < len(doc.lines) and doc.lines[i].startswith("  "):
            sub = doc.lines[i]
            for p in inv.case.mentions(sub, suspects_only=True):
                routes[p.key].append(("named in the investigator's list of who could know", 0.3,
                                      [inv.evidence(f"{path}:{i + 1}", p.name.split()[0])], sub.strip()[:80]))
            i += 1
    # people who say they did not know
    neg = L.compile_all(L.NEGATED_KNOWLEDGE)
    for p in inv.case.suspects:
        for iv in p.interviews:
            for ln in iv.lines:
                if ln["speaker"] != inv.case.interviewer_tag and any(r.search(ln["text"]) for r in neg):
                    m = next(r.search(ln["text"]) for r in neg if r.search(ln["text"]))
                    inv.add(Finding(
                        suspect=p.key, analyzer="secret-routes", constraint="knowledge", cls="NEUTRAL",
                        title=f"Says they could not tell real from {inv.case.fact('secret') or 'fake'}",
                        claim=f"'{_short(ln['text'], 150)}'",
                        evidence=[inv.evidence(f"{iv.path}:{ln['line']}", m.group(0))],
                        weight=0.05, reliability="self",
                        caveats=["self-serving statement; recorded, not relied on"],
                    ))
                    break
    secret = inv.case.fact("secret") or "secret"
    for p in inv.case.suspects:
        rs = routes[p.key]
        if not rs:
            inv.add(Finding(
                suspect=p.key, analyzer="secret-routes", constraint="knowledge", cls="EXONERATES",
                title=f"No documented route to the real/{secret} mapping",
                claim=f"No e-mail, meeting record or investigator note connects {p.name} to which artifacts were "
                      f"real (the operator avoided every {secret}).",
                weight=0.25, reliability="absence",
                caveats=["absence of a record; people talk"],
            ))
            continue
        seen = set()
        for label, w, ev, note in sorted(rs, key=lambda r: -r[1]):
            if label in seen:
                continue
            seen.add(label)
            inv.add(Finding(
                suspect=p.key, analyzer="secret-routes", constraint="knowledge", cls="WEAKLY_INCRIMINATES",
                title=f"Route to the mapping: {label}",
                claim=f"{note}.", evidence=ev, weight=w, reliability="document",
                reasoning="Capability, not guilt: the operator needed to know which artifacts were real.",
            ))


def _secret_needle(text, strong):
    for r in strong:
        m = r.search(text)
        if m:
            return m.group(0)
    return None


# ---------------------------------------------------------------------- link
def receiver_links(inv: Investigation) -> None:
    org = inv.case.fact("receiver")
    if not org:
        return
    rows = inv.rec.by_kind("diligence")
    owners = {}
    for e in rows:
        if e.actor:
            owners.setdefault(e.actor, []).append(e)
    total = sum(len(v) for v in owners.values()) or 1
    rel = re.compile(r"\b(ran|process|counterpart|approach\w*|thread|talks|negotiat\w*|continuing role|owner of record)\b", re.I)
    owner_lines = inv.corpus.search(r"owner of record", limit=50)
    for p in inv.case.suspects:
        mine = owners.get(p.handle, [])
        notes = [e for e in inv.rec.by_kind("notebook") if org.lower() in e.text.lower() and rel.search(e.text)
                 and any(re.search(rf"(?<![\w.]){re.escape(a)}(?!\w)", e.text.lower()) for a in p.aliases if len(a) > 3)]
        share = len(mine) / total
        rec_lines = [h for h in owner_lines if p.handle and p.handle in h["text"]]
        if rec_lines:
            path = rec_lines[0]["source"].rsplit(":", 1)[0]
            scope = [h for h in inv.corpus.search(r"broader than intended|never re-scoped|active staging", limit=10)]
            ev = [inv.evidence(h["source"], p.handle) for h in rec_lines[:2]]
            ev += [inv.evidence(h["source"], re.search(r"broader than intended|never re-scoped|active staging", h["text"], re.I).group(0))
                   for h in scope[:2]]
            inv.add(Finding(
                suspect=p.key, analyzer="receiver-link", constraint="knowledge", cls="WEAKLY_INCRIMINATES",
                title=f"Owner of record of the {org} data room, whose export role could read the staging tree",
                claim=f"{p.name} is named owner of record; a data-room role was scoped broader than intended and "
                      f"never revoked.",
                evidence=ev, weight=0.3, reliability="document",
                reasoning="An access path existed under this person's process. Whether they personally held the "
                          "credential is not in the file.",
                caveats=["ownership of record is a business role, not proof of credential use"],
            ))
        if notes:
            ev = [inv.ev_event(mine[0], p.handle, note=f"{len(mine)} of {total} diligence rows owned")] if mine else []
            ev += [inv.ev_event(n, org) for n in notes[:2]]
            inv.add(Finding(
                suspect=p.key, analyzer="receiver-link", constraint="link", cls="WEAKLY_INCRIMINATES",
                title=f"Sustained direct contact with {org}",
                claim=f"Owned {len(mine)} of {total} diligence requests ({share:.0%})"
                      + (f"; the investigator notes the relationship ({len(notes)} note(s))." if notes else "."),
                evidence=ev, weight=0.4, reliability="document",
                reasoning=f"A channel to the party that ended up with the model. Business contact is not theft.",
            ))
        elif mine:
            inv.add(Finding(
                suspect=p.key, analyzer="receiver-link", constraint="link", cls="NEUTRAL",
                title=f"Some contact with {org}",
                claim=f"Owned {len(mine)} of {total} diligence requests.",
                evidence=[inv.ev_event(mine[0], p.handle)], weight=0.0, reliability="document",
            ))


# ---------------------------------------------------------------------- leads
def leads(inv: Investigation) -> None:
    """The investigator's suspect sheets, and the investigator's own later verifications."""
    nb = inv.rec.by_kind("notebook")
    for p in inv.case.suspects:
        surname = p.name.split()[-1]
        sheet = next((e for e in nb if re.match(rf"^- \*\*{re.escape(surname)}\*\*", e.text)), None)
        if sheet:
            text = re.sub(r"^- \*\*[^*]+\*\*\s*", "", sheet.text)
            inv.add(Finding(
                suspect=p.key, analyzer="lead", constraint="lead", cls="WEAKLY_INCRIMINATES",
                title="Why on the list",
                claim=text, evidence=[inv.ev_event(sheet, surname)], weight=0.15, reliability="document",
                reasoning="Starting suspicion from the investigator's suspect sheet. Each point needs paperwork.",
            ))
        # later notes that verify or clear something about this person
        first_iv = min((iv.started for iv in p.interviews if iv.started), default=None)
        for e in nb:
            if first_iv is None or e.t is None or e.t.date() < first_iv.date():
                continue
            low = e.text.lower()
            if not any(a in low for a in p.aliases if len(a) > 3):
                continue
            m = next((re.search(w, e.text, re.I) for w in L.VERIFIED_WORDS if re.search(w, e.text, re.I)), None)
            if not m:
                continue
            # the note is about the person in the possessive ("X confirms Y's access" is about Y)
            mentioned = inv.case.mentions(e.text, suspects_only=True)
            owners = [q for q in mentioned if any(re.search(rf"\b{re.escape(a)}'s\b", low) for a in q.aliases)]
            if (owners and p not in owners) or (not owners and mentioned and mentioned[0] is not p):
                continue
            strong = bool(re.search(r"verified|accounted for", e.text, re.I))
            inv.add(Finding(
                suspect=p.key, analyzer="investigator-verified", constraint="lead", cls="EXONERATES",
                title="The investigator checked a point and it held",
                claim=_short(e.text.lstrip("- "), 220),
                evidence=[inv.ev_event(e, m.group(0))], weight=0.5 if strong else 0.3, reliability="document",
                reasoning="The investigator's own follow-up, written after the interviews.",
            ))
        # agent task: every lead gets a paperwork check
        if sheet:
            inv.task(Task(
                kind="agent", topic="lead", subject=f"{p.key}|lead", suspect=p.key, priority=3,
                title=f"Find the paperwork behind each point of {p.name}'s suspect sheet",
                why="The trap: suspicious points often have an innocent explanation in another file.",
                question="For each point on the sheet, search the bundle for a record that confirms or explains it "
                         "and add it with `investigate finding add` (verified before use).",
                read=[{"source": sheet.source, "quote": inv.ev_event(sheet, surname).quote, "note": "suspect sheet"}],
            ))
