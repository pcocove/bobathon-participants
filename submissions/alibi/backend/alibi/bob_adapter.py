"""IBM Bob adapter via Bob Shell (Agent Client Protocol, JSON-RPC over stdio).

Why ACP instead of `bob run`: `bob run` (headless) requires BOB_API_KEY. `bob acp`
uses Bob Shell's stored SSO login. Processes are always started with argument
lists (no shell string); case text only travels as prompt data over stdin, never
on a command line.

Each request: new session → mode "ask" (read-only tools) → prompt → collect the
answer text → extract JSON → validate → optionally one repair turn. The session's
working directory is an empty sandbox folder; tool permission requests are denied.
Results, errors and usage are stored under state/bob/; successful results are reused.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import SETTINGS
from .store import read_json, write_json

BOB_DIR = SETTINGS.state_dir / "bob"
CALLS_DIR = BOB_DIR / "calls"
PROMPTS_DIR = BOB_DIR / "prompts"
SANDBOX = BOB_DIR / "sandbox"
BOB_DB = Path.home() / ".bob" / "db" / "bob.db"


class BobError(Exception):
    pass


class BobUnavailable(BobError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- ACP-Client

class AcpClient:
    def __init__(self, timeout: int | None = None):
        self.timeout = timeout or SETTINGS.bob_timeout_s
        self.proc: subprocess.Popen | None = None
        self.pending: dict[int, dict] = {}
        self.updates: dict[str, list] = {}
        self.stderr: list[str] = []
        self.nid = 0
        self.lock = threading.Lock()
        self.cv = threading.Condition()
        self.agent_info: dict | None = None

    def start(self):
        exe = shutil.which(SETTINGS.bob_command[0])
        if not exe:
            raise BobUnavailable("Bob Shell (command \"bob\") is not installed or not on PATH.")
        SANDBOX.mkdir(parents=True, exist_ok=True)
        args = [exe, *SETTINGS.bob_command[1:], "acp", "--disable-mcp", "--disable-subagents"]
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8", bufsize=1, cwd=str(SANDBOX))
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        r = self.call("initialize", {"protocolVersion": 1, "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}, timeout=60)
        self.agent_info = r.get("agentInfo")
        return r

    def _send(self, obj):
        assert self.proc and self.proc.stdin
        with self.lock:
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def _read(self):
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in m and ("result" in m or "error" in m) and "method" not in m:
                with self.cv:
                    self.pending[m["id"]] = m
                    self.cv.notify_all()
            elif "method" in m and "id" in m:
                # request from the agent to us: tool permissions are denied.
                if m["method"] == "session/request_permission":
                    self._send({"jsonrpc": "2.0", "id": m["id"], "result": {"outcome": {"outcome": "cancelled"}}})
                else:
                    self._send({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": "not supported by ALIBI"}})
                sid = (m.get("params") or {}).get("sessionId")
                if sid:
                    self.updates.setdefault(sid, []).append({"denied_request": m["method"]})
            elif m.get("method") == "session/update":
                p = m.get("params", {})
                self.updates.setdefault(p.get("sessionId"), []).append(p.get("update", {}))
        with self.cv:
            self.cv.notify_all()

    def _read_err(self):
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip())
            del self.stderr[:-50]

    def call(self, method: str, params: dict, timeout: float | None = None) -> dict:
        with self.lock:
            self.nid += 1
            i = self.nid
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        deadline = time.time() + (timeout or self.timeout)
        with self.cv:
            while i not in self.pending:
                if self.proc and self.proc.poll() is not None:
                    raise BobUnavailable("Bob-Prozess beendet: " + " | ".join(self.stderr[-3:]))
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(f"Timeout during {method}")
                self.cv.wait(timeout=min(left, 1.0))
            m = self.pending.pop(i)
        if "error" in m:
            msg = m["error"].get("message", str(m["error"]))
            if "auth" in msg.lower() or "login" in msg.lower():
                raise BobUnavailable(f"Bob not signed in: {msg}")
            raise BobError(msg)
        return m.get("result", {})

    def new_session(self, mode: str = "ask") -> str:
        r = self.call("session/new", {"cwd": str(SANDBOX), "mcpServers": []}, timeout=60)
        sid = r["sessionId"]
        modes = [m["id"] for m in (r.get("modes") or {}).get("availableModes", [])]
        if mode in modes:
            self.call("session/set_mode", {"sessionId": sid, "modeId": mode}, timeout=30)
        return sid

    def prompt(self, sid: str, blocks: list[dict], timeout: float | None = None) -> dict:
        start = len(self.updates.get(sid, []))
        t0 = time.time()
        try:
            r = self.call("session/prompt", {"sessionId": sid, "prompt": blocks}, timeout=timeout)
        except TimeoutError:
            try:
                self._send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": sid}})
            except Exception:
                pass
            raise
        ups = self.updates.get(sid, [])[start:]
        text = "".join(u.get("content", {}).get("text", "") for u in ups
                       if u.get("sessionUpdate") == "agent_message_chunk" and u.get("content", {}).get("type") == "text")
        tools = [{"title": u.get("title"), "kind": u.get("kind"), "status": u.get("status")}
                 for u in ups if u.get("sessionUpdate") in ("tool_call",)]
        denied = [u for u in ups if "denied_request" in u]
        return {"text": text, "stop_reason": r.get("stopReason"), "elapsed_s": round(time.time() - t0, 1),
                "tool_calls": tools, "denied_requests": len(denied)}

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# --------------------------------------------------------------------------- usage

def read_spend(session_id: str, wait_s: float = 3.0) -> dict | None:
    """Reads the usage (cost, contextTokens) Bob itself records for the session.

    Source: Bob's local task database (~/.bob/db/bob.db, read-only). The unit of
    "cost" is whatever Bob reports – we do not convert it.
    """
    if not BOB_DB.exists():
        return None
    deadline = time.time() + wait_s
    last = None
    while True:
        try:
            con = sqlite3.connect(f"file:{BOB_DB}?mode=ro", uri=True, timeout=2)
            row = con.execute("select costs from tasks where id = ?", (session_id,)).fetchone()
            con.close()
            if row and row[0]:
                last = json.loads(row[0])
                if last.get("cost"):
                    return last
        except sqlite3.Error:
            pass
        if time.time() > deadline:
            return last
        time.sleep(0.4)


# --------------------------------------------------------------------------- Status

_status_cache: dict = {}


def bob_status(force: bool = False) -> dict:
    """Checks installation and login without a billed prompt (initialize + session/new)."""
    if _status_cache and not force and time.time() - _status_cache.get("_t", 0) < 300:
        return {k: v for k, v in _status_cache.items() if k != "_t"}
    st = {"installed": False, "version": None, "connected": False, "detail": "", "interface": "bob acp (Agent Client Protocol)",
          "checked_at": now()}
    exe = shutil.which(SETTINGS.bob_command[0])
    if not exe:
        st["detail"] = "Command \"bob\" not found. Install Bob Shell and run \"bob\" once in a terminal (SSO login)."
    else:
        st["installed"] = True
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
            st["version"] = (out.stdout or "").strip().splitlines()[0] if out.stdout else None
        except Exception as e:
            st["detail"] = f"Version check failed: {e}"
        c = AcpClient(timeout=60)
        try:
            c.start()
            sid = c.new_session("ask")
            st["connected"] = bool(sid)
            st["detail"] = "Bob Shell reachable, SSO session active."
        except Exception as e:
            st["detail"] = (f"Bob not connected: {e}. Run \"bob\" once in a terminal and sign in via SSO; "
                            "then check again here.")
        finally:
            c.close()
    _status_cache.clear()
    _status_cache.update(st, _t=time.time())
    return st


# --------------------------------------------------------------------------- cached requests

def extract_json(text: str):
    """Finds the JSON object in Bob's answer text (the ACP envelope is not the result)."""
    t = text.strip()
    if "```" in t:
        import re
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
        if m:
            t = m.group(1)
    i = t.find("{")
    if i < 0:
        raise ValueError("No JSON structure in the response")
    obj, _ = json.JSONDecoder().raw_decode(t[i:])
    return obj


class BobPool:
    """Reusable ACP processes for parallel requests (one process per worker)."""

    def __init__(self):
        self._free: list[AcpClient] = []
        self._lock = threading.Lock()

    def acquire(self) -> AcpClient:
        with self._lock:
            while self._free:
                c = self._free.pop()
                if c.proc and c.proc.poll() is None:
                    return c
        c = AcpClient()
        c.start()
        return c

    def release(self, c: AcpClient, broken: bool = False):
        if broken:
            c.close()
            return
        with self._lock:
            self._free.append(c)

    def close_all(self):
        with self._lock:
            for c in self._free:
                c.close()
            self._free.clear()


POOL = BobPool()
_spend_lock = threading.Lock()


def cache_key(stage: str, prompt: str, images: list[bytes] | None = None) -> str:
    h = hashlib.sha256()
    h.update(stage.encode())
    h.update(b"\0")
    h.update(prompt.encode("utf-8"))
    for im in images or []:
        h.update(hashlib.sha256(im).digest())
    return h.hexdigest()[:24]


def run_bob(stage: str, label: str, prompt: str, validate: Callable[[dict], list[str]],
            images: list[tuple[bytes, str]] | None = None, reuse: bool = True, repair: bool = True,
            followup: Callable[[dict], str | None] | None = None, max_followups: int = 1) -> dict:
    """Runs a Bob request or reuses a stored successful result.

    Returns a record with status ok|invalid|error, parsed, validation, spend …
    """
    key = cache_key(stage, prompt, [b for b, _ in images or []])
    rec_path = CALLS_DIR / f"{key}.json"
    prev = read_json(rec_path)
    if reuse and prev and prev.get("status") in ("ok", "ok_with_warnings"):
        prev["reused"] = True
        return prev
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    (PROMPTS_DIR / f"{key}.txt").write_text(prompt, encoding="utf-8")
    rec = {"key": key, "stage": stage, "label": label, "started_at": now(), "prompt_file": f"state/bob/prompts/{key}.txt",
           "prompt_chars": len(prompt), "images": [m for _, m in images or []], "status": "running",
           "turns": [], "spend": None, "session_id": None, "source": "bob-acp", "reused": False}
    client = None
    broken = False
    try:
        client = POOL.acquire()
        rec["agent"] = client.agent_info
        sid = client.new_session("ask")
        rec["session_id"] = sid
        blocks = [{"type": "text", "text": prompt}]
        for data, mime in images or []:
            blocks.append({"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime})
        def turn(blocks_or_text, note=None):
            b = blocks_or_text if isinstance(blocks_or_text, list) else [{"type": "text", "text": blocks_or_text}]
            r = client.prompt(sid, b)
            t = {"response": r["text"], "stop_reason": r["stop_reason"], "elapsed_s": r["elapsed_s"],
                 "tool_calls": r["tool_calls"], "denied_requests": r["denied_requests"]}
            if note:
                t.update(note)
            rec["turns"].append(t)
            try:
                pj = extract_json(r["text"])
                return pj, validate(pj)
            except (ValueError, json.JSONDecodeError) as e:
                return None, [f"Response is not valid JSON: {e}"]

        def with_repair(parsed, errors):
            if errors and repair:
                fix = ("Your answer violates the required format. Errors:\n- " + "\n- ".join(errors[:25]) +
                       "\n\nReply again with the complete, corrected JSON object and nothing else. "
                       "Quotes must be copied verbatim from the original lines provided.")
                p2, e2 = turn(fix, {"repair_prompt": fix})
                if p2 is not None and (parsed is None or len(e2) <= len(errors)):
                    return p2, e2
            return parsed, errors

        parsed, errors = with_repair(*turn(blocks))
        for _ in range(max_followups if followup else 0):
            if parsed is None:
                break
            msg = followup(parsed)
            if not msg:
                break
            p3, e3 = with_repair(*turn(msg, {"followup_prompt": msg}))
            if p3 is not None:
                parsed, errors = p3, e3
        rec["parsed"] = parsed
        rec["validation"] = errors
        rec["status"] = "ok" if parsed is not None and not errors else ("invalid" if parsed is not None else "error")
        if rec["status"] == "invalid" and parsed is not None:
            # partially valid results stay usable; single entries are filtered later
            rec["status"] = "ok_with_warnings" if len(errors) <= 40 else "invalid"
        rec["spend"] = read_spend(sid)
    except TimeoutError as e:
        broken = True
        rec["status"], rec["error"] = "error", f"Timeout: {e}"
    except BobUnavailable as e:
        broken = True
        rec["status"], rec["error"] = "unavailable", str(e)
    except Exception as e:  # noqa: BLE001 – Fehler werden protokolliert
        broken = True
        rec["status"], rec["error"] = "error", f"{type(e).__name__}: {e}"
    finally:
        if client:
            POOL.release(client, broken)
    rec["finished_at"] = now()
    write_json(rec_path, rec)
    _append_ledger(rec)
    return rec


def _append_ledger(rec: dict):
    """Ledger of all requests incl. usage (errors too)."""
    with _spend_lock:
        path = BOB_DIR / "ledger.json"
        led = read_json(path, [])
        led.append({"key": rec["key"], "stage": rec["stage"], "label": rec["label"], "status": rec["status"],
                    "started_at": rec["started_at"], "finished_at": rec.get("finished_at"),
                    "spend": rec.get("spend"), "error": rec.get("error"), "prompt_chars": rec["prompt_chars"],
                    "validation_errors": len(rec.get("validation") or [])})
        write_json(path, led)


def ledger_summary() -> dict:
    led = read_json(BOB_DIR / "ledger.json", [])
    cost = sum((e.get("spend") or {}).get("cost", 0) or 0 for e in led)
    toks = sum((e.get("spend") or {}).get("contextTokens", 0) or 0 for e in led)
    return {"calls": len(led), "ok": sum(1 for e in led if e["status"] in ("ok", "ok_with_warnings")),
            "errors": sum(1 for e in led if e["status"] in ("error", "unavailable", "invalid")),
            "cost_total": round(cost, 5), "context_tokens_total": toks,
            "cost_note": "\"cost\" is the value Bob Shell records per session (Bob's own unit), not converted."}
