"""The case frame: who, when, where — derived from the bundle, never typed in.

Given: the suspect names (verdict_template.json lists them; the rules allow this).
Derived: identities (chat handle, e-mail, card, number plate, calendar, interview),
the blackout window, the operation window, the site, what the investigator withheld,
the secret the operator needed, and the party that received the stolen asset.
Every derived fact carries the citation it came from.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import lexicon
from .corpus import Corpus
from .records import Interview, Permit, Records
from .util import UTC


@dataclass
class Fact:
    """A derived fact with its provenance."""
    value: object
    source: str
    quote: str
    note: str = ""

    def to_dict(self) -> dict:
        v = self.value
        if isinstance(v, datetime):
            v = v.isoformat()
        elif isinstance(v, (list, tuple)):
            v = [x.isoformat() if isinstance(x, datetime) else x for x in v]
        return {"value": v, "source": self.source, "quote": self.quote, "note": self.note}


@dataclass
class Person:
    name: str
    suspect: bool = False
    handle: str | None = None
    slack_id: str | None = None
    email: str | None = None
    title: str = ""
    permits: list[Permit] = field(default_factory=list)
    card_last4: set = field(default_factory=set)
    calendar: str | None = None
    interviews: list[Interview] = field(default_factory=list)
    offices: list[tuple[str, str, str]] = field(default_factory=list)  # (room, source, quote)
    aliases: set = field(default_factory=set)
    identity_sources: list[tuple[str, str, str]] = field(default_factory=list)  # (what, source, quote)

    @property
    def plates(self) -> list[str]:
        return [p.plate for p in self.permits]

    @property
    def key(self) -> str:
        return self.handle or self.name.lower().replace(" ", ".")

    def to_dict(self) -> dict:
        return {
            "name": self.name, "suspect": self.suspect, "handle": self.handle, "slack_id": self.slack_id,
            "email": self.email, "title": self.title, "plates": self.plates,
            "card_last4": sorted(self.card_last4), "calendar": self.calendar,
            "interviews": [i.path for i in self.interviews],
            "offices": [o[0] for o in self.offices],
            "identity_sources": [{"what": w, "source": s, "quote": q} for w, s, q in self.identity_sources],
        }


class Case:
    def __init__(self, corpus: Corpus, records: Records, template_path: Path | None,
                 brief_paths: list[Path] | None = None, require_suspects: bool = True):
        self.require_suspects = require_suspects
        self.corpus = corpus
        self.rec = records
        self.zone = records.zone
        self.briefs = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in (brief_paths or []) if p.exists()}
        self.warnings: list[str] = []
        self.team = "bob-investigator"
        self.suspect_names = self._load_suspects(template_path)
        self.people: dict[str, Person] = {}
        self._build_directory()
        self.suspects: list[Person] = [self.people[self._key_for(n)] for n in self.suspect_names]
        self.facts: dict[str, Fact] = {}
        self._derive_frame()

    # --------------------------------------------------------------- suspects
    def _load_suspects(self, template_path: Path | None) -> list[str]:
        if template_path and template_path.exists():
            data = json.loads(template_path.read_text(encoding="utf-8"))
            names = [s["name"] for s in data.get("suspects", [])]
            if names:
                return names
        if not self.require_suspects:
            return []   # the Security Guard works without suspects
        # fall back: the investigator's list line ("... → 8 names: A, B, ...")
        for e in self.rec.by_kind("notebook"):
            if re.search(r"\b\d+ names?\b", e.text):
                nxt = self.corpus.get(e.source.split(":")[0]).lines[int(e.source.split(":")[1])]
                return [n.strip(" .") for n in nxt.split(",") if n.strip()]
        raise SystemExit("No suspect list: pass a verdict_template.json with the suspects")

    def _key_for(self, name: str) -> str:
        n = _clean_name(name).lower()
        for k, p in self.people.items():
            if _clean_name(p.name).lower() == n:
                return k
        raise KeyError(name)

    def _build_directory(self) -> None:
        # chat directory first: it links real names to handles and e-mail
        for u in self.rec.users.values():
            p = Person(name=u.real_name, handle=u.handle, slack_id=u.id, email=u.email, title=u.title)
            p.identity_sources.append(("chat user", u.source, u.handle))
            self.people[u.handle] = p
        for name in self.suspect_names:
            try:
                self._key_for(name)
            except KeyError:
                self.people[_clean_name(name).lower().replace(" ", ".")] = Person(name=_clean_name(name))
        for name in self.suspect_names:
            self.people[self._key_for(name)].suspect = True
        # plates: permit holder = real name
        for pm in self.rec.permits:
            for p in self.people.values():
                if _clean_name(pm.holder).lower() == _clean_name(p.name).lower():
                    p.permits.append(pm)
                    p.identity_sources.append(("parking permit", pm.source, pm.plate))
        # cards: cardholder = handle
        for e in self.rec.by_kind("card"):
            p = self.people.get(e.actor or "")
            if p is not None and e.attrs.get("last4"):
                if e.attrs["last4"] not in p.card_last4:
                    p.identity_sources.append(("corporate card", e.source, e.attrs["last4"]))
                p.card_last4.add(e.attrs["last4"])
        # calendars: file owner or X-WR-CALNAME
        for e in self.rec.by_kind("calendar"):
            p = self.people.get(e.actor or "")
            if p is not None and not p.calendar:
                p.calendar = e.source.split(":")[0]
        # interviews
        for iv in self.rec.interviews:
            for p in self.people.values():
                if p.name and _clean_name(p.name).lower() in _clean_name(iv.interviewee).lower():
                    p.interviews.append(iv)
                    p.identity_sources.append(("interview", f"{iv.path}:{iv.interviewee_line}", iv.interviewee))
        # aliases for mention detection
        first_counts = Counter(_clean_name(p.name).split()[0].lower() for p in self.people.values() if p.name)
        last_counts = Counter(_clean_name(p.name).split()[-1].lower() for p in self.people.values() if p.name)
        for p in self.people.values():
            if not p.name:
                continue
            parts = _clean_name(p.name).split()
            p.aliases = {_clean_name(p.name).lower()}
            if p.handle:
                p.aliases.add(p.handle.lower())
            if first_counts[parts[0].lower()] == 1:
                p.aliases.add(parts[0].lower())
            if last_counts[parts[-1].lower()] == 1:
                p.aliases.add(parts[-1].lower())
        # offices: an interviewee answering a question about their office with a room id
        room_rx = re.compile(r"\b(\d[A-Z]-\d{1,3})\b")
        for p in self.people.values():
            for iv in p.interviews:
                for k, ln in enumerate(iv.lines):
                    if ln["speaker"] == "NA" or not room_rx.search(ln["text"]):
                        continue
                    prev = iv.lines[k - 1]["text"] if k else ""
                    if re.search(r"\boffice\b|\bdesk\b|\bsit\b", prev, re.I) or re.search(r"\bmy office\b", ln["text"], re.I):
                        room = room_rx.search(ln["text"]).group(1)
                        p.offices.append((room, f"{iv.path}:{ln['line']}", room_rx.search(ln["text"]).group(0)))

    def person(self, handle_or_name: str | None) -> Person | None:
        if not handle_or_name:
            return None
        if handle_or_name in self.people:
            return self.people[handle_or_name]
        low = handle_or_name.lower()
        for p in self.people.values():
            if low in p.aliases or (p.email and low == p.email.lower()):
                return p
        return None

    def mentions(self, text: str, suspects_only: bool = False) -> list[Person]:
        found = []
        low = text.lower()
        for p in self.people.values():
            if suspects_only and not p.suspect:
                continue
            if any(re.search(rf"(?<![\w.]){re.escape(a)}(?![\w])", low) for a in p.aliases):
                found.append(p)
        return found

    def suspect_by_name(self, name: str) -> Person | None:
        for p in self.suspects:
            if p.name.lower() == name.lower() or (p.handle and p.handle == name):
                return p
        return None

    # ------------------------------------------------------------------ frame
    def _derive_frame(self) -> None:
        self._derive_site()
        self._derive_blackout()
        self._derive_operation()
        self._derive_withheld()
        self._derive_secret()
        self._derive_receiver()
        self._derive_investigator()

    def fact(self, key: str):
        f = self.facts.get(key)
        return f.value if f else None

    def _derive_site(self) -> None:
        cities = Counter(e.attrs.get("city", "") for e in self.rec.by_kind("card") if e.attrs.get("city"))
        if cities:
            city, n = cities.most_common(1)[0]
            ex = next(e for e in self.rec.by_kind("card") if e.attrs.get("city") == city)
            self.facts["site_city"] = Fact(city, ex.source, city,
                                           f"most frequent card merchant city ({n} of {sum(cities.values())} transactions)")

    def _derive_blackout(self) -> None:
        rx = re.compile(
            r"(?:(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+)?(\d{1,2})(?:\.(\d{1,2})\.?|\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*)(?:(\d{4}))?\s*,?\s*(\d{1,2}):(\d{2})"
            r"\s*(?:\*\*)?\s*(?:→|->|to|bis|–|-)\s*(?:\*\*)?\s*"
            r"(?:(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+)?(\d{1,2})(?:\.(\d{1,2})\.?|\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*)(?:(\d{4}))?\s*,?\s*(\d{1,2}):(\d{2})",
            re.I,
        )
        votes: Counter = Counter()
        cites: dict = {}
        year_hint = Counter(e.t.year for e in self.rec.events if e.t)
        default_year = year_hint.most_common(1)[0][0] if year_hint else datetime.now().year
        for doc in self.corpus.text_docs():
            for i, ln in enumerate(doc.lines, 1):
                if not re.search(r"audit|collector|logging|window|log", ln, re.I):
                    continue
                m = rx.search(ln)
                if not m:
                    continue
                g = m.groups()
                try:
                    a = _mkdate(g[1], g[2], g[3], g[4], g[5], g[6], default_year)
                    b = _mkdate(g[8], g[9], g[10], g[11], g[12], g[13], default_year)
                except Exception:
                    continue
                if not (timedelta(0) < b - a < timedelta(days=3)):
                    continue
                key = (a, b)
                votes[key] += 1
                cites.setdefault(key, (f"{doc.path}:{i}", m.group(0)))
        if votes:
            (a, b), n = votes.most_common(1)[0]
            src, q = cites[(a, b)]
            self.facts["blackout"] = Fact((a.replace(tzinfo=self.zone), b.replace(tzinfo=self.zone)), src, q,
                                          f"stated in {n} place(s)")
        else:
            self.warnings.append("could not find the blackout window in the sources")

    def _derive_operation(self) -> None:
        """Times from a technical report that declares its own time base."""
        blackout = self.fact("blackout")
        for path, doc in self.corpus.docs.items():
            if doc.kind != "pdf":
                continue
            for page, text in doc.pages.items():
                mdecl = re.search(r"times? in this (?:report|document) (?:are|is) (UTC|local)", text, re.I)
                if not mdecl:
                    continue
                base_utc = mdecl.group(1).upper() == "UTC"
                decl_line = next(l for l in text.splitlines() if mdecl.group(0).split()[0] in l)
                self.facts["operation_time_basis"] = Fact(mdecl.group(1), f"{path}:{page}", mdecl.group(0).strip(),
                                                          "report declares its own time base")
                date_rx = re.compile(
                    r"(?:\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+(\d{1,2})\.(\d{1,2})\.?(\d{4})?)"
                    r"|(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
                default_year = blackout[0].year if blackout else datetime.now().year
                points = []
                first_day = None
                for pg, ptxt in sorted(doc.pages.items()):
                    cur_date = None
                    undated: list[tuple[int, int, str, bool]] = []
                    for ln in ptxt.splitlines():
                        md = date_rx.search(ln)
                        if md:
                            g = md.groups()
                            d_, m_, y_ = (g[0], g[1], g[2]) if g[0] else (g[3], g[4], g[5])
                            try:
                                cur_date = datetime(int(y_) if y_ else default_year, int(m_), int(d_)).date()
                            except ValueError:
                                pass
                        for mt in re.finditer(r"(~)?(?<![\d.])(\d{1,2}):(\d{2})\b", ln):
                            h, mi = int(mt.group(2)), int(mt.group(3))
                            if cur_date is None:
                                undated.append((h, mi, ln.strip(), bool(mt.group(1))))
                                continue
                            naive = datetime(cur_date.year, cur_date.month, cur_date.day, h, mi)
                            dt = (naive.replace(tzinfo=UTC) if base_utc else naive.replace(tzinfo=self.zone)).astimezone(self.zone)
                            if blackout and not (blackout[0] - timedelta(hours=6) <= dt <= blackout[1] + timedelta(hours=18)):
                                continue
                            first_day = first_day or cur_date
                            points.append((dt, f"{path}:{pg}", ln.strip(), bool(mt.group(1))))
                    # an undated timeline (annex): start on the first dated day, roll over midnight
                    if undated and first_day:
                        day = first_day
                        prev = None
                        for h, mi, ln, approx in undated:
                            if prev is not None and (h, mi) < prev and not approx:
                                day = day + timedelta(days=1)
                            naive = datetime(day.year, day.month, day.day, h, mi)
                            dt = (naive.replace(tzinfo=UTC) if base_utc else naive.replace(tzinfo=self.zone)).astimezone(self.zone)
                            if approx and prev is not None and (h, mi) < prev:
                                dt += timedelta(days=1)
                            if not approx:
                                prev = (h, mi)
                            points.append((dt, f"{path}:{pg}", ln, approx))
                if not points:
                    continue
                fixed = list(points)
                exact = [p for p in fixed if not p[3]]
                if not exact:
                    continue
                start = min(exact, key=lambda p: p[0])
                end = max(exact, key=lambda p: p[0])
                self.facts["operation"] = Fact((start[0], end[0]), start[1], _first_clause(start[2]),
                                               f"converted from {mdecl.group(1)}; ends: {end[2]}")
                self.facts["operation_end"] = Fact(end[0], end[1], _first_clause(end[2]), "")
                self.operation_points = [
                    {"t": p[0].isoformat(), "source": p[1], "text": p[2], "approx": p[3]} for p in sorted(set(fixed))
                ]
                m = re.search(r"[^.\n]*(?:console|local session|on the [a-z ]+floor)[^.\n]*", text, re.I)
                full = " ".join(t for _, t in sorted(doc.pages.items()))
                m = m or re.search(r"[^.]*(?:console|local session)[^.]*", full, re.I)
                if m:
                    line = next((l for l in text.splitlines() if l.strip() and l.strip() in m.group(0)), m.group(0).strip())
                    self.facts["presence_required"] = Fact(True, f"{path}:{page}", line.strip(),
                                                           "the operator worked at a local console on site")
                return
        self.warnings.append("no technical report with a declared time base; operation window = blackout window")

    def _derive_withheld(self) -> None:
        for e in self.rec.by_kind("notebook"):
            m = re.search(r"withhold[^.:]*[.:!]?\**\s*(.*)", e.text, re.I)
            if not m:
                continue
            first = re.split(r"(?<=[.!])\s", m.group(1).strip("* "))[0]
            labels = [x.strip(" *.") for x in first.split(",") if x.strip(" *.")]
            concepts = [c for c in (lexicon.concept_for_label(l) for l in labels) if c]
            if concepts:
                self.facts["withheld"] = Fact(sorted(set(concepts)), e.source, _raw(self.corpus, e.source, "WITHHOLD"),
                                              f"withheld from {e.t.date().isoformat() if e.t else '?'}; labels: {labels}")
                self.facts["withheld_since"] = Fact(e.t, e.source, e.t_raw, "")
                return
        # fallback: a report marked confidential — use every concept it mentions
        for path, doc in self.corpus.docs.items():
            if doc.kind == "pdf":
                txt = " ".join(doc.pages.values())
                if re.search(r"confidential|do not disclose", txt, re.I):
                    hits = lexicon.concept_hits(txt)
                    if hits:
                        self.facts["withheld"] = Fact(sorted(hits), f"{path}:1", "", "confidential report")
                        return

    def _derive_secret(self) -> None:
        """What the operator had to know (e.g. which items were real and which were planted fakes)."""
        for path, doc in self.corpus.docs.items():
            if doc.kind != "pdf":
                continue
            for page, txt in doc.pages.items():
                for ln in txt.splitlines():
                    m = re.search(r"\bno (\w+) (?:bundle|file|artifact|checkpoint)s? .*?(?:was|were) (?:read|opened|touched)", ln, re.I)
                    if m:
                        term = m.group(1).lower()
                        self.facts["secret"] = Fact(term, f"{path}:{page}", ln.strip(),
                                                    f"the operator avoided every '{term}' item: they knew which were real")
                        self.secret_patterns = [
                            rf"\b{term}s?\b",
                            r"which (?:artifacts|bundles|checkpoints|ones) (?:are|were) real",
                            rf"real ?/ ?{term}",
                        ]
                        return
        self.secret_patterns = []

    def _derive_receiver(self) -> None:
        texts = [(n, t) for n, t in self.briefs.items()]
        for e in self.rec.by_kind("notebook"):
            texts.append((e.source, e.text))
        votes: Counter = Counter()
        where: dict = {}
        # the victim's own name (from its e-mail domain) is never the receiver
        own_orgs = {u.email.split("@")[-1].split(".")[0].split("-")[0].lower() for u in self.rec.users.values() if u.email}
        rx = re.compile(r"\b([A-Z][a-z]{3,})(?:'s| Labs?)?\s+(?:preprint|paper|model|published)|rival (?:lab|company)s?,?\s+([A-Z][a-z]{3,})")
        for src, t in texts:
            for m in rx.finditer(t):
                org = m.group(1) or m.group(2)
                if org.lower() in {"their", "this", "the"} | own_orgs:
                    continue
                votes[org] += 1
                where.setdefault(org, (src, m.group(0)))
        if votes:
            org = votes.most_common(1)[0][0]
            src, q = where[org]
            if not re.search(r":\d+$", src):  # brief file: find a bundle line instead
                hit = self.corpus.search(rf"\b{org}\b.*\b(preprint|paper|model)\b", limit=1)
                if hit:
                    src, q = hit[0]["source"], org
            self.facts["receiver"] = Fact(org, src, q, "party whose model showed the watermark")

    def _derive_investigator(self) -> None:
        for iv in self.rec.interviews:
            doc = self.corpus.get(iv.path)
            for i, ln in enumerate(doc.lines[:10], 1):
                m = re.match(r"Interviewer:\s*(.+?)\s*\((\w+)\)", ln)
                if m:
                    self.facts["investigator"] = Fact(m.group(1), f"{iv.path}:{i}", m.group(0), f"tag {m.group(2)}")
                    self.interviewer_tag = m.group(2)
                    return
        self.interviewer_tag = "NA"

    # --------------------------------------------------------------- windows
    @property
    def op_window(self) -> tuple[datetime, datetime] | None:
        return self.fact("operation") or self.fact("blackout")

    @property
    def blackout(self) -> tuple[datetime, datetime] | None:
        return self.fact("blackout")

    def summary(self) -> dict:
        return {
            "zone": str(self.zone),
            "facts": {k: v.to_dict() for k, v in self.facts.items()},
            "suspects": [p.to_dict() for p in self.suspects],
            "operation_points": getattr(self, "operation_points", []),
            "warnings": self.warnings,
        }


def _clean_name(n: str) -> str:
    n = re.sub(r"^(Dr\.?|Prof\.?|Mr\.?|Ms\.?|Mrs\.?)\s+", "", n.strip())
    return n.split(",")[0].strip()


def _mkdate(day, month_num, month_name, year, hh, mm, default_year) -> datetime:
    if month_num:
        month = int(month_num)
    else:
        month = lexicon.MONTHS[month_name[:3].lower()]
    y = int(year) if year else default_year
    return datetime(y, month, int(day), int(hh), int(mm))


def _first_clause(s: str) -> str:
    return s.strip()


def _raw(corpus: Corpus, source: str, needle: str) -> str:
    path, line = source.rsplit(":", 1)
    ln = corpus.get(path).lines[int(line) - 1]
    from .util import best_span
    return best_span(ln, needle)
