"""Findings, evidence and issues — the unit of reasoning.

Classification scale (same as the manual argumentation):
  INCRIMINATES          🔴  raises suspicion, consistent with guilt
  WEAKLY_INCRIMINATES   🟡  suspicious but explicable innocently
  EXONERATES            🟢  lowers suspicion, inconsistent with guilt
  PROVES_INNOCENCE      ⚪  physically impossible to be the operator
  NEUTRAL               ·   context, no weight
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .util import stable_key

CLASSES = {
    "INCRIMINATES": {"icon": "🔴", "sign": 1.0, "label": "incriminates"},
    "WEAKLY_INCRIMINATES": {"icon": "🟡", "sign": 0.5, "label": "weakly incriminates"},
    "EXONERATES": {"icon": "🟢", "sign": -1.0, "label": "exonerates"},
    "PROVES_INNOCENCE": {"icon": "⚪", "sign": -1.0, "label": "proves innocence"},
    "NEUTRAL": {"icon": "·", "sign": 0.0, "label": "neutral"},
}

CONSTRAINTS = {
    "presence": "Where was the person during the operation window?",
    "knowledge": "Could the person know the secret the operator needed?",
    "echo": "Did the person know withheld details — and is there an innocent route?",
    "statement": "Does the person's own account survive the paperwork?",
    "link": "Link to the party that received the stolen asset",
    "lead": "Why the person was on the list in the first place",
    "capability": "Could the person physically/technically have done it?",
}

RELIABILITY = {
    "bank": 0.95,         # card issuer feed
    "machine": 0.85,      # barrier log, forensic journal, system timestamps
    "document": 0.8,      # e-mail, tickets, notes written at the time
    "chat": 0.65,         # contemporaneous chat, self-authored
    "witness": 0.55,      # third-party statement
    "self": 0.35,         # suspect's own later account (interview, expense narrative)
    "ocr": 0.5,           # machine-read image text, unconfirmed
    "derived": 0.7,       # computed from several sources
    "absence": 0.3,       # inferred from the lack of a record
}


@dataclass
class Evidence:
    source: str
    quote: str
    note: str = ""
    status: str = "unchecked"   # verified | whitespace | ocr | not-found | wrong-line | bad-source
    ocr: bool = False

    @property
    def usable(self) -> bool:
        return self.status in ("verified", "whitespace")


@dataclass
class Finding:
    suspect: str | None           # person key (handle) or None for case-level
    analyzer: str
    constraint: str
    cls: str
    title: str
    claim: str
    evidence: list[Evidence] = field(default_factory=list)
    reasoning: str = ""
    weight: float = 0.3
    reliability: str = "derived"
    caveats: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)   # issue ids / fixes this relies on
    explains: str | None = None    # key of the suspicion this finding explains away
    status: str = "active"         # active | downgraded | withdrawn | proposed (awaiting the agent's review)
    provenance: str = "deterministic"
    stage: str = "analyse"
    id: str = ""
    history: list[str] = field(default_factory=list)
    review: dict | None = None     # the agent's decision on this proposal
    meta: dict = field(default_factory=dict)   # e.g. the Security Guard's severity/state/subject

    @property
    def key(self) -> str:
        return stable_key(self.suspect, self.analyzer, self.title, *(e.source for e in self.evidence[:2]))

    @property
    def icon(self) -> str:
        return CLASSES[self.cls]["icon"]

    @property
    def counts(self) -> bool:
        return self.status not in ("withdrawn", "proposed")

    @property
    def score(self) -> float:
        if self.status == "withdrawn":
            return 0.0
        return CLASSES[self.cls]["sign"] * self.weight * RELIABILITY.get(self.reliability, 0.6)

    def downgrade(self, new_cls: str, why: str, weight: float | None = None) -> None:
        self.history.append(f"{self.cls} → {new_cls}: {why}")
        self.cls = new_cls
        if weight is not None:
            self.weight = weight
        self.status = "downgraded"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        d["icon"] = self.icon
        d["score"] = round(self.score, 3)
        return d


@dataclass
class Issue:
    """An inconsistency (sweep) or a weakness (adversarial review)."""
    kind: str                     # sweep | adversarial
    category: str
    title: str
    observation: str
    severity: str = "medium"      # high | medium | low
    evidence: list[Evidence] = field(default_factory=list)
    resolution: str = "open"      # open | fixed | explained | accepted | needs-human
    fix: str = ""
    effect: str = ""
    affects: list[str] = field(default_factory=list)   # person keys
    id: str = ""
    review: dict | None = None     # the agent's decision on this item

    @property
    def key(self) -> str:
        return stable_key(self.kind, self.category, self.title)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d


class FindingStore:
    def __init__(self):
        self.findings: list[Finding] = []
        self.issues: list[Issue] = []

    def add(self, f: Finding) -> Finding:
        for g in self.findings:
            if g.key == f.key:
                return g
        self.findings.append(f)
        return f

    def issue(self, i: Issue) -> Issue:
        for g in self.issues:
            if g.key == i.key:
                return g
        self.issues.append(i)
        return i

    include_proposed = False    # baseline scoring counts unreviewed proposals too

    def for_suspect(self, key: str | None, active_only: bool = True) -> list[Finding]:
        out = []
        for f in self.findings:
            if f.suspect != key:
                continue
            if active_only and f.status == "withdrawn":
                continue
            if active_only and f.status == "proposed" and not self.include_proposed:
                continue
            out.append(f)
        return out

    ISSUE_PREFIX = {"sweep": "I", "adversarial": "R", "rootcause": "P", "remediation": "M"}

    def number(self, ws=None, finding_prefix: str = "F") -> None:
        """IDs are stable across runs when a workspace is given (the agent refers to them).
        Investigator findings are F-###, Security Guard risks S-###; issues I-/R-/P-/M-."""
        order = {"sweep": 0, "analyse": 1, "bob": 2, "human": 3, "adversarial": 4}
        sev = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        self.findings.sort(key=lambda f: (order.get(f.stage, 9), sev.get(f.meta.get("severity"), 9), f.suspect or "",
                                          f.constraint, -abs(f.score)))
        items = [(finding_prefix, f.key, 3, f) for f in self.findings]
        for kind, prefix in self.ISSUE_PREFIX.items():
            items += [(prefix, s.key, 2, s) for s in self.issues if s.kind == kind]
        if ws:
            ids = ws.assign_all([(p, k, w) for p, k, w, _ in items])   # one locked update
            for (_, _, _, obj), ident in zip(items, ids):
                obj.id = ident
        else:
            counters: dict = {}
            for p, _, w, obj in items:
                counters[p] = counters.get(p, 0) + 1
                obj.id = f"{p}-{counters[p]:0{w}d}"

    def by_id(self, ident: str):
        for f in self.findings:
            if f.id == ident or f.key == ident:
                return f
        for i in self.issues:
            if i.id == ident or i.key == ident:
                return i
        return None
