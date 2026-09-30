"""The orchestrator: Bob works the playbook, step by step, and can go deeper on anything.

For each step it opens a Bob session in Investigator mode, gives Bob the step's goal and
instructions, lets Bob drive the CLI, then re-runs the pipeline and checks the step's
definition of done. Anything Bob skipped is sent back to him (up to N nudges). Every
message, command, output and permission decision lands in the session log for the UI.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from . import pipeline, playbook, profiles
from .acp import AcpError, BobSession, explain
from .engine import Paths
from .workspace import Workspace

DEPTH = {
    "quick": "Review every proposal, but only dig where a proposal looks wrong. Keep it short.",
    "normal": "Review every proposal and dig into each suspicion until you find the record that confirms or explains it.",
    "deep": "Review every proposal, dig into every suspicion, and actively hunt for records the tools missed: "
            "at least five searches in different sources per suspect. Challenge your own conclusions.",
}


def _state(paths: Paths) -> dict:
    return json.loads((paths.output / "investigation.json").read_text(encoding="utf-8"))


def _refresh(paths: Paths, log, profile: str = "investigator") -> dict:
    if profile == "guard":
        from . import guard
        guard.run(paths, log=lambda m: None)
    else:
        pipeline.run(paths, log=lambda m: None)
    return _state(paths)


def _pb(profile: str):
    if profile == "guard":
        from . import guard_playbook
        return guard_playbook
    return playbook


def frame_brief(state: dict) -> str:
    """The derived frame, so every fresh session starts from the same facts (each with its source)."""
    if state.get("agent") == "guard":
        p = state.get("posture") or {}
        top = "\n".join(f"  {t['id']} {t['severity']}/{t['state']} {t['title'][:90]}" for t in p.get("top", [])[:6])
        return (f"- data as of {p.get('as_of', '?')[:10] if p.get('as_of') else '?'}; {p.get('open')} open risks of {p.get('risks')} "
                f"({p.get('by_severity')}); {p.get('rootcauses')} root causes; {p.get('remediations')} remediation plans\n"
                f"- exposed by the incident under investigation: {', '.join(p.get('incident_linked') or []) or 'none known'}\n"
                f"- most urgent:\n{top}")
    facts = state["case"]["facts"]
    out = []
    for key, label in (("operation", "operation window (the copy itself; presence is judged against this)"),
                       ("blackout", "logging blackout (wider than the operation)"),
                       ("presence_required", "operator had to be on site"), ("site_city", "site"),
                       ("withheld", "facts the investigator withheld before the interviews"),
                       ("secret", "the operator avoided every item of this kind"), ("receiver", "receiving party")):
        f = facts.get(key)
        if not f:
            continue
        v = f["value"]
        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and "T" in v[0]:
            v = f"{v[0][:16].replace('T', ' ')} → {v[1][:16].replace('T', ' ')} local"
        out.append(f"- {label}: {v}  ({f['source']})")
    return "\n".join(out)


def step_prompt(step: playbook.Step, depth: str, missing: list[str], state: dict | None = None,
                profile: str = "investigator") -> str:
    prof = profiles.get(profile)
    todo = ("\nStill open from the last check:\n" + "\n".join(f"- {m}" for m in missing[:30])) if missing else ""
    label = "SECURITY POSTURE" if profile == "guard" else "CASE FRAME"
    frame = f"\n{label} (derived by the tools; check it if it matters):\n{frame_brief(state)}\n" if state else ""
    return f"""You are working step `{step.id}` of the {prof['name']} playbook: {step.title}.
{frame}
GOAL: {step.goal}

HOW:
{step.instructions}

DEPTH: {DEPTH.get(depth, DEPTH['normal'])}

Ground rules:
- First read {prof['notes']} if it exists — it holds what earlier steps concluded.
- Tools propose, you decide. Every decision needs a note that a person can check.
- Only `{prof['cli']} …` commands will run. Every quote you give must be copied exactly from one line of the data.
- Chat is only a lead: if you cannot cite path:line with an exact quote, you do not have it.
- Look for the innocent explanation as hard as for the incriminating one.
{todo}
When the step is done, end with one short paragraph: what you decided, what you added, what remains doubtful."""


def nudge_prompt(missing: list[str]) -> str:
    return ("The step is not complete yet. Still open:\n" + "\n".join(f"- {m}" for m in missing[:30]) +
            "\nPlease finish these (review/decide each one with a note), then run the `step done` command again.")


class Orchestrator:
    def __init__(self, paths: Paths, log=print, on_event=None, profile: str = "investigator"):
        self.profile = profile
        self.prof = profiles.get(profile)
        self.pb = _pb(profile)
        self.paths = paths
        self.log = log
        self.on_event = on_event
        self.stop = threading.Event()
        self.current_sid = None
        self.bob: BobSession | None = None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_id = stamp
        self.log_path = paths.state / "sessions" / f"{stamp}.jsonl"

    def _bob(self) -> BobSession:
        if self.bob is None:
            self.bob = BobSession(self.paths.repo, self.log_path, on_event=self.on_event, env={
                "INVESTIGATE_ACTOR": "bob", "INVESTIGATE_WORKDIR": str(self.paths.workdir),
                "INVESTIGATE_AGENT": self.profile})
            self.bob.start()
        return self.bob

    def close(self):
        if self.bob:
            self.bob.close()

    def cancel(self):
        self.stop.set()
        if self.bob and self.current_sid:
            self.bob.cancel(self.current_sid)

    # ------------------------------------------------------------- playbook
    def run_playbook(self, step_ids: list[str] | None = None, depth: str = "normal", max_nudges: int = 2,
                     redo: bool = False) -> dict:
        (self.paths.repo / "investigation" / "notes").mkdir(parents=True, exist_ok=True)
        state = _refresh(self.paths, self.log, self.profile)
        ws = Workspace(self.paths.state)
        steps = self.pb.steps_for(state)
        if step_ids:
            steps = [s for s in steps if s.id in step_ids or s.id.split(":")[0] in step_ids]
        results = []
        error = None
        try:
            bob = self._bob()
            bob.context = {"run": self.run_id}
            for step in steps:
                if self.stop.is_set():
                    break
                prog = self.pb.progress(step, state, ws)
                if prog["complete"] and not redo:
                    results.append({**prog, "skipped": True})
                    continue
                self.log(f"▶ {step.id}: {step.title}")
                ws.set_step(step.id, "in_progress", by="orchestrator")
                bob.context = {"run": self.run_id, "step": step.id}
                bob.system(f"step {step.id} started", title=step.title)
                try:
                    sid = bob.new_session(self.prof["mode"])
                    self.current_sid = sid
                    bob.prompt(sid, step_prompt(step, depth, prog["missing"] if prog["status"] != "pending" else [], state,
                                                self.profile))
                    for n in range(max_nudges + 1):
                        state = _refresh(self.paths, self.log, self.profile)
                        ws = Workspace(self.paths.state)
                        prog = self.pb.progress(step, state, ws)
                        if prog["complete"] or self.stop.is_set() or n == max_nudges:
                            break
                        bob.system(f"completion check: {len(prog['missing'])} item(s) open — nudging",
                                   missing=prog["missing"][:30])
                        bob.prompt(sid, nudge_prompt(prog["missing"] or ["run the `step done` command with a summary"]))
                except AcpError as exc:
                    error = explain(exc)
                    bob.system(f"Bob stopped: {error}", error=True)
                    self.log(f"  ✗ {step.id}: {error}")
                    state = _refresh(self.paths, self.log, self.profile)
                    ws = Workspace(self.paths.state)
                    ws.set_step(step.id, "interrupted", by="orchestrator")
                    results.append({**self.pb.progress(step, state, ws), "error": error})
                    break
                if not prog["complete"]:
                    ws.set_step(step.id, "incomplete", by="orchestrator")
                bob.system(f"step {step.id} {'done' if prog['complete'] else 'incomplete'}",
                           missing=prog["missing"][:30])
                self.log(f"  {'✓' if prog['complete'] else '…'} {step.id} ({len(prog['missing'])} open)")
                results.append(prog)
        finally:
            self.current_sid = None
            self.close()
        state = _refresh(self.paths, self.log, self.profile)
        return {"run": self.run_id, "log": str(self.log_path), "steps": results, "error": error,
                "culprit": state["argue"]["culprit_name"], "confidence": state["argue"]["confidence"],
                "basis": state["argue"].get("basis")}

    # ------------------------------------------------------------------ dig
    def dig(self, target: str, question: str | None = None, depth: str = "deep") -> dict:
        (self.paths.repo / "investigation" / "notes").mkdir(parents=True, exist_ok=True)
        error = None
        try:
            bob = self._bob()
            bob.context = {"run": self.run_id, "step": f"dig:{target}"}
            bob.system(f"dig {target}", question=question)
            sid = bob.new_session(self.prof["mode"])
            self.current_sid = sid
            frame = frame_brief(_state(self.paths))
            cli, notes = self.prof["cli"], self.prof["notes"]
            bob.prompt(sid, f"""Go deeper on `{target}`.
{"SECURITY POSTURE" if self.profile == "guard" else "CASE FRAME"} (derived by the tools):
{frame}

{('QUESTION: ' + question) if question else 'QUESTION: Is this right, and what does the rest of the bundle say about it?'}

1. Start with `{cli} dig {target}` — it shows the item, each cited line in context, what the same
   person did around those moments, and where the evidence's identifiers appear elsewhere.
2. Follow the leads into other files and formats (`{cli} search`, `show`, `timeline`).
3. Record what you conclude: `{cli} review {target} accept|reject|amend --note "..."` if it is a
   proposal, inconsistency, root cause or remediation, and `{cli} finding add …` for anything new (quotes are verified).
4. Append what you learned to {notes}.
DEPTH: {DEPTH.get(depth, DEPTH['deep'])}
End with a short answer to the question, citing path:line.""")
        except AcpError as exc:
            error = explain(exc)
            if self.bob:
                self.bob.system(f"Bob stopped: {error}", error=True)
        finally:
            self.current_sid = None
            self.close()
        state = _refresh(self.paths, self.log, self.profile)
        return {"run": self.run_id, "log": str(self.log_path), "error": error,
                "culprit": state["argue"]["culprit_name"], "confidence": state["argue"]["confidence"]}


def list_runs(paths: Paths) -> list[dict]:
    d = paths.state / "sessions"
    out = []
    for f in sorted(d.glob("*.jsonl"), reverse=True) if d.exists() else []:
        lines = f.read_text(encoding="utf-8").splitlines()
        steps = []
        for ln in lines:
            try:
                e = json.loads(ln)
            except Exception:
                continue
            if e.get("step") and e["step"] not in steps:
                steps.append(e["step"])
        out.append({"run": f.stem, "events": len(lines), "steps": steps})
    return out


def read_events(paths: Paths, run: str, since: int = 0) -> tuple[list[dict], int]:
    f = paths.state / "sessions" / f"{run}.jsonl"
    if not f.exists():
        return [], since
    lines = f.read_text(encoding="utf-8").splitlines()
    evs = []
    for ln in lines[since:]:
        try:
            evs.append(json.loads(ln))
        except Exception:
            pass
    return evs, len(lines)
