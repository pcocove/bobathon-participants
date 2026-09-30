"""Tasks for the agent (mechanical, source-verifiable) and the human (judgement calls).

Resolutions are persisted in the state directory keyed by a stable task key, so a
decision made in the UI or CLI survives re-runs and feeds back into the pipeline.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .util import stable_key


@dataclass
class Task:
    kind: str                  # human | agent
    topic: str                 # clock | plate | ocr | travel | echo | lead | quote | calibration | ...
    title: str
    why: str                   # why this needs a human / what the agent must do
    question: str
    read: list[dict] = field(default_factory=list)   # [{source, quote, note}]
    options: list[str] = field(default_factory=list)
    effect: dict = field(default_factory=dict)        # decision -> what the pipeline does
    subject: str = ""          # stable subject string (plate, finding key, ...)
    suspect: str | None = None
    priority: int = 2          # 1 = blocks verdict, 2 = affects confidence, 3 = nice to have
    id: str = ""
    resolution: dict | None = None

    @property
    def key(self) -> str:
        return stable_key(self.kind, self.topic, self.subject or self.title)

    @property
    def status(self) -> str:
        return "resolved" if self.resolution else "open"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        d["status"] = self.status
        return d


class TaskBook:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / "resolutions.json"
        self.tasks: list[Task] = []
        self.resolutions: dict[str, dict] = {}
        if self.path.exists():
            self.resolutions = json.loads(self.path.read_text(encoding="utf-8"))

    def add(self, t: Task) -> Task:
        for g in self.tasks:
            if g.key == t.key:
                return g
        t.resolution = self.resolutions.get(t.key)
        self.tasks.append(t)
        return t

    def decision(self, kind: str, topic: str, subject: str) -> dict | None:
        """Look up a stored resolution before the task is (re)created."""
        return self.resolutions.get(stable_key(kind, topic, subject))

    def resolve(self, key_or_id: str, decision: str, note: str = "", by: str = "human",
                extra: dict | None = None) -> Task:
        t = self.get(key_or_id)
        if t is None:
            raise KeyError(key_or_id)
        if t.options and decision not in t.options:
            raise ValueError(f"decision must be one of {t.options}")
        t.resolution = {"decision": decision, "note": note, "by": by,
                        "at": datetime.now().isoformat(timespec="seconds"), **(extra or {})}
        self._update(lambda d: d.__setitem__(t.key, t.resolution))
        return t

    def reopen(self, key_or_id: str) -> Task:
        t = self.get(key_or_id)
        if t is None:
            raise KeyError(key_or_id)
        t.resolution = None
        self._update(lambda d: d.pop(t.key, None))
        return t

    def _update(self, change) -> None:
        """Lock, re-read, change one entry, write — never write back a stale snapshot."""
        from .workspace import Workspace
        ws = Workspace.__new__(Workspace)
        ws.dir = self.state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.resolutions = ws._update("resolutions.json", {}, change)

    def get(self, key_or_id: str) -> Task | None:
        for t in self.tasks:
            if t.key == key_or_id or t.id == key_or_id:
                return t
        return None

    def save(self) -> None:
        """Kept for compatibility: resolutions are persisted when they are made."""

    def number(self) -> None:
        # IDs must not change when a task is resolved: order by content only
        self.tasks.sort(key=lambda t: (t.kind, t.priority, t.topic, t.subject or t.title))
        h = a = 0
        for t in self.tasks:
            if t.kind == "human":
                h += 1
                t.id = f"H-{h:02d}"
            else:
                a += 1
                t.id = f"A-{a:02d}"

    def open(self, kind: str | None = None) -> list[Task]:
        return [t for t in self.tasks if t.status == "open" and (kind is None or t.kind == kind)]
