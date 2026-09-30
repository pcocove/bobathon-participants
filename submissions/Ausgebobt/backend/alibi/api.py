"""FastAPI app: serves inventory, evidence network, sources, analysis and export to the UI.

No Bob calls for normal UI requests (zoom, filters, search, opening evidence).
Bob is only used via /api/analysis/run (background job) and /api/bob/check (no prompt).
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import sources
from .bob_adapter import bob_status, ledger_summary
from .config import ALIBI_DIR, SETTINGS
from .corpus import AN, Corpus
from .graph import graph_cached
from .i18n import tr, tr_tree
from .ingest import DOC_TYPES, run_ingest
from .jobs import RUNNER
from .pipeline import STAGES
from .store import read_json

app = FastAPI(title="ALIBI", version="1.0")
app.add_middleware(GZipMiddleware, minimum_size=2000)


READONLY_STATUS = {"installed": False, "version": None, "connected": False, "readonly": True, "interface": "—",
                   "detail": "Shared read-only view: the analysis was run locally with IBM Bob. "
                             "This server only shows the stored results – no new Bob calls."}


@app.middleware("http")
async def _no_cache(request, call_next):
    if SETTINGS.readonly and request.method not in ("GET", "HEAD", "OPTIONS"):
        return JSONResponse({"detail": "Read-only share: analysis and write actions are disabled here."}, status_code=403)
    resp = await call_next(request)
    if not request.url.path.startswith("/assets/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp

_corpus: dict = {}


def corpus() -> Corpus:
    """Cached corpus; reloaded when labels/vision change."""
    deps = [SETTINGS.state_dir / "units.json", AN / "labels.json", AN / "vision.json"]
    stamp = tuple(d.stat().st_mtime if d.exists() else 0 for d in deps)
    if _corpus.get("stamp") != stamp:
        _corpus["c"] = Corpus()
        _corpus["stamp"] = stamp
    return _corpus["c"]


@app.on_event("startup")
def _startup():
    if not (SETTINGS.state_dir / "units.json").exists():
        run_ingest()


# --------------------------------------------------------------------------- Status

def _result_source(meta: dict) -> dict:
    if not meta:
        return {"kind": "none", "label": "No Bob analysis yet"}
    stages = [k for k, _ in STAGES if k in meta and k != "export"]
    live = any(meta[k].get("live_calls") for k in stages)
    last = max((meta[k].get("finished_at") or "" for k in stages), default="")
    return {"kind": "bob-live" if live else "bob-stored", "stages": stages, "last": last,
            "label": ("Results from real Bob runs" + (" (at least one stage from a stored earlier run)"
                                                              if not live else ""))}


@app.get("/api/status")
def status():
    meta = read_json(AN / "meta.json", {})
    st = READONLY_STATUS if SETTINGS.readonly else bob_status()
    return {"team": SETTINGS.team, "bundle": str(SETTINGS.bundle.relative_to(SETTINGS.team_dir.parents[1])) if SETTINGS.bundle else None,
            "bob": st, "ledger": ledger_summary(), "meta": meta, "result_source": _result_source(meta),
            "job": RUNNER.state(), "stages": [{"key": k, "label": l} for k, l in STAGES],
            "sheep_threshold": SETTINGS.sheep_threshold,
            "verdict_written": SETTINGS.verdict_path.exists(), "readonly": SETTINGS.readonly}


@app.post("/api/bob/check")
def bob_check():
    return bob_status(force=True)


# --------------------------------------------------------------------------- Inventar

@app.get("/api/inventory")
def inventory():
    inv = read_json(SETTINGS.state_dir / "inventory.json", {})
    c = corpus()
    reviewed = read_json(AN / "reviewed.json", {})
    per_file: dict[str, dict] = {}
    for u in c.units:
        d = per_file.setdefault(u["file"], {"units": 0, "reviewed": 0, "labeled": 0, "pending": 0, "doc_type": u["doc_type"]})
        d["units"] += 1
        if u["id"] in reviewed or u["id"] in c.vision:
            d["reviewed"] += 1
        if u["id"] in c.labels:
            d["labeled"] += 1
        if u["status"] != "parsed" and u["id"] not in c.vision:
            d["pending"] += 1
    files = []
    for f in inv.get("files", []):
        d = per_file.get(f["file"], {"units": 0, "reviewed": 0, "labeled": 0, "pending": 0, "doc_type": None})
        content = ("fully reviewed by Bob" if d["units"] and d["reviewed"] == d["units"] else
                   "partially reviewed by Bob" if d["reviewed"] else "not yet reviewed by Bob")
        files.append({**f, **d, "content_status": content})
    discovered = len(files)
    parsed = sum(1 for f in files if f["status"] in ("parsed",) or f["status"].startswith("partial"))
    failed = sum(1 for f in files if f["status"] == "failed")
    fully = sum(1 for f in files if f["units"] and f["reviewed"] == f["units"])
    pending_files = sum(1 for f in files if f["units"] and f["reviewed"] < f["units"])
    units_total = len(c.units)
    units_reviewed = sum(1 for u in c.units if u["id"] in reviewed or u["id"] in c.vision)
    by_type: dict[str, dict] = {}
    for f in files:
        t = DOC_TYPES.get(f.get("doc_type") or "", "Other")
        b = by_type.setdefault(t, {"files": 0, "units": 0, "reviewed": 0, "labeled": 0})
        b["files"] += 1
        b["units"] += f["units"]
        b["reviewed"] += f["reviewed"]
        b["labeled"] += f["labeled"]
    return {"files": files, "by_type": by_type, "coverage": {
        "files_discovered": discovered, "files_parsed": parsed, "files_failed": failed,
        "files_fully_reviewed": fully, "files_pending": pending_files,
        "units_total": units_total, "units_reviewed": units_reviewed, "units_labeled": len(c.labels),
        "all_processed": units_total > 0 and units_reviewed == units_total and failed == 0},
        "packages": read_json(AN / "label_packages.json", []), "rejected": len(read_json(AN / "label_rejected.json", []))}


@app.post("/api/ingest")
def reingest():
    inv = run_ingest()
    _corpus.clear()
    return {"units": inv["unit_count"]}


# --------------------------------------------------------------------------- Graph, Personen, Einheiten

@app.get("/api/graph")
def graph():
    return JSONResponse(graph_cached())


@app.get("/api/persons")
def persons():
    c = corpus()
    return [{"id": p["id"], "name": p["name"], "suspect": p["suspect"], "kind": p.get("kind"), "unit_count": p.get("unit_count", 0),
             "titles": p.get("titles"), "aliases": p["aliases"]} for p in c.persons]


def _unit_lines(u: dict, ctx: int = 0, cap: int = 160):
    loc = u["loc"]
    if loc["type"] != "lines":
        return None
    lines = sources.raw_lines(u["file"])
    a, b = max(1, loc["start"] - ctx), min(len(lines), loc["end"] + ctx)
    if b - a > cap:
        b = a + cap
    return [{"n": n, "text": lines[n - 1], "in": loc["start"] <= n <= loc["end"]} for n in range(a, b + 1)]


@app.get("/api/unit/{uid:path}")
def unit(uid: str):
    c = corpus()
    u = c.by_id.get(uid)
    if not u:
        raise HTTPException(404, "Unknown unit")
    reviewed = read_json(AN / "reviewed.json", {})
    out = {k: u[k] for k in ("id", "file", "doc_type", "cluster", "loc", "title", "fields", "times", "people", "status")}
    out["note"] = u.get("note")
    out["doc_label"] = DOC_TYPES.get(u["doc_type"], u["doc_type"])
    out["lines"] = _unit_lines(u, ctx=1)
    if u["loc"]["type"] == "page" and u["doc_type"] == "pdf":
        out["page_text"] = sources.pdf_pages(u["file"])[u["loc"]["page"] - 1]
    if u["loc"]["type"] == "row":
        out["row_cells"] = sources.xlsx_rows(u["file"]).get(u["loc"].get("sheet"), ())[u["loc"]["row"] - 1]
    out["image"] = u["doc_type"] in ("photo", "scan")
    out["vision"] = tr_tree(c.vision.get(uid))
    out["label"] = tr_tree(c.labels.get(uid))
    out["reviewed"] = reviewed.get(uid)
    out["person_names"] = {h: c.person_by_id[h]["name"] for h in c.unit_people(u) if h in c.person_by_id}
    return out


@app.get("/api/image/{uid:path}")
def image(uid: str):
    c = corpus()
    u = c.by_id.get(uid)
    if not u or u["doc_type"] not in ("photo", "scan"):
        raise HTTPException(404)
    if u["doc_type"] == "photo":
        return FileResponse(sources.bundle_path(u["file"]))
    from .pipeline import _image_for_unit
    data, mime = _image_for_unit(u)
    return Response(content=data, media_type=mime)


@app.get("/api/source")
def source(ref: str = Query(...), ctx: int = 3):
    """Originalstelle zu einer Quellenangabe (path:line, path:start-end, file.pdf:page, xlsx:row)."""
    try:
        s = sources.parse_source(ref)
        kind, segs = sources.source_text(ref)
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))
    c = corpus()
    if kind == "lines":
        lines = sources.raw_lines(s["path"])
        a, b = max(1, s["start"] - ctx), min(len(lines), s["end"] + ctx)
        uid = c.unit_for_line(s["path"], s["start"])
        return {"kind": kind, "path": s["path"], "unit": uid,
                "lines": [{"n": n, "text": lines[n - 1], "in": s["start"] <= n <= s["end"]} for n in range(a, b + 1)]}
    return {"kind": kind, "path": s["path"], "segments": list(segs), "page": s["start"]}


@app.get("/api/search")
def search(q: str = Query("", min_length=0), limit: int = 30):
    c = corpus()
    ql = q.strip().lower()
    if not ql:
        return {"persons": [], "units": []}
    ps = []
    for p in c.persons:
        hay = " ".join([p["id"], p["name"]] + [a["value"] for a in p["aliases"]]).lower()
        if ql in hay:
            ps.append({"id": p["id"], "name": p["name"], "suspect": p["suspect"]})
    uids = c.search(q, limit=limit)
    return {"persons": ps[:20], "units": [{"id": x, "title": c.by_id[x]["title"], "doc_type": c.by_id[x]["doc_type"],
                                           "file": c.by_id[x]["file"]} for x in uids]}


# --------------------------------------------------------------------------- analysis

@app.get("/api/analysis")
def analysis():
    c = corpus()
    persons = {}
    for h in c.suspects:
        persons[h] = read_json(AN / "persons" / f"{h}.json")
    return {"suspects": [{"id": h, "name": n} for h, n in zip(c.suspects, c.suspect_names)],
            "frame": tr_tree(read_json(AN / "frame.json")), "persons": tr_tree(persons),
            "final": tr_tree(read_json(AN / "final.json")), "prevention": tr_tree(read_json(AN / "prevention.json")),
            "meta": read_json(AN / "meta.json", {}), "questions": tr_tree(read_json(AN / "label_questions.json", [])),
            "sheep_threshold": SETTINGS.sheep_threshold, "language": "en",
            "translation": {"source": "IBM Bob translated the stored German analysis text; quotes are verbatim originals"}}


@app.get("/api/runs")
def runs():
    """Stored analysis runs (state/runs/*) plus the current state – for the repeat-run comparison."""
    c = corpus()
    out = []
    base = AN.parent / "runs"
    dirs = sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []
    for d in dirs + [AN]:
        f = read_json(d / "final.json")
        if not f or (d == AN and any(r["built_at"] == f.get("built_at") for r in out)):
            continue  # current state is already stored as a run
        persons = {}
        for h in c.suspects:
            pr = (read_json(d / "persons" / f"{h}.json", {}) or {}).get("result") or {}
            v = next((p.get("verdict") for p in f.get("persons", []) if p.get("id") == h), None)
            persons[h] = {"verdict": v, "conclusion": pr.get("conclusion"), "exo": pr.get("exoneration_confidence"),
                          "weight": (f.get("weights_normalized") or {}).get(h)}
        out.append({"name": "current" if d == AN else d.name, "leading": f.get("leading"),
                    "confidence": f.get("verdict_confidence"), "built_at": f.get("built_at"), "persons": persons})
    return out


class RunReq(BaseModel):
    stages: list[str] | None = None
    force: bool = False


@app.post("/api/analysis/run")
def run(req: RunReq):
    try:
        job = RUNNER.start(req.stages, req.force)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return job.to_dict()


@app.post("/api/analysis/cancel")
def cancel():
    RUNNER.cancel()
    return RUNNER.state()


@app.get("/api/job")
def job():
    return RUNNER.state()


@app.get("/api/bob/calls")
def bob_calls():
    led = read_json(AN.parent / "bob" / "ledger.json", [])
    return led[-200:]


@app.get("/api/bob/call/{key}")
def bob_call(key: str):
    if not key.isalnum():
        raise HTTPException(400)
    rec = read_json(AN.parent / "bob" / "calls" / f"{key}.json")
    if not rec:
        raise HTTPException(404)
    return rec


# --------------------------------------------------------------------------- Export

@app.get("/api/export")
def export_state():
    from .export import build_draft
    d = build_draft(write=not SETTINGS.readonly)
    final = read_json(SETTINGS.verdict_path) if SETTINGS.verdict_path.exists() else None
    d = {**d, "notes": [tr(n) for n in d.get("notes") or []]}
    return {**d, "written": final is not None, "written_matches_draft": final == d.get("draft"),
            "path": str(SETTINGS.verdict_path.relative_to(SETTINGS.team_dir.parents[1]))}


@app.post("/api/export/write")
def export_write():
    from .export import write_final
    r = write_final()
    if not r["written"]:
        raise HTTPException(409, detail=r)
    return r


@app.get("/api/export/download")
def export_download():
    from .export import build_draft
    d = build_draft(write=False)
    if not d["report"]["valid"]:
        raise HTTPException(409, "Export is not valid – see the validation report.")
    body = json.dumps(d["draft"], ensure_ascii=False, indent=2) + "\n"
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="verdict.json"'})


# --------------------------------------------------------------------------- Frontend

DIST = ALIBI_DIR / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        p = (DIST / path).resolve()
        if path and p.is_file() and DIST in p.parents:
            return FileResponse(p)
        return FileResponse(DIST / "index.html")
