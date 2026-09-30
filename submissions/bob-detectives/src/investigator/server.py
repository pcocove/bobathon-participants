"""Local backend for the UI (stdlib only). Binds to 127.0.0.1 by default.

GET  /api/state                 whole investigation (findings, issues, tasks, verdict, …)
GET  /api/source?src=&context=  the cited unit with surrounding lines, for checking a claim
GET  /api/raw?path=             a bundle file (images for the source viewer)
GET  /api/doc?name=             a generated context document (markdown)
GET  /api/search?q=&in=         citable search hits
GET  /api/timeline?hours=       per-suspect records around the operation window (fixed view)
GET  /api/log?since=            pipeline log lines + running flag
POST /api/run                   re-run the pipeline
POST /api/task/<key>/resolve    {decision, note, value, text}
POST /api/task/<key>/reopen
POST /api/task/<key>/bob        dispatch an agent task to Bob (or get the prompt)
POST /api/verify-quote          {source, quote}
POST /api/finding               add a finding (quotes verified first)
"""

from __future__ import annotations

import json
import mimetypes
import threading
import traceback
import webbrowser
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import agent as agentmod
from . import bob as bobmod
from . import pipeline, playbook, profiles
from .engine import Paths
from .tasks import Task
from .workspace import Workspace

WEB = Path(__file__).parent / "web"


class App:
    def __init__(self, paths: Paths, team: str, profile: str = "investigator"):
        self.paths = paths
        self.team = team
        self.profile = profile
        self.prof = profiles.get(profile)
        self.inv = None
        self.lock = threading.Lock()
        self.running = False
        self.log: list[str] = []
        self.error = None
        self.orch = None           # the running Bob orchestrator, if any
        self.agent_run = None      # id of the latest agent run
        self.agent_kind = None
        self.agent_error = None
        self.agent_result = None

    # ------------------------------------------------------------- Bob agent
    def agent_busy(self) -> bool:
        return self.orch is not None

    def start_agent(self, kind: str, **kw) -> dict:
        if self.orch is not None:
            return {"started": False, "error": "Bob is already working", "run": self.agent_run}
        if self.running:
            return {"started": False, "error": "the pipeline is running; try again in a moment"}
        orch = agentmod.Orchestrator(self.paths, log=self.log.append, profile=self.profile)
        self.orch, self.agent_run, self.agent_kind, self.agent_error, self.agent_result = orch, orch.run_id, kind, None, None

        def work():
            try:
                if kind == "playbook":
                    self.agent_result = orch.run_playbook(kw.get("steps"), depth=kw.get("depth", "normal"),
                                                          redo=kw.get("redo", False))
                else:
                    self.agent_result = orch.dig(kw["target"], kw.get("question"), depth=kw.get("depth", "deep"))
                self.agent_error = (self.agent_result or {}).get("error")
            except Exception as exc:
                self.agent_error = f"{type(exc).__name__}: {exc}"
                self.log.append(traceback.format_exc())
            finally:
                self.orch = None
                self.run_async()
        threading.Thread(target=work, daemon=True).start()
        return {"started": True, "run": orch.run_id}

    def run_async(self) -> bool:
        if self.running or self.orch is not None:
            return False
        self.running = True
        self.log.append("── run started ──")

        def work():
            try:
                if self.profile == "guard":
                    from . import guard
                    inv = guard.run(self.paths, log=self.log.append)
                else:
                    inv = pipeline.run(self.paths, team=self.team, log=self.log.append)
                with self.lock:
                    self.inv = inv
                self.error = None
                self.log.append("── run finished ──")
            except Exception as exc:  # surface to UI
                self.error = f"{type(exc).__name__}: {exc}"
                self.log.append(traceback.format_exc())
            finally:
                self.running = False
        threading.Thread(target=work, daemon=True).start()
        return True

    def state(self) -> dict:
        p = self.paths.output / "investigation.json"
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        v = self.paths.output / "verdict.json"
        st["verdict"] = json.loads(v.read_text(encoding="utf-8")) if v.exists() else None
        st["docs"] = sorted(x.name for x in self.paths.context_dir.glob("*.md")) if self.paths.context_dir.exists() else []
        st["bob"] = bobmod.status()
        st["running"] = self.running
        st["agent"] = {"busy": self.agent_busy(), "run": self.agent_run, "kind": self.agent_kind,
                       "error": self.agent_error, "result": self.agent_result}
        st["agent_profile"] = self.prof
        st["profiles"] = {k: {"name": v["name"], "blurb": v["blurb"]} for k, v in profiles.PROFILES.items()}
        if st.get("case"):
            ws = Workspace(self.paths.state)
            pb = agentmod._pb(self.profile)
            st["playbook"] = [{**pb.progress(s, st, ws), "goal": s.goal, "suspect": s.suspect}
                              for s in pb.steps_for(st)]
            st["reviews"] = ws.reviews
            st["journal"] = ws.journal(200)
            st["mode"] = ws.mode
        st["error"] = self.error
        st["bundle"] = str(self.paths.bundle)
        return st

    def task_obj(self, key: str) -> Task | None:
        if self.inv is None:
            return None
        return self.inv.tasks.get(key)


def make_handler(apps: dict, default: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json_body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            app = apps.get(q.get("agent") or default, apps[default])
            try:
                if u.path in ("/", "/index.html"):
                    return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
                if u.path == "/view":
                    return self._send(200, (WEB / "viewer.html").read_bytes(), "text/html; charset=utf-8")
                if u.path.startswith("/static/"):
                    f = (WEB / u.path[len("/static/"):]).resolve()
                    if WEB.resolve() not in f.parents or not f.exists():
                        return self._send(404, {"error": "not found"})
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                if u.path == "/api/state":
                    return self._send(200, app.state())
                if u.path == "/api/verdict.json":
                    f = app.paths.output / "verdict.json"
                    if not f.exists():
                        return self._send(404, {"error": "no verdict yet"})
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Disposition", 'attachment; filename="verdict.json"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if u.path == "/api/verdict-files":
                    from .verdict import verify_file
                    if app.inv is None:
                        return self._send(503, {"error": "not ready"})
                    out = []
                    for f in sorted(app.paths.repo.glob("verdict*.json")) + sorted(app.paths.repo.glob("submissions/*/verdict.json")):
                        if f.name in ("verdict_template.json", "verdict_example.json"):
                            continue
                        try:
                            v = json.loads(f.read_text(encoding="utf-8"))
                            rep = verify_file(app.inv.corpus, v)
                            out.append({"path": str(f.relative_to(app.paths.repo)), "culprit": v.get("culprit"),
                                        "confidence": v.get("confidence"), "report": rep,
                                        "verdicts": {s["name"]: s["verdict"] for s in v.get("suspects", [])}})
                        except Exception as exc:
                            out.append({"path": str(f.relative_to(app.paths.repo)), "error": str(exc)})
                    return self._send(200, {"files": out})
                if u.path == "/api/agent/events":
                    run = q.get("run") or app.agent_run or (agentmod.list_runs(app.paths)[:1] or [{}])[0].get("run")
                    evs, nxt = agentmod.read_events(app.paths, run, int(q.get("since", 0))) if run else ([], 0)
                    return self._send(200, {"run": run, "events": evs, "next": nxt, "busy": app.agent_busy(),
                                            "error": app.agent_error})
                if u.path == "/api/agent/runs":
                    return self._send(200, {"runs": agentmod.list_runs(app.paths)})
                if u.path == "/api/log":
                    since = int(q.get("since", 0))
                    return self._send(200, {"lines": app.log[since:], "next": len(app.log), "running": app.running,
                                            "error": app.error})
                if app.inv is None:
                    return self._send(503, {"error": "pipeline not run yet"})
                inv = app.inv
                if u.path == "/api/source":
                    ctx = 10 ** 7 if q.get("full") == "1" else int(q.get("context", 6))
                    return self._send(200, source_view(inv, q.get("src", ""), ctx, q.get("quote")))
                if u.path == "/api/raw":
                    f = (inv.paths.bundle / q.get("path", "")).resolve()
                    if inv.paths.bundle.resolve() not in f.parents or not f.exists():
                        return self._send(404, {"error": "not found"})
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                if u.path == "/api/doc":
                    f = (inv.paths.context_dir / q.get("name", "")).resolve()
                    if inv.paths.context_dir.resolve() not in f.parents or not f.exists():
                        return self._send(404, {"error": "not found"})
                    return self._send(200, f.read_bytes(), "text/markdown; charset=utf-8")
                if u.path == "/api/search":
                    hits = inv.corpus.search(q.get("q", ""), regex=q.get("regex", "1") == "1",
                                             path_prefix=q.get("in", ""), limit=int(q.get("limit", 80)))
                    return self._send(200, {"hits": hits})
                if u.path == "/api/timeline":
                    return self._send(200, timeline(inv, int(q.get("hours", 14))))
                return self._send(404, {"error": "not found"})
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        def do_POST(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            app = apps.get(q.get("agent") or default, apps[default])
            try:
                body = self._json_body()
                if u.path == "/api/run":
                    if app.agent_busy():
                        return self._send(409, {"error": "Bob is working; the pipeline re-runs when he finishes"})
                    return self._send(200, {"started": app.run_async()})
                if u.path == "/api/agent/run":
                    steps = body.get("steps") or None
                    return self._send(200, app.start_agent("playbook", steps=steps, depth=body.get("depth", "normal"),
                                                           redo=bool(body.get("redo"))))
                if u.path == "/api/agent/dig":
                    if not body.get("target"):
                        return self._send(400, {"error": "target required"})
                    return self._send(200, app.start_agent("dig", target=body["target"], question=body.get("question"),
                                                           depth=body.get("depth", "deep")))
                if u.path == "/api/agent/stop":
                    if app.orch:
                        app.orch.cancel()
                    return self._send(200, {"ok": True})
                if u.path == "/api/mode":
                    Workspace(app.paths.state).set_mode(body.get("mode", "agent"))
                    app.run_async()
                    return self._send(200, {"ok": True})
                if u.path == "/api/review":
                    st = app.state()
                    item = next((x for x in st["findings"] + st["issues"] if x["id"] == body.get("id")), None)
                    if item is None:
                        return self._send(404, {"error": "unknown id"})
                    if not body.get("note"):
                        return self._send(400, {"error": "a decision needs a note"})
                    Workspace(app.paths.state).review(item["key"], body.get("decision", "accept"), body["note"],
                                                      by="human (UI)", id=body.get("id"))
                    app.run_async()
                    return self._send(200, {"ok": True})
                if u.path == "/api/verify-quote":
                    if app.inv is None:
                        return self._send(503, {"error": "not ready"})
                    return self._send(200, app.inv.corpus.verify(body.get("source", ""), body.get("quote", "")))
                if u.path == "/api/finding":
                    res = pipeline.add_agent_finding(app.paths, {**body, "by": body.get("by", "human")})
                    if res["accepted"]:
                        app.run_async()
                    return self._send(200, res)
                parts = u.path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "task"]:
                    key, action = parts[2], parts[3]
                    t = app.task_obj(key)
                    if t is None:
                        return self._send(404, {"error": "unknown task"})
                    if action == "resolve":
                        extra = {k: body[k] for k in ("value", "text") if body.get(k) not in (None, "")}
                        if "value" in extra:
                            extra["value"] = float(extra["value"])
                        app.inv.tasks.resolve(key, body.get("decision", ""), body.get("note", ""), by="human (UI)",
                                              extra=extra)
                        app.run_async()
                        return self._send(200, {"ok": True})
                    if action == "reopen":
                        app.inv.tasks.reopen(key)
                        app.run_async()
                        return self._send(200, {"ok": True})
                    if action == "bob":
                        st = bobmod.status()
                        if not st["headless"]:
                            return self._send(200, {"ok": False, "error": st["why_not_headless"],
                                                    "prompt": bobmod.prompt_for(t, "src/investigate")})

                        def work():
                            app.log.append(f"── Bob working on {t.id} ──")
                            res = bobmod.dispatch(t, app.paths.repo, app.paths.state)
                            app.log.append(f"Bob finished {t.id}: exit {res.get('exit')} {res.get('final')}")
                            app.run_async()
                        threading.Thread(target=work, daemon=True).start()
                        return self._send(200, {"ok": True, "dispatched": True})
                return self._send(404, {"error": "not found"})
            except Exception as exc:
                return self._send(400, {"error": f"{type(exc).__name__}: {exc}"})
    return H


def source_view(inv, src: str, context: int, quote: str | None) -> dict:
    doc, a, b = inv.corpus.resolve(src)
    if doc is None:
        return {"error": f"unknown source {src}"}
    out = {"source": src, "path": doc.path, "kind": doc.kind, "ocr": doc.is_ocr}
    if quote:
        out["verification"] = inv.corpus.verify(src, quote)
    if doc.kind == "text":
        a = a or 1
        b = b or a
        lo, hi = max(1, a - context), min(len(doc.lines), b + context)
        out["lines"] = [{"n": i, "text": doc.lines[i - 1], "hit": a <= i <= b} for i in range(lo, hi + 1)]
        out["total"] = len(doc.lines)
    elif doc.kind == "pdf":
        out["pages"] = [{"page": p, "text": t, "hit": p == a, "ocr": doc.page_ocr.get(p)} for p, t in doc.pages.items()]
    elif doc.kind == "xlsx":
        out["rows"] = [{"row": r, "cells": c, "hit": r == a} for r, c in doc.rows.items()]
    elif doc.kind == "image":
        out["image"] = f"/api/raw?path={doc.path}"
        out["ocr_text"] = doc.ocr_text
    return out


def timeline(inv, hours: int) -> dict:
    op0, op1 = inv.op
    bo = inv.case.blackout or inv.op
    lo, hi = op0 - timedelta(hours=hours), op1 + timedelta(hours=hours)
    lanes = []
    for p in inv.case.suspects:
        evs = inv.events_for(p, ("card", "garage", "slack", "calendar"), lo, hi)
        lanes.append({"key": p.key, "name": p.name, "events": [
            {"t": e.t.isoformat(), "kind": e.kind, "text": e.text, "source": e.source,
             "city": e.attrs.get("city"), "direction": e.attrs.get("direction"),
             "fix": e.attrs.get("clock_fix"), "raw": e.t_raw,
             "degraded": bool(e.attrs.get("degraded")),
             "end": e.attrs.get("end")} for e in evs]})
    return {"from": lo.isoformat(), "to": hi.isoformat(), "op": [op0.isoformat(), op1.isoformat()],
            "blackout": [bo[0].isoformat(), bo[1].isoformat()], "site": inv.site, "lanes": lanes,
            "sightings": inv.sightings}


def serve(paths: Paths, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False, team: str = "bob-investigator"):
    """One server, both agents: ?agent=investigator (default) or ?agent=guard."""
    current = profiles.current()
    apps = {current: App(paths, team, current)}
    for pid, prof in profiles.PROFILES.items():
        if pid not in apps:
            other = pipeline.make_paths(str(paths.bundle), str(paths.repo / prof["workdir"]), str(paths.repo))
            apps[pid] = App(other, team, pid)
    for a in apps.values():
        a.run_async()
    httpd = ThreadingHTTPServer((host, port), make_handler(apps, current))
    url = f"http://{host}:{port}/" + ("?agent=guard" if current == "guard" else "")
    print(f"Bob Investigator + Security Guard UI on {url}  (bundle: {paths.bundle})")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
