"""The investigation context shared by all stages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .case import Case, Person
from .corpus import Corpus
from .findings import Evidence, Finding, FindingStore, Issue
from .records import Event, Records
from .tasks import Task, TaskBook
from .util import best_span
from .workspace import Workspace


@dataclass
class Paths:
    repo: Path
    bundle: Path
    template: Path | None
    briefs: list[Path]
    workdir: Path

    @property
    def state(self) -> Path:
        return self.workdir / "state"

    @property
    def output(self) -> Path:
        return self.workdir / "output"

    @property
    def context_dir(self) -> Path:
        return self.output / "context"


@dataclass
class Leak:
    """A moment when withheld facts were exposed outside the need-to-know circle."""
    t: datetime
    room: str | None
    channel: str
    evidence: list[Evidence]
    audience: list[dict] = field(default_factory=list)   # {person, why, evidence}


class Investigation:
    def __init__(self, paths: Paths, ocr: bool = True, log=None, suspects: bool = True, agent: str = "investigator"):
        self.agent = agent
        self.paths = paths
        self.log = log or (lambda msg: None)
        self.corpus = Corpus(paths.bundle, cache_dir=paths.state / "ocr_cache", ocr=ocr)
        self.rec = Records(self.corpus)
        self.case = Case(self.corpus, self.rec, paths.template if suspects else None, paths.briefs,
                         require_suspects=suspects)
        self.store = FindingStore()
        self.tasks = TaskBook(paths.state)
        self.ws = Workspace(paths.state)
        self.hints: list[dict] = []
        self.clock_fixes: dict[str, dict] = {}
        self.plate_resolutions: dict[str, dict] = {}   # garage event source -> {plate, why}
        self.leaks: list[Leak] = []
        self.sightings: list[dict] = []
        self.results: dict = {}                       # argue/verdict outputs
        self.stage_log: list[dict] = []

    # ------------------------------------------------------------ evidence
    def evidence(self, source: str, needle: str | None = None, note: str = "", quote: str | None = None) -> Evidence:
        """Build an Evidence item whose quote is an exact span of the cited unit, then verify it."""
        doc, a, _ = self.corpus.resolve(source)
        ocr = bool(doc and doc.is_ocr)
        if quote is None:
            if doc is not None and doc.kind == "text" and a:
                quote = best_span(doc.lines[a - 1], needle)
            elif doc is not None and doc.kind == "xlsx" and a:
                cells = [c for c in doc.rows.get(a, []) if c]
                quote = next((c for c in cells if needle and needle.lower() in c.lower()), cells[0] if cells else "")
            elif doc is not None and doc.kind in ("pdf", "image"):
                text = doc.pages.get(a, "") if doc.kind == "pdf" else doc.ocr_text
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                quote = next((l for l in lines if needle and needle.lower() in l.lower()), lines[0] if lines else "")
            else:
                quote = ""
        ev = Evidence(source=source, quote=quote, note=note, ocr=ocr)
        ev.status = self.corpus.verify(source, quote)["status"]
        return ev

    def ev_event(self, e: Event, needle: str | None = None, note: str = "") -> Evidence:
        return self.evidence(e.source, needle, note)

    # ------------------------------------------------------------ helpers
    def add(self, f: Finding) -> Finding:
        return self.store.add(f)

    def issue(self, i: Issue) -> Issue:
        return self.store.issue(i)

    def task(self, t: Task) -> Task:
        return self.tasks.add(t)

    def person(self, key: str | None) -> Person | None:
        return self.case.person(key)

    @property
    def op(self) -> tuple[datetime, datetime]:
        w = self.case.op_window
        if not w:
            raise SystemExit("no incident window could be derived")
        return w

    @property
    def site(self) -> str:
        return self.case.fact("site_city") or ""

    def is_site(self, city: str) -> bool:
        s = self.site.lower()
        c = (city or "").lower()
        return bool(s) and (c == s or c.startswith(s) or s.startswith(c)) and bool(c)

    def events_for(self, person: Person, kinds: tuple[str, ...], start: datetime | None = None,
                   end: datetime | None = None) -> list[Event]:
        keys = {person.handle, *person.plates} - {None}
        out = []
        for e in self.rec.events:
            if e.kind not in kinds or e.t is None:
                continue
            if start and e.t < start or end and e.t > end:
                continue
            if e.actor in keys or (e.kind == "garage" and self.resolved_plate(e) in keys):
                out.append(e)
        return out

    def resolved_plate(self, e: Event) -> str:
        r = self.plate_resolutions.get(e.source)
        return r["plate"] if r else e.attrs.get("plate", e.actor or "")

    def stage(self, name: str, detail: str) -> None:
        self.stage_log.append({"stage": name, "detail": detail, "at": datetime.now().isoformat(timespec="seconds")})
        self.log(f"[{name}] {detail}")


def near(t: datetime, a: datetime, b: datetime, margin_min: int = 0) -> bool:
    return a - timedelta(minutes=margin_min) <= t <= b + timedelta(minutes=margin_min)


def room_ids(text: str) -> list[str]:
    return re.findall(r"\b(\d[A-Z]-\d{1,3})\b", text)
