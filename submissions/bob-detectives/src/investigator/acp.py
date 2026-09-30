"""Minimal Agent Client Protocol client for IBM Bob (`bob acp`).

Bob runs as an ACP server over stdio and uses the user's stored SSO login (no API key).
This client opens sessions in a mode, sends prompts, streams Bob's messages and tool
calls into a JSONL event log, and answers Bob's permission requests with a strict policy:

  allowed   shell commands that run the investigation CLI (`src/investigate …`),
            optionally piped into head/tail/grep/wc/sort/cat; edits under investigation/notes/
  denied    everything else (logged, so the denial is visible in the trace)
"""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

SAFE_PIPE = r"(?:\s*\|\s*(?:head|tail|grep|egrep|wc|sort|uniq|cat|cut|sed -n)\b[^|;&><`$]*)*"
ALLOWED_CMD = re.compile(r"^\s*(?:cd\s+[^;&|]+\s*&&\s*)?(?:\./)?src/(?:investigate|guard)\b[^;&><`]*?" + SAFE_PIPE + r"\s*$")
NOTES_READ = re.compile(r"^\s*(?:cd\s+[^;&|]+\s*&&\s*)?(?:cat|head|tail|ls|wc)(?:\s+-\w+)*\s+investigation/notes(?:/[\w.\-]*)?"
                        r"(?:\s*\|\|\s*echo\s+[\"'][^\"'`$;&|]*[\"'])?\s*$")
HARMLESS_REDIRECTS = re.compile(r"\s+2>&1|\s+2>/dev/null")
NOTES_PART = re.compile(r"(?:cat|head|tail|ls|wc|test)(?:\s+-\w+)*\s+investigation/notes(?:/[\w.\-]*)?")
ECHO_PART = re.compile(r"echo\s+[\"'][^\"'`$;&|<>]*[\"']")


SAFE_FILTERS = {"head", "tail", "grep", "egrep", "wc", "sort", "uniq", "cut", "sed", "cat"}
OPERATORS = {";", "&", "&&", "||", "|", ">", ">>", "<", "<<", "(", ")", "|&", ";;"}


def cli_command_ok(cmd: str) -> bool:
    """`[cd <dir> &&] src/investigate|src/guard …` optionally piped into read-only filters;
    several such pipelines may be joined with `&&`, and a literal `|| echo "…"` may close the line.

    Parsed like a shell: quoted text is data (a note may contain ';' or '&'); operators only
    count outside quotes. Command substitution is refused everywhere, quoted or not."""
    if "`" in cmd or "$(" in cmd or "${" in cmd:
        return False
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return False
    if len(tokens) >= 3 and tokens[0] == "cd" and tokens[2] == "&&":
        tokens = tokens[3:]
    if len(tokens) >= 3 and tokens[-3:-1] == ["||", "echo"] and tokens[-1] not in OPERATORS:
        tokens = tokens[:-3]   # a literal fallback message: `… || echo "none"`
    chain, cur = [], []
    for t in tokens:
        if t == "&&":
            chain.append(cur)
            cur = []
        else:
            cur.append(t)
    chain.append(cur)
    echo = [part for part in chain if part[:1] == ["echo"] and not set(part) & OPERATORS]
    rest = [part for part in chain if part not in echo]
    return bool(rest) and all(_pipeline_ok(part) for part in rest)   # `&& echo "---"` markers are fine


def _pipeline_ok(tokens: list) -> bool:
    """`src/investigate|src/guard …` piped only into read-only filters."""
    segments, cur = [], []
    for t in tokens:
        if t == "|":
            segments.append(cur)
            cur = []
        elif t in OPERATORS:
            return False
        else:
            cur.append(t)
    segments.append(cur)
    head = segments[0]
    if not head or head[0] not in ("src/investigate", "./src/investigate", "src/guard", "./src/guard"):
        return False
    for seg in segments[1:]:
        if not seg or seg[0] not in SAFE_FILTERS:
            return False
        if seg[0] == "sed" and "-n" not in seg:
            return False
        if seg[0] == "cat" and len(seg) > 1:
            return False   # `| cat` only, never `cat <file>`
    return True


def notes_read_ok(cmd: str) -> bool:
    """Reading the agent's own notes, e.g. `ls investigation/notes/x.md && cat … || echo "none"`."""
    if any(x in cmd for x in (";", "`", "$(", "..", ">", "<")):
        return False
    parts = re.split(r"\s*(?:&&|\|\|)\s*", cmd.strip())
    return all(NOTES_PART.fullmatch(p) or ECHO_PART.fullmatch(p) for p in parts) and any(NOTES_PART.fullmatch(p) for p in parts)


class AcpError(RuntimeError):
    pass


def explain(exc: Exception) -> str:
    """Turn Bob's errors into something a person can act on."""
    s = str(exc)
    if "TrialExpired" in s or "Bobcoins" in s or "quota" in s.lower() or "insufficient" in s.lower():
        return ("Bob's usage allowance is used up (IBM Bob: trial Bobcoins exhausted). Add Bobcoins / a plan in your "
                "IBM Bob account, then re-run — everything done so far is saved and the step resumes where it stopped.")
    if "auth" in s.lower() and "required" in s.lower():
        return "Bob needs you to log in again: run `bob chat` once in a terminal, then re-run."
    return s[:500]


class BobSession:
    def __init__(self, repo: Path, log_path: Path, env: dict | None = None, notes_dir: str = "investigation/notes",
                 on_event=None):
        self.repo = repo
        self.log_path = log_path
        self.notes_dir = notes_dir
        self.on_event = on_event
        self.env = {**os.environ, **(env or {})}
        self.proc = None
        self.q: queue.Queue = queue.Queue()
        self.next_id = 1
        self.buffer = {"message": "", "thought": ""}
        self.context = {}
        self.cancelled = threading.Event()
        self.stderr: list[str] = []
        self._last_out: dict = {}

    # ---------------------------------------------------------------- process
    def start(self) -> dict:
        if not shutil.which("bob"):
            raise AcpError("bob CLI not installed")
        self.proc = subprocess.Popen(
            ["bob", "acp", "--trust", "--accept-license", "--log-level", "warn"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(self.repo), env=self.env, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=lambda: [self.stderr.append(l) for l in self.proc.stderr], daemon=True).start()
        return self.request("initialize", {"protocolVersion": 1, "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}, timeout=60)

    def _read(self):
        for line in self.proc.stdout:
            self.q.put(line)
        self.q.put(None)

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()

    # --------------------------------------------------------------- json-rpc
    def _send(self, obj: dict):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict, timeout: float = 1800) -> dict:
        rid = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        end = time.time() + timeout
        while time.time() < end:
            try:
                line = self.q.get(timeout=1)
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise AcpError("bob acp exited: " + "".join(self.stderr)[-500:])
                continue
            if line is None:
                raise AcpError("bob acp closed the connection: " + "".join(self.stderr)[-500:])
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == rid and "method" not in msg:
                if "error" in msg:
                    raise AcpError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self._handle(msg)
        raise AcpError(f"{method}: timed out after {timeout}s")

    # ------------------------------------------------------------ incoming
    def _handle(self, msg: dict):
        method = msg.get("method")
        if method == "session/request_permission":
            p = msg["params"]
            tc = p.get("toolCall", {})
            allow, why = self.policy(tc)
            options = p.get("options", [])
            want = "allow_once" if allow else "reject_once"
            opt = next((o for o in options if o.get("kind") == want), options[0] if options else {"optionId": "reject"})
            self._send({"jsonrpc": "2.0", "id": msg["id"],
                        "result": {"outcome": {"outcome": "selected", "optionId": opt["optionId"]}}})
            self._event("permission", {"allowed": allow, "why": why, "title": tc.get("title"),
                                       "command": (tc.get("rawInput") or {}).get("command")})
            return
        if method == "session/update":
            u = msg["params"]["update"]
            kind = u.get("sessionUpdate")
            if kind == "agent_message_chunk":
                self.buffer["message"] += (u.get("content") or {}).get("text", "")
            elif kind == "agent_thought_chunk":
                self.buffer["thought"] += (u.get("content") or {}).get("text", "")
            elif kind == "tool_call":
                self._flush()
                raw = u.get("rawInput") or {}
                self._event("tool_call", {"id": u.get("toolCallId"), "title": u.get("title"), "kind": u.get("kind"),
                                          "command": raw.get("command"), "input": raw if not raw.get("command") else None})
            elif kind == "tool_call_update":
                out = None
                if u.get("rawOutput"):
                    ro = u["rawOutput"]
                    out = ro.get("result") if isinstance(ro, dict) else str(ro)
                elif u.get("content"):
                    parts = [c.get("content", {}).get("text", "") for c in u["content"] if isinstance(c, dict)]
                    out = "".join(parts) or None
                tid = u.get("toolCallId")
                if out is not None and self._last_out.get(tid) == out.strip():
                    return  # the same output delivered twice (content + rawOutput)
                if out is not None or u.get("status") in ("completed", "failed"):
                    if out is not None:
                        self._last_out[tid] = out.strip()
                    self._event("tool_result", {"id": tid, "status": u.get("status"),
                                                "output": (out or "")[:6000]})
            elif kind == "plan":
                self._flush()
                self._event("plan", {"entries": u.get("entries")})
            return
        # other requests from the agent (fs, terminal) are not offered: refuse politely
        if "id" in msg and method:
            self._send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported"}})

    def policy(self, tool_call: dict) -> tuple[bool, str]:
        kind = tool_call.get("kind")
        raw = tool_call.get("rawInput") or {}
        if kind == "execute":
            cmd = HARMLESS_REDIRECTS.sub("", raw.get("command", ""))
            if cli_command_ok(cmd):
                return True, "investigation CLI"
            if (NOTES_READ.match(cmd) and ".." not in cmd) or notes_read_ok(cmd):
                return True, "reading the case notes"
            return False, "only `src/investigate …` / `src/guard …` commands (and reading investigation/notes/) are allowed"
        if kind in ("edit", "delete", "move"):
            paths = [l.get("path", "") for l in tool_call.get("locations") or []] + \
                    [raw.get(k, "") for k in ("path", "file_path", "filePath") if raw.get(k)]
            notes = str((self.repo / self.notes_dir).resolve())
            ok = paths and all(str((self.repo / p).resolve()).startswith(notes) for p in paths if p)
            return (True, "notes file") if ok else (False, f"edits only allowed under {self.notes_dir}/")
        if kind in ("read", "search", "think", "fetch_local"):
            return True, "read-only"
        if kind == "other" and set(raw) <= {"todos"} and raw:
            return True, "the agent's own to-do list"
        return False, f"tool kind '{kind}' not allowed in this environment"

    # ------------------------------------------------------------ logging
    def _flush(self):
        for k in ("thought", "message"):
            if self.buffer[k].strip():
                self._event(k, {"text": self.buffer[k]})
            self.buffer[k] = ""

    def _event(self, kind: str, data: dict):
        ev = {"at": datetime.now().isoformat(timespec="seconds"), "type": kind, **self.context, **data}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        if self.on_event:
            self.on_event(ev)

    def system(self, text: str, **extra):
        self._event("system", {"text": text, **extra})

    # ------------------------------------------------------------ sessions
    def new_session(self, mode: str = "investigator") -> str:
        res = self.request("session/new", {"cwd": str(self.repo), "mcpServers": []}, timeout=120)
        sid = res["sessionId"]
        modes = [m["id"] for m in (res.get("modes") or {}).get("availableModes", [])]
        if mode in modes:
            self.request("session/set_mode", {"sessionId": sid, "modeId": mode}, timeout=60)
        else:
            self.system(f"mode '{mode}' not available ({modes}); using default")
        return sid

    def prompt(self, sid: str, text: str, timeout: float = 1800) -> str:
        self._event("prompt", {"text": text})
        try:
            res = self.request("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": text}]},
                               timeout=timeout)
        finally:
            self._flush()
        stop = res.get("stopReason", "?")
        self._event("stop", {"reason": stop})
        return stop

    def cancel(self, sid: str):
        try:
            self._send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": sid}})
        except Exception:
            pass
