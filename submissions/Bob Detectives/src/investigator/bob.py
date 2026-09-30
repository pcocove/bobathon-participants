"""IBM Bob inside the system.

Two ways Bob works here:

1. Interactive (`bob chat` in the repo, mode "Investigator"): Bob drives the CLI —
   `src/investigate search/show/timeline/verify-quote/finding add/task …` — and can
   only add evidence through `finding add`, which verifies every quote first.
2. Headless (`investigate bob <task-id>`): the backend hands an agent task to
   `bob run --mode investigator` and records the transcript. Needs BOB_API_KEY.

Rule: chat is only a lead. Nothing Bob says counts until a quote it cites is found at
its source in the bundle as received.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .tasks import Task

MODE = "investigator"


def status() -> dict:
    exe = shutil.which("bob")
    version = None
    if exe:
        try:
            version = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout.split()[0]
        except Exception:
            version = "?"
    return {
        "installed": bool(exe), "version": version,
        "headless": bool(exe and os.environ.get("BOB_API_KEY")),
        "why_not_headless": None if os.environ.get("BOB_API_KEY") else
        "headless `bob run` needs BOB_API_KEY; interactive `bob chat` uses your login",
    }


def prompt_for(task: Task, cli: str) -> str:
    reads = "\n".join(f"- {r['source']} — \"{r['quote'][:200]}\"" for r in task.read)
    return f"""You are working task {task.id} of the automated investigation.

TASK: {task.title}
WHY: {task.why}
WHAT TO DO: {task.question}
START FROM:
{reads or '- (no pointers)'}

Tools (run them with your shell tool, from the repository root):
  {cli} search "<regex>" [--in <path-prefix>]   find lines; every hit is a citation path:line
  {cli} show <path:line> -C 3                   read around a citation
  {cli} timeline --suspect "<name>"             records around the incident window
  {cli} verify-quote <path:line> "<quote>"      check a quote before you rely on it
  {cli} finding add --suspect "<name>" --constraint <presence|statement|echo|knowledge|link|lead> \\
        --class <INCRIMINATES|WEAKLY_INCRIMINATES|EXONERATES|PROVES_INNOCENCE|NEUTRAL> \\
        --title "<short>" --claim "<what it shows>" --source <path:line> --quote "<exact text>" --by bob

Rules:
- Chat is only a lead. If you cannot cite it as path:line with an exact quote, you do not have it.
- Never edit files in the case bundle. Never change verdict.json by hand.
- Quotes must be copied exactly from ONE line (or PDF page / xlsx row / photo).
- Look for innocent explanations as hard as for incriminating ones.
- Finish with one line of JSON: {{"task": "{task.id}", "added": <n findings>, "summary": "<one sentence>"}}
"""


def dispatch(task: Task, repo: Path, state_dir: Path, cli: str = "src/investigate",
             max_turns: int = 30, timeout: int = 900) -> dict:
    st = status()
    if not st["installed"]:
        return {"ok": False, "error": "bob CLI not installed"}
    if not st["headless"]:
        return {"ok": False, "error": st["why_not_headless"],
                "interactive": f"cd {repo} && bob chat   # then pick the 'Investigator' mode and paste the task",
                "prompt": prompt_for(task, cli)}
    cmd = ["bob", "run", "--format", "json", "--mode", MODE, "--trust", "-w", str(repo),
           "--max-turns", str(max_turns), prompt_for(task, cli)]
    started = datetime.now().isoformat(timespec="seconds")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(repo))
        out, err, code = res.stdout, res.stderr, res.returncode
    except subprocess.TimeoutExpired as exc:
        out, err, code = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), "timeout", -1
    final = _final_json(out)
    rec = {"task": task.id, "key": task.key, "started": started, "exit": code, "final": final,
           "stderr": err[-2000:], "stdout_tail": out[-4000:]}
    d = state_dir / "bob_runs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task.key}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return {"ok": code == 0, **rec}


def _final_json(text: str) -> dict | None:
    """Bob's JSON output format may vary by version; find the last {...} with a "task" key."""
    for m in reversed(list(re.finditer(r"\{[^{}]*\"task\"[^{}]*\}", text))):
        try:
            return json.loads(m.group(0).replace('\\"', '"'))
        except Exception:
            continue
    return None
