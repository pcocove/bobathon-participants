"""Stage 3 — the inconsistency sweep. Runs BEFORE any argument is built.

1. Hint scan: every place a source warns that it may be wrong, incomplete or withheld.
2. Observed inconsistencies: two records of the same thing that disagree.
3. Fix what can be fixed with evidence (and say so), resolve what can be resolved by
   elimination, and turn the rest into agent/human tasks.

Later stages only ever see the fixed view, and every fix is listed with its evidence.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from . import garage as G
from . import lexicon as L
from .engine import Investigation, Leak, room_ids
from .findings import Evidence, Finding, Issue
from .tasks import Task
from .util import dst_shift_minutes, dst_transitions, fmt_dt


def run(inv: Investigation, profile: str = "investigator") -> None:
    """The same sweep serves both agents; the Guard skips the suspect-specific checks."""
    scan_hints(inv)
    check_time_bases(inv)
    check_clocks(inv)
    check_transcripts(inv)
    if profile == "investigator":
        resolve_degraded_reads(inv)
        check_narratives(inv)
    find_leak_channels(inv)
    if profile == "investigator":
        resolve_sightings(inv)
    n_fixed = sum(1 for i in inv.store.issues if i.kind == "sweep" and i.resolution in ("fixed", "explained"))
    inv.stage("sweep", f"{len(inv.hints)} hints, {len([i for i in inv.store.issues if i.kind == 'sweep'])} "
                       f"inconsistencies ({n_fixed} fixed/explained)")


# --------------------------------------------------------------------------- 1
def scan_hints(inv: Investigation) -> None:
    compiled = {cat: L.compile_all(p) for cat, p in L.HINT_PATTERNS.items()}
    seen = set()
    for path, doc in inv.corpus.docs.items():
        chatty = path.startswith("slack_export/") or path.endswith(".mbox") or path.endswith(".json") \
            or path.endswith(".ics")
        for cite, text in doc.unit_lines():
            if chatty:
                # only headers/comments of machine exports
                if not (text.startswith("#") or (doc.kind == "text" and cite.endswith((":1", ":2", ":3")))):
                    continue
            elif path.endswith(".csv") and not text.startswith("#"):
                continue
            for cat, rxs in compiled.items():
                for rx in rxs:
                    m = rx.search(text)
                    if m and (cat, cite) not in seen:
                        seen.add((cat, cite))
                        ev = inv.evidence(cite, m.group(0))
                        inv.hints.append({"category": cat, "source": cite, "quote": ev.quote,
                                          "match": m.group(0), "ocr": doc.is_ocr, "status": ev.status})
                        break
    # the briefing documents (outside the bundle) are hints too
    for name, text in inv.case.briefs.items():
        for i, ln in enumerate(text.splitlines(), 1):
            for cat, rxs in compiled.items():
                if any(rx.search(ln) for rx in rxs):
                    inv.hints.append({"category": cat, "source": f"brief:{name}:{i}", "quote": ln.strip()[:200],
                                      "match": "", "ocr": False, "status": "brief"})
                    break


def _hints(inv, cat):
    return [h for h in inv.hints if h["category"] == cat]


# --------------------------------------------------------------------------- 2
def check_time_bases(inv: Investigation) -> None:
    bases = inv.rec.time_basis
    cal = {p: b for p, b in bases.items() if p.startswith("calendars/")}
    kinds = defaultdict(list)
    for p, b in cal.items():
        k = "utc" if "utc" in b.split(":")[-1] else ("tzid" if "tzid" in b else "other")
        kinds[k].append(p)
    if len(kinds) > 1:
        ev = []
        for k, paths in kinds.items():
            doc = inv.corpus.get(paths[0])
            ln = next(i for i, l in enumerate(doc.lines, 1) if l.startswith("DTSTART"))
            ev.append(inv.evidence(f"{paths[0]}:{ln}", "DTSTART", note=f"{len(paths)} calendar(s) use {k}"))
        inv.issue(Issue(
            kind="sweep", category="clock", severity="medium",
            title="Calendar exporters use different time bases",
            observation=f"{len(kinds.get('utc', []))} calendars store UTC ('Z') times, "
                        f"{len(kinds.get('tzid', []))} store local times with TZID. Treating them alike shifts "
                        "events by one to two hours.",
            evidence=ev, resolution="fixed",
            fix="Each calendar is converted using its own declaration (Z → UTC, TZID → that zone).",
            effect="Calendar events are comparable across people.",
        ))
    # card feed vs expense detail: the same transaction recorded twice
    feed = inv.rec.by_kind("card")
    pairs = []
    for cl in inv.rec.claims:
        for it in cl.items:
            amt = re.sub(r"[^\d.]", "", it["amount"])
            for e in feed:
                if e.actor == cl.handle and e.attrs.get("amount") == amt and abs((e.t - it["t"]).total_seconds()) < 36 * 3600:
                    pairs.append((cl, it, e, int((it["t"] - e.t).total_seconds() // 60)))
                    break
    if pairs:
        deltas = [d for *_, d in pairs]
        agree = sum(1 for d in deltas if abs(d) <= L.CLOCK_TOLERANCE_MIN)
        cl, it, e, d = pairs[0]
        inv.issue(Issue(
            kind="sweep", category="clock", severity="low" if agree == len(pairs) else "high",
            title="Card feed (UTC) vs expense claim detail (terminal time)",
            observation=f"{len(pairs)} transactions appear in both. After converting the card feed from UTC, "
                        f"{agree}/{len(pairs)} agree to the minute with the expense detail.",
            evidence=[inv.evidence(e.source, e.attrs.get("merchant")), inv.evidence(f"{cl.path}:{it['line']}", it["detail"][:20])],
            resolution="fixed" if agree == len(pairs) else "open",
            fix="Card feed converted UTC → local; expense detail read as local terminal time.",
            effect="Card data and expense claims can be compared directly.",
        ))


# --------------------------------------------------------------------------- 3
def check_clocks(inv: Investigation) -> None:
    """Bare-local clocks (no zone declared) are checked against records of the same moment."""
    hint_srcs = [h for h in _hints(inv, "clock")]
    garage_evs = inv.rec.by_kind("garage")
    if not garage_evs:
        return
    path = garage_evs[0].source.split(":")[0]
    anchors = []
    bo = inv.case.blackout or inv.op
    days = {(bo[0] + timedelta(days=k)).date() for k in (-1, 0, 1)} | {bo[1].date()}
    # (a) someone says in chat they are leaving; their plate exits the garage the same evening.
    #     Only the days around the incident matter — routine "going home" posts are noise.
    for msg in inv.rec.by_kind("slack"):
        if msg.t.date() not in days or not any(re.search(p, msg.text, re.I) for p in L.LEAVING_MESSAGE):
            continue
        p = inv.person(msg.actor)
        if not p or not p.plates:
            continue
        best = None
        for e in garage_evs:
            if e.attrs.get("plate") in p.plates and G.is_exit(e) and e.t.date() == msg.t.date():
                d = (e.t - msg.t).total_seconds() / 60
                if abs(d) <= 150 and (best is None or abs(d) < abs(best[1])):
                    best = (e, d)
        if best:
            anchors.append({"kind": "chat 'leaving' vs barrier exit", "person": p.name, "delta": round(best[1]),
                            "dst": dst_shift_minutes(inv.rec.zone, msg.t) > 0,
                            "evidence": [inv.ev_event(msg), inv.ev_event(best[0])]})
    # (b) an expense narrative says the purchase was made "on the way in"; the entry must come after it
    for cl in inv.rec.claims:
        if not re.search(r"on (?:the|my) way in|before (?:coming|going) in", cl.narrative, re.I):
            continue
        p = inv.person(cl.handle)
        if not p or not p.plates:
            continue
        for it in cl.items:
            entries = [e for e in garage_evs if e.attrs.get("plate") in p.plates and G.is_entry(e)
                       and e.t.date() == it["t"].date()]
            if entries:
                e = min(entries, key=lambda x: abs((x.t - it["t"]).total_seconds()))
                d = (e.t - it["t"]).total_seconds() / 60
                if d < 0:
                    anchors.append({"kind": "purchase 'on the way in' vs barrier entry", "person": p.name,
                                    "delta": round(d), "bound": True,
                                    "dst": dst_shift_minutes(inv.rec.zone, it["t"]) > 0,
                                    "evidence": [inv.evidence(f"{cl.path}:{cl.narrative_line}", "way in"),
                                                 inv.evidence(f"{cl.path}:{it['line']}", it["detail"][:15]),
                                                 inv.ev_event(e)]})
    # (c) seasonal step: habitual arrival times jump when the zone changes DST, if the clock does not
    first_entry: dict = {}
    for e in garage_evs:
        if G.is_entry(e) and not e.attrs.get("degraded"):
            k = (e.attrs["plate"], e.t.date())
            m = e.t.hour * 60 + e.t.minute
            first_entry[k] = min(first_entry.get(k, 10 ** 6), m)
    days = sorted({d for _, d in first_entry})
    step_ev = None
    shift = None
    trans = dst_transitions(inv.rec.zone, days[0], days[-1]) if days else []
    for tday in trans:
        per_plate = []
        for plate in {p for p, _ in first_entry}:
            before = [m for (p, d), m in first_entry.items() if p == plate and tday - timedelta(days=42) <= d < tday]
            after = [m for (p, d), m in first_entry.items() if p == plate and tday < d <= tday + timedelta(days=42)]
            if len(before) >= 5 and len(after) >= 5:
                per_plate.append(statistics.median(after) - statistics.median(before))
        if len(per_plate) >= 8:
            shift = {"transition": tday.isoformat(), "median_shift_min": statistics.median(per_plate),
                     "plates": len(per_plate)}
            break

    # (d) the sources may document the fault themselves: a line that names this system (words from
    #     its own header) and says its clock is off. This is the first thing to look for.
    doc = inv.corpus.get(path)
    header = " ".join(l for l in doc.lines[:3] if l.startswith("#"))
    names = {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöü]{6,}", header)} | {"barrier", "garage", "parking"}
    documented = []
    for h in inv.corpus.search(r"clock|winter ?time|summer ?time|hour off|one hour", limit=400):
        low = h["text"].lower()
        if h["source"].startswith(path) or not any(n in low for n in names):
            continue
        if re.search(r"clock.{0,60}(wrong|off|stayed|behind|ahead)|(one|an) hour off|winter ?time|summer ?time", low):
            documented.append(h)
    doc_ev = [inv.evidence(h["source"], re.search(r"winter ?time|hour off|clock", h["text"], re.I).group(0),
                           note="the sources document the fault") for h in documented[:3]]

    offending = [a for a in anchors if abs(a["delta"]) > L.CLOCK_TOLERANCE_MIN]
    dst_like = shift is not None and abs(abs(shift["median_shift_min"]) - 60) <= 10
    anchors_agree = offending and all(a["dst"] for a in offending) and \
        all(-80 <= a["delta"] <= -40 for a in offending if not a.get("bound"))
    decision = inv.tasks.decision("human", "clock", path)
    ev = [e for a in offending[:3] for e in a["evidence"]]
    obs = [f"documented: '{d.quote}' ({d.source})" for d in doc_ev]
    for a in offending[:4]:
        obs.append(f"{a['person']}: {a['kind']} differ by {a['delta']:+d} min")
    if shift:
        obs.append(f"habitual arrival times jump by {shift['median_shift_min']:+.0f} min across the "
                   f"{shift['transition']} DST change ({shift['plates']} plates)")
    if not offending and not dst_like and not doc_ev:
        if hint_srcs:
            inv.issue(Issue(kind="sweep", category="clock", severity="low",
                            title="Barrier clock checked against other records",
                            observation="No disagreement beyond tolerance found.", resolution="explained"))
        return
    apply = ((dst_like and (anchors_agree or not offending)) or (doc_ev and (dst_like or anchors_agree))) \
        and not (decision and decision["decision"] == "reject")
    if apply:
        shift_sign = 1 if (shift["median_shift_min"] if shift else 1) > 0 else -1
        for e in garage_evs:
            add = dst_shift_minutes(inv.rec.zone, e.t) * shift_sign
            if add:
                e.t = e.t + timedelta(minutes=add)
                e.attrs["clock_fix"] = f"{add:+d} min (barrier clock ignores summer time)"
        inv.clock_fixes[path] = {"rule": "add the DST offset during summer time", "shift": shift,
                                 "anchors": [{k: v for k, v in a.items() if k != "evidence"} for a in anchors]}
        # re-sort
        inv.rec.events.sort(key=lambda x: (x.t is None, x.t or datetime.min.replace(tzinfo=inv.rec.zone)))
    hint_ev = [inv.evidence(h["source"], h["match"]) for h in hint_srcs
               if h["source"].startswith(path)][:1]
    inv.issue(Issue(
        kind="sweep", category="clock", severity="high",
        title="Garage barrier clock is one hour off in summer — documented and confirmed",
        observation="; ".join(obs),
        evidence=doc_ev + hint_ev + ev,
        resolution="fixed" if apply else "needs-human",
        fix=("Barrier times during summer time are shifted by +60 min (the system clock stays on standard time). "
             "Raw times are kept in every citation." if apply else "No correction applied."),
        effect="Every garage time used later is the corrected wall-clock time; quotes still show the raw line.",
    ))
    inv.task(Task(
        kind="human", topic="clock", subject=path, priority=2,
        title="Confirm the garage clock correction",
        why="A clock correction changes who was where. The sweep inferred it from matching records, "
            "but whether a landlord's barrier clock was wrong is a judgement a person should sign off.",
        question="Do the matched records convince you the barrier clock ran one hour behind in summer?",
        read=[{"source": e.source, "quote": e.quote, "note": e.note} for e in (doc_ev + ev)[:7]],
        options=["confirm", "reject"],
        effect={"confirm": "keep the correction", "reject": "use raw barrier times; re-run analysis"},
    ))


# --------------------------------------------------------------------------- 4
def check_transcripts(inv: Investigation) -> None:
    hints = _hints(inv, "transcription")
    if not inv.rec.interviews or not hints:
        return
    tag = inv.case.interviewer_tag
    labels = defaultdict(int)
    for iv in inv.rec.interviews:
        for ln in iv.lines:
            labels[ln["speaker"]] += 1
    inv.issue(Issue(
        kind="sweep", category="transcription", severity="low",
        title="Automatic speaker labels are unreliable",
        observation=f"Transcripts are not proofread; labels seen: {dict(labels)}.",
        evidence=[inv.evidence(h["source"], h["match"]) for h in hints[:2]],
        resolution="fixed",
        fix=f"Every line not labelled '{tag}' (the interviewer) is attributed to the interviewee named in the header; "
            "quotes are taken from the transcript text only, never from the label.",
        effect="Statements are attributed per interview, not per label.",
    ))


# --------------------------------------------------------------------------- 5
def resolve_degraded_reads(inv: Investigation) -> None:
    bo = inv.case.blackout or inv.op
    lo, hi = bo[0] - timedelta(hours=36), bo[1] + timedelta(hours=36)
    garage_evs = inv.rec.by_kind("garage")
    known_plates = {e.attrs["plate"] for e in garage_evs if not e.attrs.get("degraded")} | {p.plate for p in inv.rec.permits}
    suspect_plates = {pl: p for p in inv.case.suspects for pl in p.plates}
    for e in garage_evs:
        if not e.attrs.get("degraded") or not (lo <= e.t <= hi):
            continue
        rx = re.compile("^" + re.escape(e.attrs["plate"]).replace(r"\?", "[0-9A-Z]") + "$")
        cands = sorted(p for p in known_plates if rx.match(p))
        rows = []
        for c in cands:
            state, last = G.state_at(inv, c, e.t, include_resolved=False)
            consistent = (G.is_exit(e) and state == "inside") or (G.is_entry(e) and state in ("outside", "unknown"))
            h = G.history(inv, c)
            holder = next((pm for pm in inv.rec.permits if pm.plate == c), None)
            rows.append({"plate": c, "state_before": state, "last": last, "consistent": consistent,
                         "history": h, "holder": holder.holder if holder else "?", "permit": holder})
        consistent = [r for r in rows if r["consistent"]]
        affects = [suspect_plates[r["plate"]].key for r in rows if r["plate"] in suspect_plates]
        ev = [inv.ev_event(e, e.attrs["plate"], note=f"read confidence {e.attrs.get('confidence')}%")]
        obs = [f"Read '{e.attrs['plate']}' at {fmt_dt(e.t)} ({e.attrs.get('direction')}, confidence "
               f"{e.attrs.get('confidence')}%) matches {len(cands)} known plate(s)."]
        for r in rows:
            last = r["last"]
            obs.append(f"{r['plate']} ({r['holder']}): last clean record before it = "
                       f"{last.attrs.get('direction') + ' ' + fmt_dt(last.t) if last else 'none'} → car {r['state_before']}; "
                       f"{r['history'].get('overnight_stays', 0)} overnight stays in {r['history'].get('days', 0)} days")
            if last:
                ev.append(inv.ev_event(last, r["plate"], note=f"{r['plate']} last clean record"))
            if r["permit"]:
                ev.append(inv.evidence(r["permit"].source, r["plate"], note=f"permit: {r['holder']}"))
        if len(consistent) == 1:
            win = consistent[0]
            inv.plate_resolutions[e.source] = {"plate": win["plate"], "candidates": [r["plate"] for r in rows],
                                               "why": "only candidate whose car was in a state to make this move"}
            e.attrs["resolved_plate"] = win["plate"]
            resolution = "fixed"
            fix = (f"Attributed to {win['plate']} ({win['holder']}) by elimination: every other candidate was already "
                   f"{'outside' if G.is_exit(e) else 'inside'} and could not have made this {e.attrs.get('direction')}.")
        else:
            resolution = "needs-human"
            fix = "Ambiguous — not used as evidence until a human decides."
        if not affects and len(rows) <= 1 and resolution == "fixed":
            continue  # nobody we care about, nothing to say
        inv.issue(Issue(
            kind="sweep", category="recognition", severity="high" if affects else "low",
            title=f"Degraded plate read '{e.attrs['plate']}' near the incident window",
            observation=" ".join(obs), evidence=ev, resolution=resolution, fix=fix, affects=affects,
            effect="Used as presence evidence only as resolved here, and flagged as a degraded read.",
        ))
        if affects:
            inv.task(Task(
                kind="human", topic="plate", subject=e.source, priority=1,
                suspect=affects[0] if len(affects) == 1 else None,
                title=f"Confirm who the degraded read '{e.attrs['plate']}' at {fmt_dt(e.t)} belongs to",
                why="The read is below the recognition threshold and matches more than one real plate. "
                    "Elimination by car state is mechanical, but accepting it as someone's movement is a judgement.",
                question=f"Do you accept '{e.attrs['plate']}' as "
                         f"{consistent[0]['plate'] if len(consistent) == 1 else '(undecided)'}?",
                read=[{"source": x.source, "quote": x.quote, "note": x.note} for x in ev],
                options=["accept", "reject"],
                effect={"accept": "use the read as resolved", "reject": "drop the read; rely on other records"},
            ))
            decision = inv.tasks.decision("human", "plate", e.source)
            if decision and decision["decision"] == "reject":
                inv.plate_resolutions.pop(e.source, None)
                e.attrs.pop("resolved_plate", None)


# --------------------------------------------------------------------------- 6
_DATE_RX = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*"
                      r"(?:\s+(morning|afternoon|evening|night))?", re.I)


def claimed_ranges(text: str, year: int, zone) -> list[tuple[datetime, datetime, str]]:
    out = []
    for m in _DATE_RX.finditer(text):
        d = datetime(year, L.MONTHS[m.group(3)[:3].lower()], int(m.group(2)))
        part = (m.group(4) or "").lower()
        if not part:
            # "evening" may come later in the sentence
            tail = text[m.end():m.end() + 25].lower()
            part = next((p for p in L.PART_OF_DAY if p in tail.split() or p in tail), "")
        h0, h1 = L.PART_OF_DAY.get(part, (0, 24))
        a = d.replace(tzinfo=zone) + timedelta(hours=h0)
        b = d.replace(tzinfo=zone) + timedelta(hours=h1)
        out.append((a, b, m.group(0) + (f" {part}" if part and part not in m.group(0).lower() else "")))
    return out


def check_narratives(inv: Investigation) -> None:
    """Self-reported narratives (expense claims) vs the card data attached to them."""
    op0, op1 = inv.op
    feed = inv.rec.by_kind("card")
    for cl in inv.rec.claims:
        p = inv.person(cl.handle)
        if not p or not cl.items:
            continue
        ranges = claimed_ranges(cl.narrative, op0.year, inv.rec.zone)
        touches = any(a <= op1 + timedelta(hours=24) and b >= op0 - timedelta(hours=24) for a, b, _ in ranges)
        flagged = bool(cl.finance_note and any(re.search(pt, cl.finance_note, re.I) for pt in L.HINT_PATTERNS["narrative_mismatch"]))
        if not (touches and (p.suspect or flagged)):
            continue
        items = sorted(cl.items, key=lambda it: it["t"])
        claimed_a, claimed_b, phrase = ranges[0]

        def city_of(it):
            amt = re.sub(r"[^\d.]", "", it["amount"])
            for e in feed:
                if e.actor == cl.handle and e.attrs.get("amount") == amt and abs((e.t - it["t"]).total_seconds()) < 600:
                    return e.attrs.get("city", ""), e
            return ("" if inv.site.lower() not in it["detail"].lower() else inv.site), None
        first = items[0]
        city, feed_ev = city_of(first)
        at_site = inv.is_site(city)
        narrative_ev = inv.evidence(f"{cl.path}:{cl.narrative_line}", phrase.split()[0])
        item_ev = inv.evidence(f"{cl.path}:{first['line']}", first["detail"][:18], note=f"{fmt_dt(first['t'])}")
        ev = [narrative_ev, item_ev]
        if feed_ev:
            ev.append(inv.ev_event(feed_ev, feed_ev.attrs.get("merchant"), note="same transaction in the card issuer feed"))
        if cl.finance_line:
            ev.append(inv.evidence(f"{cl.path}:{cl.finance_line}", "differs"))
        later = first["t"] > claimed_b
        earlier = first["t"] < claimed_a
        if later and at_site and first["t"] > op0:
            # still at the site after the operation started, although the narrative says they had left
            inv.issue(Issue(
                kind="sweep", category="narrative_mismatch", severity="high", affects=[p.key],
                title=f"{p.name}: narrative departure contradicted by card data",
                observation=f"Narrative: '{cl.narrative}'. First attached card transaction is {first['detail']} "
                            f"at {fmt_dt(first['t'])} — in {city or inv.site}, after the operation window opened.",
                evidence=ev, resolution="open",
                fix="Card data outranks the narrative (bank record vs self-report).",
                effect="Statement contradicted; the person was at the site when they claim to have left.",
            ))
            inv.add(Finding(
                suspect=p.key, analyzer="narrative-vs-card", constraint="statement", cls="INCRIMINATES",
                title="Claimed departure contradicted by own card", stage="sweep",
                claim=f"Claims to have left '{phrase}'; card shows them in {city or inv.site} at {fmt_dt(first['t'])}, "
                      f"after the operation ({fmt_dt(op0, False)}–{fmt_dt(op1, False)}).",
                evidence=ev, weight=0.9, reliability="bank",
                reasoning="The narrative is the person's own account; the card transaction is an issuer record. "
                          "The first trace of the trip is the next morning, from the site.",
            ))
        elif earlier or not at_site:
            inv.issue(Issue(
                kind="sweep", category="narrative_mismatch", severity="medium", affects=[p.key],
                title=f"{p.name}: narrative date differs from card times",
                observation=f"Narrative: '{cl.narrative}'. First card transaction: {first['detail']} at "
                            f"{fmt_dt(first['t'])} ({city or 'elsewhere'}).",
                evidence=ev, resolution="explained",
                fix="The card places the person away from the site; the narrative is imprecise, not an alibi problem.",
                effect="Card data is used for presence; the narrative is not relied on.",
            ))


# --------------------------------------------------------------------------- 7
def find_leak_channels(inv: Investigation) -> None:
    """Where withheld facts could have leaked: a conversation someone next door could hear."""
    acoustic = re.compile(r"audible|hear|sound|partition|wall|intelligible", re.I)
    adjacency: dict[str, list[tuple[str, Evidence]]] = defaultdict(list)
    for path, doc in inv.corpus.docs.items():
        if path.startswith("slack_export/"):
            continue
        for cite, text in doc.unit_lines():
            rooms = list(dict.fromkeys(room_ids(text)))
            if len(rooms) >= 2 and acoustic.search(text):
                ev = inv.evidence(cite, rooms[0])
                for a in rooms:
                    for b in rooms:
                        if a != b and all(x[0] != b for x in adjacency[a]):
                            adjacency[a].append((b, ev))
    if not adjacency:
        return
    since = inv.case.fact("withheld_since")
    forensic_author = _report_author(inv)
    discussions = []
    for e in inv.rec.by_kind("notebook"):
        if e.basis != "local-bare" or not re.search(r"speaker|lautsprecher|called|call\b|phone", e.text, re.I):
            continue
        rooms = room_ids(e.text)
        about = re.search(r"findings|forensic", e.text, re.I) or (forensic_author and forensic_author["first"] and
                                                                 forensic_author["first"].lower() in e.text.lower())
        if rooms and about and (not since or e.t >= since):
            discussions.append((e.t, rooms[0], [inv.ev_event(e, "speaker")]))
    for path, doc in inv.corpus.docs.items():
        if doc.kind != "image" or not doc.ocr_text:
            continue
        rooms = room_ids(doc.ocr_text) or room_ids(path)
        for ln in doc.ocr_text.splitlines():
            m = re.search(r"(\d{1,2})\.(\d{1,2})\.?\s+(\d{1,2}):(\d{2}).*(?:call|anruf|lautsprecher|speaker)", ln, re.I)
            if m and rooms:
                inits = forensic_author["initials"] if forensic_author else None
                if inits and inits.lower() not in ln.lower() and not re.search(r"lautsprecher|speaker", ln, re.I):
                    continue
                t = datetime(inv.op[0].year, int(m.group(2)), int(m.group(1)), int(m.group(3)), int(m.group(4)),
                             tzinfo=inv.rec.zone)
                discussions.append((t, rooms[0], [inv.evidence(path, quote=ln.strip())]))
    by_time: dict = {}
    for t, room, ev in discussions:
        k = (t, room)
        by_time.setdefault(k, []).extend(ev)
    for (t, room), ev in sorted(by_time.items()):
        leak = Leak(t=t, room=room, channel="speakerphone call audible through a partition", evidence=ev)
        for other, adj_ev in adjacency.get(room, []):
            for p in inv.case.people.values():
                for office, src, q in p.offices:
                    if office != other:
                        continue
                    why = [adj_ev, inv.evidence(src, office, note=f"{p.name}'s office is {office}")]
                    present = "unknown"
                    for pl in p.plates:
                        state, last = G.state_at(inv, pl, t)
                        if last and last.t.date() == t.date():
                            present = state
                            why.append(inv.ev_event(last, pl, note=f"car {state} at {fmt_dt(t, False)}"))
                    leak.audience.append({"person": p.key, "name": p.name, "room": office, "present": present,
                                          "evidence": why})
        inv.leaks.append(leak)
        names = ", ".join(f"{a['name']} ({a['room']}, car {a['present']})" for a in leak.audience) or "nobody identified"
        inv.issue(Issue(
            kind="sweep", category="leak_channel", severity="high" if leak.audience else "medium",
            title=f"Withheld facts discussed audibly in {room} on {fmt_dt(t)}",
            observation=f"After the facts were withheld, they were discussed by {leak.channel} in {room}. "
                        f"Rooms that can hear {room}: {', '.join(o for o, _ in adjacency.get(room, []))}. "
                        f"Possible listeners: {names}.",
            evidence=ev + [x for a in leak.audience for x in a["evidence"]],
            resolution="explained" if leak.audience else "open",
            fix="Anyone interviewed after this moment who could hear it has an innocent route to the withheld facts.",
            affects=[a["person"] for a in leak.audience],
            effect="Knowledge-echo analysis checks every echo against this leak's time and audience.",
        ))
        for a in leak.audience:
            inv.task(Task(
                kind="human", topic="leak", subject=f"{a['person']}|{t.isoformat()}", priority=2, suspect=a["person"],
                title=f"Could {a['name']} have overheard the {fmt_dt(t)} call?",
                why="Whether a person actually heard a conversation through a wall cannot be read off a record.",
                question=f"Accept the partition leak as an innocent route for {a['name']}'s knowledge?",
                read=[{"source": x.source, "quote": x.quote, "note": x.note} for x in leak.evidence + a["evidence"]],
                options=["accept", "reject"],
                effect={"accept": "echo explained by the leak", "reject": "echo stays unexplained"},
            ))


def _report_author(inv) -> dict | None:
    for path, doc in inv.corpus.docs.items():
        if doc.kind == "pdf" and not any(doc.page_ocr.values()):
            last = [l for l in doc.pages[max(doc.pages)].splitlines() if l.strip()][-1]
            m = re.match(r"([A-Z])\.\s*([A-Z][a-z]+)", last.strip())
            if m:
                first = None
                for e in inv.rec.by_kind("notebook"):
                    mm = re.search(r"\b([A-Z][a-z]+)\b[^.]{0,40}" + m.group(2)[:3], e.text)
                    if mm:
                        first = mm.group(1)
                if not first:
                    for e in inv.rec.by_kind("notebook"):
                        mm = re.search(r"\bwith ([A-Z][a-z]+) at his office|\bwith ([A-Z][a-z]+)\b", e.text)
                        if mm and (mm.group(1) or mm.group(2) or "").startswith(m.group(1)):
                            first = mm.group(1) or mm.group(2)
                return {"initials": f"{m.group(1)}.{m.group(2)[0]}.", "surname": m.group(2), "first": first,
                        "source": f"{path}:{max(doc.pages)}"}
    return None


# --------------------------------------------------------------------------- 8
def resolve_sightings(inv: Investigation) -> None:
    """Witnesses who were unsure whose car / which person they saw."""
    bo = inv.case.blackout or inv.op
    lo, hi = bo[0] - timedelta(hours=14), bo[1] + timedelta(hours=14)
    makes = {pm.vehicle.split()[0].lower() for pm in inv.rec.permits if pm.vehicle}
    texts = []   # (time, source, text, ocr, witness)
    for m in inv.rec.by_kind("slack"):
        if lo <= m.t <= hi and any(re.search(rf"\b{re.escape(mk)}\b", m.text, re.I) for mk in makes):
            texts.append((m.t, m.source, m.text, False, m.actor))
    for path, doc in inv.corpus.docs.items():
        if doc.kind != "pdf" or not any(doc.page_ocr.values()):
            continue
        for page, txt in doc.pages.items():
            lines = [l for l in txt.splitlines()]
            cur_t = None
            witness = None
            mname = re.search(r"Name:\s*_?([A-Z][a-z]+ [A-Z][a-z]+)", txt)
            if mname:
                wp = inv.person(mname.group(1))
                witness = wp.key if wp else mname.group(1)
            for k, ln in enumerate(lines):
                md = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", ln)
                mt = re.search(r"(\d{1,2}):(\d{2})", ln)
                if md and mt:
                    cur_t = datetime(int(md.group(3)), int(md.group(2)), int(md.group(1)), int(mt.group(1)),
                                     int(mt.group(2)), tzinfo=inv.rec.zone)
                block = " ".join(lines[max(0, k - 1):k + 2])
                if cur_t and any(re.search(rf"\b{re.escape(mk)}\b", ln, re.I) for mk in makes):
                    texts.append((cur_t, f"{path}:{page}", block, True, witness))
                    texts.append(("line", f"{path}:{page}", ln, True, witness))
                if cur_t and re.search(r"\(([A-Z][a-z]+)\?\)", ln):
                    who = inv.person(re.search(r"\(([A-Z][a-z]+)\?\)", ln).group(1))
                    mt2 = re.search(r"(\d{1,2}):(\d{2})", ln) or re.search(r"(\d{1,2}):(\d{2})", lines[k - 1] if k else "")
                    t2 = cur_t.replace(hour=int(mt2.group(1)), minute=int(mt2.group(2))) if mt2 else cur_t
                    if who:
                        _name_guess(inv, who, t2, f"{path}:{page}", ln.strip(), witness)
    # score permits against each sighting
    lines_for = {}
    for t, src, text, ocr, w in texts:
        if t == "line":
            lines_for.setdefault(src, []).append(text)
    for t, src, text, ocr, witness in texts:
        if t == "line":
            continue
        low = text.lower()
        scored = []
        for pm in inv.rec.permits:
            s, why = 0, []
            mk = pm.vehicle.split()[0].lower() if pm.vehicle else ""
            if mk and re.search(rf"\b{re.escape(mk)}\b", low):
                s += 2
                why.append("make")
            col = pm.colour.lower()
            if col and (re.search(rf"\b{col}", low) or re.search(rf"\b{L.COLOURS.get(col, '#')}\b", low)):
                s += 2
                why.append("colour")
            for key, syns in L.BODY_SYNONYMS.items():
                if key in pm.vehicle.lower() and any(x in low for x in syns):
                    s += 1
                    why.append(key)
            model = [w for w in re.findall(r"[A-Za-z0-9]+", pm.vehicle)[1:2] if len(w) > 1]
            if model and re.search(rf"\b{re.escape(model[0].lower())}\b", low):
                s += 1
                why.append("model")
            if pm.level and re.search(rf"(ebene|level)\s*{re.escape(pm.level)}\b", low):
                s += 1
                why.append("level")
            if s >= 2 and "make" in why:
                state, last = G.state_at(inv, pm.plate, t)
                scored.append({"permit": pm, "score": s, "why": why, "state": state, "last": last})
        if not scored:
            continue
        scored.sort(key=lambda r: -r["score"])
        top = [r for r in scored if r["score"] == scored[0]["score"]]
        if len(top) > 1:
            inside = [r for r in top if r["state"] == "inside"]
            if len(inside) == 1:
                top = inside
        if len(top) != 1:
            inv.issue(Issue(kind="sweep", category="uncertain_identification", severity="medium",
                            title=f"Vehicle sighting at {fmt_dt(t)} is ambiguous",
                            observation=f"'{text[:120]}' matches {[r['permit'].holder for r in top]}",
                            evidence=[inv.evidence(src, quote=_quote_for(inv, src, text, lines_for))],
                            resolution="needs-human"))
            continue
        win = top[0]
        pm = win["permit"]
        owner = inv.person(pm.holder)
        others = [f"{r['permit'].holder} ({r['score']} pts, car {r['state']})" for r in scored if r is not win][:3]
        quote = _quote_for(inv, src, text, lines_for)
        ev = [inv.evidence(src, quote=quote, note=f"sighting {fmt_dt(t)}"),
              inv.evidence(pm.source, pm.plate, note=f"permit: {pm.holder}, {pm.vehicle}, {pm.colour}, level {pm.level}")]
        if win["last"]:
            ev.append(inv.ev_event(win["last"], pm.plate, note=f"car {win['state']} at {fmt_dt(t, False)}"))
        sighting = {"t": t.isoformat(), "source": src, "plate": pm.plate, "holder": pm.holder,
                    "person": owner.key if owner else None, "why": win["why"], "state": win["state"], "ocr": ocr,
                    "witness": witness}
        inv.sightings.append(sighting)
        inv.issue(Issue(
            kind="sweep", category="uncertain_identification", severity="high" if owner and owner.suspect else "low",
            title=f"Whose car was seen at {fmt_dt(t)}?",
            observation=f"Witness description '{quote}' matches permit {pm.permit_id} ({pm.holder}) on "
                        f"{', '.join(win['why'])}; the barrier log has that car {win['state']} at that time. "
                        + (f"Other candidates: {'; '.join(others)}." if others else ""),
            evidence=ev, resolution="fixed" if win["state"] == "inside" else "needs-human",
            fix=f"Sighting attributed to {pm.holder}'s car ({pm.plate}).",
            affects=[owner.key] if owner else [],
            effect="Used as corroborating presence evidence.",
        ))
        if owner and owner.suspect and win["state"] == "inside":
            inv.add(Finding(
                suspect=owner.key, analyzer="witness-sighting", constraint="presence", cls="INCRIMINATES",
                stage="sweep", title=f"Car seen on site by a witness at {fmt_dt(t, False)}",
                claim=f"A witness saw a car matching {pm.holder}'s permit ({pm.vehicle}, {pm.colour}) at "
                      f"{fmt_dt(t)}; the barrier log confirms it was inside.",
                evidence=ev, weight=0.35, reliability="ocr" if ocr else "chat",
                reasoning="Two independent records (a witness and the barrier log) put the car on site as the "
                          "window opened. A car on site is not the person on site.",
                caveats=["OCR text — confirm the quote against the scan"] if ocr else [],
            ))


def _quote_for(inv, src, text, lines_for) -> str:
    doc, _, _ = inv.corpus.resolve(src)
    if doc and doc.kind == "text":
        from .util import best_span
        return best_span(doc.lines[int(src.rsplit(':', 1)[1]) - 1])
    cands = lines_for.get(src, [])
    return (cands[0] if cands else text).strip()


def _name_guess(inv, who, t, src, line, witness) -> None:
    states = []
    ev = [inv.evidence(src, quote=line, note="witness guesses a name")]
    for pl in who.plates:
        state, last = G.state_at(inv, pl, t)
        states.append(state)
        if last:
            ev.append(inv.ev_event(last, pl, note=f"car {state} at {fmt_dt(t, False)}"))
    consistent = "inside" in states
    inv.issue(Issue(
        kind="sweep", category="uncertain_identification", severity="low", affects=[who.key],
        title=f"Witness guessed '{who.name}' at {fmt_dt(t)}",
        observation=f"The witness marked the name with a question mark. Barrier log: car {'/'.join(states) or 'no plate'} "
                    f"at that time.",
        evidence=ev, resolution="explained" if consistent else "needs-human",
        fix="Consistent with the records" if consistent else "Not corroborated",
    ))
    op0, _ = inv.op
    inv.add(Finding(
        suspect=who.key, analyzer="witness-name-guess", constraint="presence", cls="NEUTRAL", stage="sweep",
        title=f"Probably on site at {fmt_dt(t, False)}, before the operation",
        claim=f"A witness heard someone they took to be {who.name} at {fmt_dt(t)} "
              f"({'before' if t < op0 else 'during'} the operation window).",
        evidence=ev, weight=0.1, reliability="witness",
        reasoning="Being in the building before the window opened says nothing about the window itself.",
    ))
