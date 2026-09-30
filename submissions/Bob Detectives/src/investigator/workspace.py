"""The agent's workspace: everything the agent decides, kept across runs.

  settings.json        mode: "agent" (only reviewed/agent findings count) or "autopilot"
  ids.json             stable IDs (F-/S-###, I-/R-/P-/M-##) — an ID never changes once assigned
  reviews.json         the agent's decision on each proposal / inconsistency / challenge
  steps.json           playbook progress: status and the agent's summary per step
  verdict_drafts.json  the agent's verdict + reasoning per suspect, confidence proposal
  journal.jsonl        every agent action, in order (the trace shown in the UI)

Several processes write here at once (the orchestrator's pipeline refreshes, Bob's CLI calls,
the UI, the other agent sharing IDs). Every change therefore takes a file lock, re-reads the
file, changes only its own entry and writes atomically — nobody writes back a stale snapshot.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_thread_lock = threading.RLock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Workspace:
    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings = self._load("settings.json", {"mode": "agent"})
        self.ids = self._load("ids.json", {})
        self.reviews = self._load("reviews.json", {})
        self.steps = self._load("steps.json", {})
        self.drafts = self._load("verdict_drafts.json", {"suspects": {}, "confidence": None})

    # ------------------------------------------------------------------ io
    def _load(self, name: str, default):
        p = self.dir / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return json.loads(json.dumps(default))
        return json.loads(json.dumps(default))

    def _write(self, name: str, data) -> None:
        tmp = self.dir / f".{name}.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.dir / name)

    @contextmanager
    def _locked(self):
        with _thread_lock:
            with open(self.dir / ".lock", "w") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _update(self, name: str, default, change):
        """Lock, re-read, apply `change(data)`, write. Returns the fresh data."""
        with self._locked():
            data = self._load(name, default)
            change(data)
            self._write(name, data)
            return data

    def save(self) -> None:
        """Kept for compatibility: every change is already persisted when it is made."""

    # ----------------------------------------------------------------- ids
    def assign(self, prefix: str, key: str, width: int) -> str:
        return self.assign_all([(prefix, key, width)])[0]

    def assign_all(self, items: list[tuple[str, str, int]]) -> list[str]:
        """Assign IDs for many keys at once; existing IDs (from any process) are kept."""
        out: list[str] = []

        def change(ids):
            for prefix, key, width in items:
                reg = ids.setdefault(prefix, {})
                if key not in reg:
                    used = {int(v.split("-")[1]) for v in reg.values() if "-" in v and v.split("-")[1].isdigit()}
                    n = max(used, default=0) + 1
                    reg[key] = f"{prefix}-{n:0{width}d}"
                out.append(reg[key])
        self.ids = self._update("ids.json", {}, change)
        return out

    def key_for(self, ident: str) -> str | None:
        """F-012 / I-03 / R-02 / a raw key → key."""
        self.ids = self._load("ids.json", {})
        prefix = ident.split("-")[0] if "-" in ident else None
        for p, reg in self.ids.items():
            if prefix and p != prefix:
                continue
            for k, v in reg.items():
                if v == ident:
                    return k
        return ident if any(ident in reg for reg in self.ids.values()) else None

    # ------------------------------------------------------------- reviews
    @property
    def mode(self) -> str:
        return self.settings.get("mode", "agent")

    def set_mode(self, mode: str) -> None:
        self.settings = self._update("settings.json", {"mode": "agent"}, lambda d: d.update(mode=mode))

    def review(self, key: str, decision: str, note: str, by: str, **extra) -> dict:
        r = {"decision": decision, "note": note, "by": by, "at": _now(), **{k: v for k, v in extra.items() if v is not None}}
        self.reviews = self._update("reviews.json", {}, lambda d: d.__setitem__(key, r))
        self.log(by, "review", {"key": key, **r})
        return r

    # --------------------------------------------------------------- steps
    def step_state(self, step_id: str) -> dict:
        return self.steps.get(step_id, {"status": "pending"})

    def set_step(self, step_id: str, status: str, summary: str | None = None, by: str = "agent") -> None:
        def change(steps):
            s = steps.setdefault(step_id, {"status": "pending"})
            s["status"] = status
            s["updated"] = _now()
            if summary is not None:
                s["summary"] = summary
        self.steps = self._update("steps.json", {}, change)
        self.log(by, "step", {"step": step_id, "status": status, "summary": summary})

    # -------------------------------------------------------------- drafts
    def draft_verdict(self, suspect: str, verdict: str, reasoning: str, cites: list[str], by: str) -> None:
        entry = {"verdict": verdict, "reasoning": reasoning, "cites": cites, "by": by, "at": _now()}
        self.drafts = self._update("verdict_drafts.json", {"suspects": {}, "confidence": None},
                                   lambda d: d.setdefault("suspects", {}).__setitem__(suspect, entry))
        self.log(by, "verdict", {"suspect": suspect, "verdict": verdict, "reasoning": reasoning, "cites": cites})

    def propose_confidence(self, value: float, why: str, by: str) -> None:
        entry = {"value": value, "why": why, "by": by, "at": _now()}
        self.drafts = self._update("verdict_drafts.json", {"suspects": {}, "confidence": None},
                                   lambda d: d.__setitem__("confidence", entry))
        self.log(by, "confidence", {"value": value, "why": why})

    # ------------------------------------------------------------- journal
    def log(self, actor: str, action: str, data: dict) -> None:
        line = json.dumps({"at": _now(), "actor": actor, "action": action, **data}, ensure_ascii=False) + "\n"
        with self._locked():
            with (self.dir / "journal.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(line)

    def journal(self, limit: int = 500) -> list[dict]:
        p = self.dir / "journal.jsonl"
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for x in lines:
            try:
                out.append(json.loads(x))
            except Exception:
                pass
        return out


def actor() -> str:
    """Who is calling the CLI: set by the orchestrator (INVESTIGATE_ACTOR=bob) or --by."""
    return os.environ.get("INVESTIGATE_ACTOR", "human")
