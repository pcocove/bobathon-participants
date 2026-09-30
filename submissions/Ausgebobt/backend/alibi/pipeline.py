"""Analysis pipeline: images → labeling → case frame → exoneration per person →
verdict → cross-check → prevention → export draft.

Jede inhaltliche Schlussfolgerung stammt aus einem gespeicherten Bob-Auftrag.
The code contains no case-specific conclusions; only parsing, search, evidence
checks, weight normalisation and export safety rules (e.g. no clearing without
verified evidence) are deterministic.
"""
from __future__ import annotations

import io
import json
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from . import sources
from .bob_adapter import run_bob
from .config import ALIBI_DIR, SETTINGS
from .corpus import AN, REL_RANK, Corpus, window_from_frame
from .store import read_json, write_json

PROMPTS = ALIBI_DIR / "prompts"
TAGS = {"belastend", "entlastend", "alternative_erklaerung", "widerspruch", "offene_frage", "wissensweg", "zugang",
        "anwesenheit", "zeitangabe", "uhrabweichung", "ereignis", "behauptung"}
REL_TYPES = {"erwaehnt", "behauptet", "ist_zugeordnet", "fand_statt", "hatte_zugang", "konnte_erfahren", "stuetzt",
             "widerspricht", "erklaert", "entlastet", "belastet", "bleibt_offen"}
BASIS = {"direkt", "abgeleitet", "moeglich", "ungeprueft"}
# Bob occasionally used tag names or umlauts as relation type – fixed, documented mapping onto the vocabulary.
REL_ALIASES = {"anwesenheit": "ist_zugeordnet", "offene_frage": "bleibt_offen", "wissensweg": "konnte_erfahren",
               "ereignis": "fand_statt", "zugang": "hatte_zugang", "uhrabweichung": "bleibt_offen",
               "alternative_erklaerung": "erklaert", "widerspruch": "widerspricht"}


def norm_rel(t) -> str:
    t = str(t or "").lower().strip().replace(" ", "_").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    return REL_ALIASES.get(t, t)
STAGES = [
    ("vision", "Read image sources with Bob Vision"),
    ("label", "Label the entire case file"),
    ("frame", "Case frame and points of suspicion"),
    ("persons", "Exoneration review for all eight people"),
    ("synthesis", "Reconstruction and verdict"),
    ("crosscheck", "Cross-check of the leading hypothesis"),
    ("prevention", "Prevention measures"),
    ("export", "Export draft and validation"),
]


def weights_note(raw_sum: float) -> str:
    return (f"Relative weights estimated by Bob, normalised by ALIBI to sum to 1 (raw sum {raw_sum:.3f}). "
            "Comparison under the case assumption that one of the eight people committed the act.")


def tpl(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def fill(t: str, **kw) -> str:
    for k, v in kw.items():
        t = t.replace("{{" + k + "}}", str(v))
    return t


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Progress:
    """Schnittstelle zum Job-Runner (siehe jobs.py)."""

    def __init__(self):
        self.cancelled = False

    def stage(self, key: str, label: str, total: int):  # pragma: no cover - overridden
        pass

    def step(self, n: int = 1, msg: str | None = None):
        pass

    def log(self, msg: str):
        pass


def _meta_update(stage: str, recs: list[dict], extra: dict | None = None):
    meta = read_json(AN / "meta.json", {})
    live = sum(1 for r in recs if not r.get("reused"))
    cost = sum(((r.get("spend") or {}).get("cost") or 0) for r in recs if not r.get("reused"))
    meta[stage] = {"finished_at": now(), "calls": [r["key"] for r in recs], "live_calls": live,
                   "reused_calls": len(recs) - live, "status": [r["status"] for r in recs],
                   "cost_live": round(cost, 5), "source": "bob-live" if live else "bob-gespeichert"}
    if extra:
        meta[stage].update(extra)
    write_json(AN / "meta.json", meta)


def _ev_list(c: Corpus, evs) -> list[dict]:
    return [c.resolve(e) for e in (evs or []) if isinstance(e, dict)]


def _ok_rate(c: Corpus, evs: list[dict]) -> float:
    if not evs:
        return 1.0
    return sum(1 for e in evs if c.resolve(e)["ok"] or c.resolve(e)["status"] == "image") / len(evs)


def _collect_evs(obj) -> list[dict]:
    """Alle {unit, quote}-Objekte in einer verschachtelten Bob-Antwort."""
    out = []
    if isinstance(obj, dict):
        if "unit" in obj and "quote" in obj:
            out.append(obj)
        for v in obj.values():
            out.extend(_collect_evs(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_collect_evs(v))
    return out


def _resolve_tree(c: Corpus, obj):
    """Replaces every {unit, quote} item with the resolved, checked evidence."""
    if isinstance(obj, dict):
        if "unit" in obj and "quote" in obj:
            return c.resolve(obj)
        return {k: _resolve_tree(c, v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_tree(c, v) for v in obj]
    return obj


# =========================================================================== 1 Vision

def _image_for_unit(u: dict) -> tuple[bytes, str]:
    from PIL import Image
    if u["doc_type"] == "scan":
        from pypdf import PdfReader
        reader = PdfReader(str(sources.bundle_path(u["file"])))
        imgs = list(reader.pages[u["loc"]["page"] - 1].images)
        im = imgs[0].image
    else:
        im = Image.open(sources.bundle_path(u["file"]))
    im = im.convert("RGB")
    im.thumbnail((1600, 1600))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue(), "image/jpeg"


def _v_vision(p: dict) -> list[str]:
    errs = []
    if not isinstance(p.get("transcript_lines"), list):
        errs.append("transcript_lines missing or not a list")
    if not isinstance(p.get("description"), str):
        errs.append("description missing")
    return errs


def stage_vision(job: Progress, force: bool = False):
    c = Corpus()
    targets = [u for u in c.units if u["doc_type"] in ("scan", "photo")]
    job.stage("vision", "Read image sources with Bob Vision", len(targets))
    results = read_json(AN / "vision.json", {})
    recs = []
    for u in targets:
        if job.cancelled:
            return
        img, mime = _image_for_unit(u)
        src = u["file"] + (f", page {u['loc']['page']}" if u["loc"]["type"] == "page" else "")
        prompt = fill(tpl("01_vision.md"), SOURCE=src, KIND="scanned document" if u["doc_type"] == "scan" else "photo",
                      RULES=tpl("00_common_rules.md"))
        rec = run_bob("vision", f"Image: {src}", prompt, _v_vision, images=[(img, mime)], reuse=not force)
        recs.append(rec)
        if rec.get("parsed") and rec["status"] in ("ok", "ok_with_warnings"):
            results[u["id"]] = {**rec["parsed"], "call": rec["key"], "reused": rec.get("reused", False),
                                "status": "Bob Vision transcript (uncertain)"}
        job.step(1, f"{src}: {rec['status']}")
    write_json(AN / "vision.json", results)
    _meta_update("vision", recs)


# =========================================================================== 2 labeling

FILE_ORDER = ["interview", "notebook", "pdf", "scan", "photo", "email", "jira", "helpdesk", "meeting", "diligence",
              "expense", "slack", "calendar", "card", "garage", "permit", "meta"]


def _compact(c: Corpus, u: dict) -> str:
    """Compact but quotable rendering for labeling large tables."""
    lines = sources.raw_lines(u["file"]) if u["loc"]["type"] == "lines" else None
    if u["doc_type"] in ("garage", "card", "expense", "diligence") and u["loc"]["start"] == u["loc"]["end"]:
        n = u["loc"]["start"]
        ppl = ",".join(f"{x['person']}{'?' if x.get('basis') == 'fahrzeug_unsicher' else ''}" for x in u["people"] if x.get("person"))
        t = u["times"][0]["local"][:16].replace("T", " ") if u["times"] and u["doc_type"] == "card" else ""
        return f"[{u['id']}] L{n}: {lines[n - 1]}" + (f" (={t} local time)" if t else "") + (f" ⇒ {ppl}" if ppl and u["doc_type"] == "garage" else "")
    if u["doc_type"] == "calendar":
        f = u["fields"]
        t0 = next((t for t in u["times"] if t.get("role") == "dtstart"), None)
        t1 = next((t for t in u["times"] if t.get("role") == "dtend"), None)
        when = (t0["local"][:16].replace("T", " ") if t0 else "?") + ("–" + t1["local"][11:16] if t1 else "")
        foc = u["loc"].get("focus", u["loc"]["start"])
        extra = ""
        for n in range(u["loc"]["start"], u["loc"]["end"] + 1):
            if lines[n - 1].startswith(("DESCRIPTION", "LOCATION")):
                extra += f" | L{n}: {lines[n - 1]}"
        return f"[{u['id']}] L{foc}: {lines[foc - 1]} | {when} local time ({t0['basis'] if t0 else ''}) | organizer {f.get('organizer')}{extra}"
    if u["doc_type"] == "slack":
        foc = u["loc"].get("focus", u["loc"]["start"])
        who = next((x["person"] for x in u["people"] if x.get("role") == "autor"), u["fields"].get("user"))
        t = u["times"][0]["local"][:16].replace("T", " ") if u["times"] else "?"
        return f"[{u['id']}] #{u['fields'].get('channel')} {t} local time · {who} · L{foc}: {lines[foc - 1].strip()}"
    return c.render(u)


PACKAGE_LIMITS = {"garage": 150_000, "card": 150_000, "calendar": 150_000, "expense": 150_000, "diligence": 150_000,
                  "slack": 100_000}


def build_packages(c: Corpus) -> list[dict]:
    order = {k: i for i, k in enumerate(FILE_ORDER)}
    units = sorted(c.units, key=lambda u: (order.get(u["doc_type"], 99), u["file"],
                                           u["loc"].get("start") or u["loc"].get("page") or u["loc"].get("row") or 0))
    pkgs, cur, size, cur_type = [], [], 0, None
    for u in units:
        txt = _compact(c, u)
        big_type = u["doc_type"] in ("garage", "card", "calendar", "slack", "expense", "diligence")
        # do not mix tables/channels with free text – better attention per package
        limit = PACKAGE_LIMITS.get(cur_type or u["doc_type"], SETTINGS.label_package_chars)
        if cur and (size + len(txt) > limit or (cur_type != u["doc_type"] and (big_type or cur_type in ("garage", "card", "calendar", "slack")))):
            pkgs.append(cur)
            cur, size = [], 0
        cur.append((u["id"], txt))
        size += len(txt) + 1
        cur_type = u["doc_type"]
    if cur:
        pkgs.append(cur)
    return [{"id": f"P{i + 1:02d}", "units": [x[0] for x in p], "text": "\n".join(x[1] for x in p)} for i, p in enumerate(pkgs)]


def _remap_id(c: Corpus, uid, pkg_ids: set):
    """Bob sometimes names a line instead of the unit (e.g. IV01-L19 instead of IV01-L17).
    Deterministic mapping to the unit with the same prefix that contains that line."""
    if uid in pkg_ids or not isinstance(uid, str):
        return uid
    m = re.match(r"^(.*)-L(\d+)$", uid)
    if not m:
        return uid
    prefix, line = m.group(1), int(m.group(2))
    for pid in pkg_ids:
        u = c.by_id[pid]
        if pid.startswith(prefix + "-L") and u["loc"]["type"] == "lines" and u["loc"]["start"] <= line <= u["loc"]["end"]:
            return pid
    return uid


def _v_label(c: Corpus, pkg_ids: set):
    def v(p: dict) -> list[str]:
        if not isinstance(p.get("units"), list):
            return ["Field 'units' missing or not a list"]
        errs = []
        bad_ids = [x.get("id") for x in p["units"] if isinstance(x, dict) and _remap_id(c, x.get("id"), pkg_ids) not in pkg_ids]
        if len(bad_ids) > max(3, 0.3 * len(p["units"])):
            errs.append(f"Unknown unit IDs (not in this package): {bad_ids[:8]}")
        evs = [{"unit": _remap_id(c, x.get("id"), pkg_ids), "quote": cl.get("quote")} for x in p["units"] if isinstance(x, dict)
               for cl in (x.get("claims") or []) if isinstance(cl, dict)]
        bad = [e for e in evs if not c.resolve(e)["ok"] and c.resolve(e)["status"] != "image"]
        if evs and len(bad) > max(3, 0.34 * len(evs)):
            errs.append(f"{len(bad)} of {len(evs)} quotes are not verbatim in the named unit, e.g.: "
                        + "; ".join(f"{e['unit']}: {str(e['quote'])[:60]!r}" for e in bad[:5]))
        return errs
    return v


def _ingest_labels(c: Corpus, pkg: dict, rec: dict, labels: dict, reviewed: dict, rejected: list):
    p = rec.get("parsed") or {}
    ids = set(pkg["units"])
    if rec["status"] in ("ok", "ok_with_warnings"):
        for uid in pkg["units"]:
            reviewed[uid] = {"call": rec["key"], "package": pkg["id"]}
    for x in p.get("units") or []:
        if not isinstance(x, dict):
            continue
        uid = _remap_id(c, x.get("id"), ids)
        if uid in labels and labels[uid].get("package") == pkg["id"]:
            # two reports for the same unit: merge the claims
            prev = labels[uid]
        else:
            prev = None
        if uid not in ids:
            rejected.append({"package": pkg["id"], "unit": uid, "reason": "unit not in package"})
            continue
        persons = []
        for pp in x.get("persons") or []:
            h = c.person_handle((pp or {}).get("id", ""))
            if h:
                persons.append({"id": h, "role": pp.get("role")})
            else:
                rejected.append({"package": pkg["id"], "unit": uid, "reason": f"unknown person: {pp}"})
        claims = []
        for cl in x.get("claims") or []:
            if not isinstance(cl, dict):
                continue
            ev = c.resolve({"unit": uid, "quote": cl.get("quote", "")})
            rel = dict(cl["relation"]) if isinstance(cl.get("relation"), dict) else None
            if rel:
                t0 = rel.get("type")
                rel["type"] = norm_rel(t0)
                if rel["type"] != t0:
                    rel["type_original"] = t0
            if rel and rel.get("type") not in REL_TYPES:
                rejected.append({"package": pkg["id"], "unit": uid, "reason": f"unknown relation type: {rel.get('type')}"})
                rel = None
            claims.append({"text": cl.get("text"), "basis": cl.get("basis") if cl.get("basis") in BASIS else "ungeprueft",
                           "evidence": ev, "relation": rel})
            if not ev["ok"] and ev["status"] != "image":
                rejected.append({"package": pkg["id"], "unit": uid, "reason": f"quote not found: {str(cl.get('quote'))[:80]}"})
        if prev:
            prev["claims"].extend(claims)
            prev["tags"] = sorted(set(prev["tags"]) | {t for t in x.get("tags") or [] if t in TAGS})
            prev["persons"].extend(pp for pp in persons if pp not in prev["persons"])
            if REL_RANK.get(x.get("relevance"), 0) > REL_RANK.get(prev["relevance"], 0):
                prev["relevance"] = x["relevance"]
            continue
        labels[uid] = {
            "relevance": x.get("relevance") if x.get("relevance") in REL_RANK else "niedrig",
            "summary": x.get("summary"), "tags": [t for t in x.get("tags") or [] if t in TAGS],
            "persons": persons, "entities": [e for e in x.get("entities") or [] if isinstance(e, dict) and e.get("name")],
            "time": x.get("time") if isinstance(x.get("time"), dict) else None, "claims": claims,
            "call": rec["key"], "package": pkg["id"], "reused": rec.get("reused", False),
            "provenance": "Bob label (AI interpretation)",
        }


def stage_label(job: Progress, force: bool = False):
    c = Corpus()
    pkgs = build_packages(c)
    job.stage("label", "Label the entire case file", len(pkgs))
    labels, reviewed, rejected = {}, {}, []
    questions = []
    pkg_meta = []
    tmpl = tpl("02_label_package.md")
    readme = next((u["raw"] for u in c.units if u["file"] == "README.md"), "")
    readme = "\n".join(sources.raw_lines("README.md"))
    people = c.people_table()
    recs = []
    lock = threading.Lock()

    def work(pkg):
        prompt = fill(tmpl, PACKAGE=f"{pkg['id']} of {len(pkgs)}", RULES=tpl("00_common_rules.md"), CASE_README=readme,
                      PEOPLE=people, MAX_UNITS=30, UNITS=pkg["text"])
        return pkg, run_bob("label", f"Label {pkg['id']} ({len(pkg['units'])} units)", prompt,
                            _v_label(c, set(pkg["units"])), reuse=not force)

    with ThreadPoolExecutor(max_workers=SETTINGS.bob_workers) as ex:
        futs = [ex.submit(work, p) for p in pkgs]
        for f in as_completed(futs):
            pkg, rec = f.result()
            with lock:
                recs.append(rec)
                _ingest_labels(c, pkg, rec, labels, reviewed, rejected)
                for q in (rec.get("parsed") or {}).get("open_questions") or []:
                    if isinstance(q, dict) and q.get("text"):
                        questions.append({**q, "package": pkg["id"]})
                pkg_meta.append({"id": pkg["id"], "units": len(pkg["units"]), "chars": len(pkg["text"]), "call": rec["key"],
                                 "status": rec["status"], "reported": len((rec.get("parsed") or {}).get("units") or []),
                                 "spend": rec.get("spend"), "reused": rec.get("reused", False), "error": rec.get("error"),
                                 "doc_types": sorted({c.by_id[i]["doc_type"] for i in pkg["units"]})})
                write_json(AN / "labels.json", labels)
                write_json(AN / "reviewed.json", reviewed)
            job.step(1, f"{pkg['id']}: {rec['status']}, {pkg_meta[-1]['reported']} units reported")
            if job.cancelled:
                ex.shutdown(cancel_futures=True)
                break
    pkg_meta.sort(key=lambda x: x["id"])
    write_json(AN / "labels.json", labels)
    write_json(AN / "reviewed.json", reviewed)
    write_json(AN / "label_packages.json", pkg_meta)
    write_json(AN / "label_rejected.json", rejected)
    write_json(AN / "label_questions.json", questions)
    _meta_update("label", recs, {"packages": len(pkgs), "labeled_units": len(labels), "reviewed_units": len(reviewed)})


# =========================================================================== 3 case frame

def _budget_join(parts: list[str], budget: int) -> tuple[str, int]:
    out, used, skipped = [], 0, 0
    for p in parts:
        if used + len(p) > budget:
            skipped += 1
            continue
        out.append(p)
        used += len(p) + 2
    return "\n\n".join(out), skipped


def _v_frame(c: Corpus):
    def v(p: dict) -> list[str]:
        errs = []
        inc = p.get("incident")
        if not isinstance(inc, dict):
            errs.append("incident missing")
        got = {c.person_handle(x.get("id", "")) for x in p.get("persons") or [] if isinstance(x, dict)}
        miss = [s for s in c.suspects if s not in got]
        if miss:
            errs.append(f"people missing in 'persons': {miss}")
        evs = _collect_evs(p)
        if evs and _ok_rate(c, evs) < 0.6:
            errs.append("More than 40 % of the quotes are not verbatim in the named unit.")
        return errs
    return v


def stage_frame(job: Progress, force: bool = False):
    c = Corpus()
    job.stage("frame", "Case frame and points of suspicion", 1)
    core_types = ("interview", "notebook", "pdf", "scan", "photo")
    core = [u for u in c.units if u["doc_type"] in core_types or u["file"] == "README.md"]
    core.sort(key=lambda u: (u["file"], u["loc"].get("start") or u["loc"].get("page") or 0))
    parts = [c.render(u, max_lines=200) for u in core]
    core_ids = {u["id"] for u in core}
    hoch = [uid for uid, l in c.labels.items() if l.get("relevance") == "hoch" and uid not in core_ids]
    mittel = [uid for uid, l in c.labels.items() if l.get("relevance") == "mittel" and uid not in core_ids]
    key = lambda uid: (c.unit_time(c.by_id[uid]) or "9999")
    hoch.sort(key=key)
    mittel.sort(key=key)
    parts += [c.render(c.by_id[uid]) + f"\nBob label: {c.labels[uid].get('summary')}" for uid in hoch]
    ctx, skipped = _budget_join(parts, 230_000)
    summ = "\n".join(c.render_label(uid) for uid in mittel)
    ctx += "\n\nFURTHER LABELS (summary only, no original lines – not quotable):\n" + summ[:40_000]
    suspects = "\n".join(f"- {n} (handle {h})" for n, h in zip(c.suspect_names, c.suspects))
    prompt = fill(tpl("03_case_frame.md"), RULES=tpl("00_common_rules.md"), SUSPECTS=suspects, PEOPLE=c.people_table(), CONTEXT=ctx)
    rec = run_bob("frame", "Case frame", prompt, _v_frame(c), reuse=not force)
    job.step(1, f"Case frame: {rec['status']}")
    if rec.get("parsed"):
        fr = _resolve_tree(c, rec["parsed"])
        for p in fr.get("persons") or []:
            p["id"] = c.person_handle(p.get("id", "")) or p.get("id")
        fr["_call"] = rec["key"]
        fr["_reused"] = rec.get("reused", False)
        fr["_context"] = {"units_with_lines": len(parts) - skipped, "skipped": skipped, "label_summaries": len(mittel)}
        write_json(AN / "frame.json", fr)
    _meta_update("frame", [rec])


# =========================================================================== 4 people

def _ev_brief(e: dict) -> dict:
    return {"unit": e.get("unit"), "quote": e.get("quote") or e.get("quote_given")}


def _frame_brief(fr: dict, h: str | None = None) -> str:
    inc = fr.get("incident") or {}
    out = {"incident": {k: inc.get(k) for k in ("summary", "window_start_local", "window_end_local", "window_note")},
           "facts": [{"text": f.get("text"), "evidence": [_ev_brief(e) for e in f.get("evidence") or [] if e.get("ok")]}
                     for f in inc.get("facts") or []],
           "knowledge_items": [{"id": k.get("id"), "text": k.get("text"), "how_known_legitimately": k.get("how_known_legitimately"),
                                "evidence": [_ev_brief(e) for e in k.get("evidence") or [] if e.get("ok")]}
                               for k in fr.get("knowledge_items") or []],
           "time_sources": [{k: t.get(k) for k in ("source", "basis", "clock_issue", "note")} for t in fr.get("time_sources") or []]}
    if h:
        me = next((p for p in fr.get("persons") or [] if p.get("id") == h), {})
        out["suspicious_for_this_person"] = [{"id": s.get("id"), "type": s.get("type"), "text": s.get("text"),
                                              "evidence": [_ev_brief(e) for e in s.get("evidence") or [] if e.get("ok")]}
                                             for s in me.get("suspicious") or []]
    return json.dumps(out, ensure_ascii=False, indent=1)


def _person_units(c: Corpus, fr: dict, h: str) -> list[str]:
    """Prioritised units for the person review (IDs, no duplicates)."""
    order: list[str] = []
    def add(uids):
        for uid in uids:
            if uid and uid in c.by_id and uid not in order:
                order.append(uid)
    # 1 own interview/follow-up in full
    own_files = {u["file"] for u in c.units if u["doc_type"] == "interview"
                 and any(x.get("person") == h and x.get("role") == "befragt" for x in u["people"])}
    add(u["id"] for u in c.units if u["file"] in own_files)
    # 2 evidence from the frame about this person and the insider knowledge
    me = next((p for p in fr.get("persons") or [] if p.get("id") == h), {})
    add(e.get("unit") for s in me.get("suspicious") or [] for e in s.get("evidence") or [])
    add(e.get("unit") for k in fr.get("knowledge_items") or [] for e in k.get("evidence") or [])
    add(e.get("unit") for f in (fr.get("incident") or {}).get("facts") or [] for e in f.get("evidence") or [])
    add(e.get("unit") for t in fr.get("time_sources") or [] for e in t.get("evidence") or [])
    # 3 units around the time window linked to the person (calendar, vehicle, card, messages)
    win = window_from_frame(fr)
    if win:
        add(u["id"] for u in c.units if h in c.unit_people(u) and c.in_window(u, *win))
    # 4 units Bob labeled as relevant and linked to the person
    lab = [uid for uid, l in c.labels.items() if l.get("relevance") in ("hoch", "mittel") and h in c.unit_people(c.by_id[uid])]
    lab.sort(key=lambda uid: (-REL_RANK.get(c.labels[uid].get("relevance"), 0), c.unit_time(c.by_id[uid]) or ""))
    add(lab)
    # 5 search terms from the frame
    for term in (me.get("search_terms") or [])[:8]:
        add(c.search(str(term), limit=8))
    # 6 mentions in other interviews
    add(u["id"] for u in c.units if u["doc_type"] == "interview" and h in c.unit_people(u))
    return order


def _v_person(c: Corpus, h: str):
    def v(p: dict) -> list[str]:
        errs = []
        if c.person_handle(p.get("person", "")) != h:
            errs.append(f"field 'person' must be {h}")
        if p.get("status") == "need_more":
            return errs
        if p.get("conclusion") not in ("entlastet", "verdacht_entkraeftet", "offen", "belastet"):
            errs.append("conclusion must be entlastet|verdacht_entkraeftet|offen|belastet")
        x = p.get("exoneration_confidence")
        if not isinstance(x, (int, float)) or not 0 <= x <= 1:
            errs.append("exoneration_confidence must be a number between 0 and 1")
        evs = _collect_evs(p)
        if evs and _ok_rate(c, evs) < 0.6:
            bad = [e for e in evs if not c.resolve(e)["ok"]][:5]
            errs.append("More than 40 % of the quotes are not verbatim in the named unit, e.g.: "
                        + "; ".join(f"{e.get('unit')}: {str(e.get('quote'))[:60]!r}" for e in bad))
        return errs
    return v


def _person_one(c: Corpus, fr: dict, h: str, force: bool) -> dict:
    name = c.person_by_id[h]["name"]
    uids = _person_units(c, fr, h)
    parts = [c.render(c.by_id[u]) for u in uids]
    ctx, skipped = _budget_join(parts, 150_000)
    sent = set(uids[:len(uids) - skipped]) if skipped == 0 else {u for u, p in zip(uids, parts) if p in ctx}
    requests_log = []

    def followup(parsed: dict) -> str | None:
        if parsed.get("status") != "need_more" or not parsed.get("requests"):
            return None
        blocks = []
        for r in parsed["requests"][:6]:
            q = str((r or {}).get("query", ""))
            ranked = c.search(q, limit=20)
            known = [x for x in ranked if x in sent][:10]
            hits = [x for x in ranked if x not in sent][:8]
            sent.update(hits)
            requests_log.append({"query": q, "why": (r or {}).get("why"), "results": hits, "already_in_context": known})
            body = "\n\n".join(c.render(c.by_id[x]) for x in hits) or "(no further hits)"
            note = (f"Matching units already in the context above: {', '.join(known)}\n" if known else "")
            blocks.append(f"=== Search results for \"{q}\" ({len(hits)} new hits)\n{note}{body}")
        return ("Here are the original passages for your requests (local full-text search over the entire case "
                "file, incl. aliases and plates). The same rules apply.\n\n<<<FILES>>>\n"
                + "\n\n".join(blocks)[:90_000] + "\n<<<END FILES>>>\n\nNow deliver the final analysis with \"status\": \"final\" "
                "in the complete JSON format.")

    prompt = fill(tpl("04_person.md"), NAME=name, ID=h, RULES=tpl("00_common_rules.md"), FRAME=_frame_brief(fr, h),
                  ROUND_NOTE=("Two steps. STEP 1 (now): reply ONLY with {\"person\": \"" + h + "\", "
                              "\"status\": \"need_more\", \"requests\": [...]} containing 3 to 6 search requests for the most important "
                              "points not yet confirmed or refuted by a document – e.g. whereabouts from interviews, legitimate "
                              "knowledge paths to insider knowledge, vehicle or card records, later corrections. Keep search terms "
                              "short and in the language of the files (mostly English, some German/Italian); person names are "
                              "expanded automatically with aliases (Slack ID, email, plate). ALIBI searches the entire case file. "
                              "STEP 2: with the hits, deliver the final analysis in the complete format (\"status\": \"final\")."),
                  CONTEXT=ctx)
    rec = run_bob("person", f"Exoneration review {name}", prompt, _v_person(c, h), reuse=not force, followup=followup)
    out = {"id": h, "name": name, "call": rec["key"], "status": rec["status"], "reused": rec.get("reused", False),
           "context_units": len(sent), "requests": requests_log or _requests_from_turns(rec), "error": rec.get("error")}
    if rec.get("parsed"):
        out["result"] = _resolve_tree(c, rec["parsed"])
    write_json(AN / "persons" / f"{h}.json", out)
    return {"rec": rec, "out": out}


def _requests_from_turns(rec: dict) -> list:
    """Rebuild source requests from a stored run (search terms + delivered units)."""
    out = []
    for t in rec.get("turns") or []:
        fp = t.get("followup_prompt")
        if not fp:
            continue
        # German (older runs) and English header format
        for block in re.split(r"=== (?:Suchergebnis für „|Search results for \")", fp)[1:]:
            q = re.split(r"“|\"", block, 1)[0]
            ids = re.findall(r"^### \[([^\]]+)\]", block, re.M)
            out.append({"query": q, "why": "(from stored Bob request)", "results": ids})
    return out


def stage_persons(job: Progress, force: bool = False, only: list[str] | None = None):
    c = Corpus()
    fr = read_json(AN / "frame.json")
    if not fr:
        raise RuntimeError("Case frame missing – run stage 'frame' first.")
    todo = [h for h in c.suspects if not only or h in only]
    job.stage("persons", "Exoneration review for all eight people", len(todo))
    recs = []
    with ThreadPoolExecutor(max_workers=SETTINGS.bob_workers) as ex:
        futs = {ex.submit(_person_one, c, fr, h, force): h for h in todo}
        for f in as_completed(futs):
            r = f.result()
            recs.append(r["rec"])
            res = (r["out"].get("result") or {})
            job.step(1, f"{r['out']['name']}: {res.get('conclusion', r['rec']['status'])}")
    _meta_update("persons", recs)


# =========================================================================== 5 verdict

def _persons_brief(c: Corpus) -> tuple[str, list[str]]:
    briefs, units = [], []
    for h in c.suspects:
        d = read_json(AN / "persons" / f"{h}.json", {})
        r = d.get("result") or {}
        def evs(lst):
            out = []
            for e in lst or []:
                if e.get("ok") or e.get("status") == "image":
                    out.append({"unit": e.get("unit"), "quote": e.get("quote"), **({"claim": e["claim_de"]} if e.get("claim_de") else {}),
                                **({"image_uncertain": True} if e.get("status") == "image" else {})})
                    units.append(e.get("unit"))
            return out
        briefs.append({
            "id": h, "name": c.person_by_id[h]["name"], "conclusion": r.get("conclusion"),
            "exoneration_confidence": r.get("exoneration_confidence"), "confidence_reason": r.get("confidence_reason"),
            "summary": r.get("summary_de"),
            "suspicious": [{"id": s.get("id"), "text": s.get("text"), "evidence": evs(s.get("evidence"))} for s in r.get("suspicious") or []],
            "explanations": [{"for": x.get("for"), "text": x.get("text"), "status": x.get("status"), "evidence": evs(x.get("evidence")),
                              "contra": [{"text": k.get("text"), "unit": k.get("unit"), "quote": k.get("quote")} for k in x.get("contra") or [] if k.get("ok")]}
                             for x in r.get("explanations") or []],
            "alibi_checks": [{"claim": a.get("claim"), "check": a.get("check"), "check_text": a.get("check_text"),
                              "claim_evidence": evs(a.get("claim_evidence")), "check_evidence": evs(a.get("check_evidence"))}
                             for a in r.get("alibi_checks") or [] if isinstance(a, dict)],
            "conditions": r.get("conditions"),
            "remaining": [{"text": s.get("text"), "evidence": evs(s.get("evidence"))} for s in r.get("remaining") or []],
            "uncertainties": r.get("uncertainties"),
        })
    return json.dumps(briefs, ensure_ascii=False, indent=1), [u for u in dict.fromkeys(units) if u]


def _akten(c: Corpus, uids: list[str], budget: int) -> str:
    parts = [c.render(c.by_id[u]) for u in uids if u in c.by_id]
    txt, _ = _budget_join(parts, budget)
    return txt


def _v_synthesis(c: Corpus):
    def v(p: dict) -> list[str]:
        errs = []
        lead = c.person_handle(p.get("leading", ""))
        if lead not in c.suspects:
            errs.append("leading must be the handle of one of the eight people")
        ws = {c.person_handle(w.get("id", "")): w.get("weight") for w in p.get("weights") or [] if isinstance(w, dict)}
        if set(c.suspects) - set(ws):
            errs.append(f"weights missing for {sorted(set(c.suspects) - set(ws))}")
        if any(not isinstance(x, (int, float)) or x < 0 or not math.isfinite(x) for x in ws.values()):
            errs.append("weights must be non-negative numbers")
        vc = p.get("verdict_confidence")
        if not isinstance(vc, (int, float)) or not 0 <= vc <= 1:
            errs.append("verdict_confidence must be between 0 and 1")
        ps = {c.person_handle(x.get("id", "")): x for x in p.get("persons") or [] if isinstance(x, dict)}
        if set(c.suspects) - set(ps):
            errs.append(f"persons missing: {sorted(set(c.suspects) - set(ps))}")
        culprits = [h for h, x in ps.items() if x.get("verdict") == "culprit"]
        if any(x.get("verdict") not in ("culprit", "cleared", "unresolved") for x in ps.values()):
            errs.append("verdict must be culprit|cleared|unresolved")
        if culprits != [lead]:
            errs.append(f"Exactly the leading person ({lead}) must have verdict 'culprit'; found: {culprits}")
        evs = _collect_evs(p)
        if evs and _ok_rate(c, evs) < 0.6:
            errs.append("More than 40 % of the quotes are not verbatim in the named unit.")
        return errs
    return v


def stage_synthesis(job: Progress, force: bool = False):
    c = Corpus()
    fr = read_json(AN / "frame.json")
    job.stage("synthesis", "Reconstruction and verdict", 1)
    pb, units = _persons_brief(c)
    fr_units = [e.get("unit") for e in _collect_evs(fr) if e.get("ok")]
    akten = _akten(c, list(dict.fromkeys(units + fr_units)), 140_000)
    prompt = fill(tpl("05_synthesis.md"), RULES=tpl("00_common_rules.md"), PERSONS=pb, FRAME=_frame_brief(fr))
    prompt += "\n\n<<<FILES>>>\n" + akten + "\n<<<END FILES>>>\n"
    rec = run_bob("synthesis", "Reconstruction and verdict", prompt, _v_synthesis(c), reuse=not force)
    job.step(1, f"Verdict: {rec['status']}")
    if rec.get("parsed"):
        s = _resolve_tree(c, rec["parsed"])
        s["leading"] = c.person_handle(s.get("leading", "")) or s.get("leading")
        raw = {c.person_handle(w.get("id", "")): float(w.get("weight") or 0) for w in s.get("weights") or [] if isinstance(w, dict)}
        raw = {h: raw.get(h, 0.0) for h in c.suspects}
        tot = sum(raw.values())
        s["weights_raw"] = raw
        s["weights_normalized"] = {h: (v / tot if tot > 0 else None) for h, v in raw.items()}
        s["weights_note"] = weights_note(tot)
        for p in s.get("persons") or []:
            p["id"] = c.person_handle(p.get("id", "")) or p.get("id")
        s["_call"], s["_reused"] = rec["key"], rec.get("reused", False)
        write_json(AN / "synthesis.json", s)
    _meta_update("synthesis", [rec])


def _v_cross(c: Corpus):
    def v(p: dict) -> list[str]:
        errs = []
        x = p.get("revised_verdict_confidence")
        if not isinstance(x, (int, float)) or not 0 <= x <= 1:
            errs.append("revised_verdict_confidence must be between 0 and 1")
        if not isinstance(p.get("holds"), bool):
            errs.append("holds must be true or false")
        for r in p.get("revisions") or []:
            if c.person_handle((r or {}).get("person", "")) not in c.suspects or r.get("verdict") not in ("culprit", "cleared", "unresolved"):
                errs.append(f"Invalid revision: {r}")
        return errs
    return v


def _synth_brief(s: dict) -> str:
    keep = {k: s.get(k) for k in ("leading", "weights", "weights_basis", "verdict_confidence", "confidence_reason", "open_questions")}
    keep["persons"] = [{"id": p.get("id"), "verdict": p.get("verdict"), "reasoning": p.get("reasoning_de"),
                        "evidence": [{"unit": e.get("unit"), "quote": e.get("quote"), "kind": e.get("kind")} for e in p.get("evidence") or [] if e.get("ok")]}
                       for p in s.get("persons") or []]
    keep["timeline"] = [{k: t.get(k) for k in ("when", "who", "what", "how", "status")} |
                        {"evidence": [{"unit": e.get("unit"), "quote": e.get("quote")} for e in t.get("evidence") or [] if e.get("ok")]}
                        for t in s.get("timeline") or []]
    return json.dumps(keep, ensure_ascii=False, indent=1)


def stage_crosscheck(job: Progress, force: bool = False):
    c = Corpus()
    s = read_json(AN / "synthesis.json")
    if not s:
        raise RuntimeError("Verdict missing – run stage 'synthesis' first.")
    job.stage("crosscheck", "Cross-check of the leading hypothesis", 1)
    pb, units = _persons_brief(c)
    s_units = [e.get("unit") for e in _collect_evs(s) if e.get("ok")]
    akten = _akten(c, list(dict.fromkeys(s_units + units)), 140_000)
    prompt = fill(tpl("06_crosscheck.md"), RULES=tpl("00_common_rules.md"), SYNTHESIS=_synth_brief(s), PERSONS=pb, CONTEXT=akten)
    rec = run_bob("crosscheck", "Cross-check", prompt, _v_cross(c), reuse=not force)
    job.step(1, f"Cross-check: {rec['status']}")
    if rec.get("parsed"):
        x = _resolve_tree(c, rec["parsed"])
        x["_call"], x["_reused"] = rec["key"], rec.get("reused", False)
        write_json(AN / "crosscheck.json", x)
        build_final(c)
    _meta_update("crosscheck", [rec])


def build_final(c: Corpus | None = None) -> dict | None:
    """Deterministic merge of verdict and cross-check (both from Bob)."""
    c = c or Corpus()
    s = read_json(AN / "synthesis.json")
    x = read_json(AN / "crosscheck.json")
    if not s:
        return None
    notes = []
    persons = {p["id"]: dict(p) for p in s.get("persons") or [] if p.get("id") in c.suspects}
    for h in c.suspects:
        persons.setdefault(h, {"id": h, "verdict": "unresolved", "reasoning_de": "No assessment in the verdict.", "evidence": []})
    conf = s.get("verdict_confidence")
    if x:
        for r in x.get("revisions") or []:
            h = c.person_handle(r.get("person", ""))
            if h in persons and r.get("verdict") in ("culprit", "cleared", "unresolved") and persons[h].get("verdict") != r["verdict"]:
                notes.append(f"Cross-check changes {c.person_by_id[h]['name']}: {persons[h].get('verdict')} → {r['verdict']} ({r.get('why')})")
                persons[h]["verdict"] = r["verdict"]
                persons[h]["revised_by_crosscheck"] = r.get("why")
        if isinstance(x.get("revised_verdict_confidence"), (int, float)):
            conf = float(x["revised_verdict_confidence"])
    lead = s.get("leading")
    culprits = [h for h, p in persons.items() if p.get("verdict") == "culprit"]
    if len(culprits) == 1:
        if culprits[0] != lead:
            notes.append(f"Leading hypothesis after cross-check: {c.person_by_id[culprits[0]]['name']}")
        lead = culprits[0]
    elif len(culprits) == 0:
        notes.append("After the cross-check no person carries the verdict 'culprit'. The required field 'culprit' uses the "
                     "leading hypothesis of the verdict; the low verdict confidence reflects this.")
        persons[lead]["verdict"] = "culprit"
        persons[lead]["forced_by_format"] = True
    else:
        for h in culprits:
            if h != lead:
                persons[h]["verdict"] = "unresolved"
                notes.append(f"{c.person_by_id[h]['name']}: second 'culprit' verdict → unresolved (only one person can be the culprit).")
    final = {"leading": lead, "verdict_confidence": conf, "verdict_confidence_synthesis": s.get("verdict_confidence"),
             "confidence_reason": s.get("confidence_reason"), "crosscheck": x, "persons": [persons[h] for h in c.suspects],
             "weights_normalized": s.get("weights_normalized"), "weights": s.get("weights"), "weights_note": s.get("weights_note"),
             "weights_basis": s.get("weights_basis"), "timeline": s.get("timeline"), "chains": s.get("chains"),
             "dismissed": s.get("dismissed"), "open_questions": s.get("open_questions"), "merge_notes": notes,
             "built_at": now()}
    write_json(AN / "final.json", final)
    return final


# =========================================================================== 6 prevention

def _v_prev(c: Corpus):
    def v(p: dict) -> list[str]:
        ms = p.get("measures")
        if not isinstance(ms, list) or not ms:
            return ["measures missing"]
        errs = [f"invalid category: {m.get('category')}" for m in ms if m.get("category") not in ("zugriff", "kopie", "erkennung", "untersuchung")]
        return errs
    return v


def stage_prevention(job: Progress, force: bool = False):
    c = Corpus()
    f = read_json(AN / "final.json") or build_final(c)
    if not f:
        raise RuntimeError("Verdict missing – run stage 'synthesis' first.")
    job.stage("prevention", "Prevention measures", 1)
    tl = [{"index": i, **{k: t.get(k) for k in ("when", "who", "what", "how", "status")},
           "evidence": [{"unit": e.get("unit"), "quote": e.get("quote")} for e in t.get("evidence") or [] if e.get("ok")]}
          for i, t in enumerate(f.get("timeline") or [])]
    units = [e["unit"] for t in tl for e in t["evidence"]]
    units += [e.get("unit") for e in _collect_evs(f.get("chains")) if e.get("ok")]
    akten = _akten(c, list(dict.fromkeys(units)), 90_000)
    prompt = fill(tpl("07_prevention.md"), RULES=tpl("00_common_rules.md"), CONFIDENCE=f.get("verdict_confidence"),
                  TIMELINE=json.dumps({"timeline": tl, "leading": f.get("leading")}, ensure_ascii=False, indent=1), CONTEXT=akten)
    rec = run_bob("prevention", "Prevention", prompt, _v_prev(c), reuse=not force)
    job.step(1, f"Prevention: {rec['status']}")
    if rec.get("parsed"):
        p = _resolve_tree(c, rec["parsed"])
        p["_call"], p["_reused"] = rec["key"], rec.get("reused", False)
        write_json(AN / "prevention.json", p)
    _meta_update("prevention", [rec])


# =========================================================================== 7 Export

def stage_export(job: Progress, force: bool = False):
    from .export import build_draft
    job.stage("export", "Export draft and validation", 1)
    d = build_draft()
    job.step(1, "Export draft: " + ("valid" if d["report"]["valid"] else "invalid – see report"))


STAGE_FUNCS = {"vision": stage_vision, "label": stage_label, "frame": stage_frame, "persons": stage_persons,
               "synthesis": stage_synthesis, "crosscheck": stage_crosscheck, "prevention": stage_prevention, "export": stage_export}


def stage_done(k: str) -> bool:
    """Is a stored result for this stage already present?"""
    c_units = read_json(AN.parent / "units.json", [])
    if k == "vision":
        v = read_json(AN / "vision.json", {})
        return all(u["id"] in v for u in c_units if u["doc_type"] in ("scan", "photo"))
    if k == "label":
        return len(read_json(AN / "reviewed.json", {})) >= len(c_units) > 0
    if k == "persons":
        from .config import template_names
        from .ingest import People
        return all((read_json(AN / "persons" / f"{People.handle_from_name(n)}.json", {}) or {}).get("result")
                   for n in template_names())
    files = {"frame": "frame.json", "synthesis": "synthesis.json", "crosscheck": "crosscheck.json", "prevention": "prevention.json"}
    return k in files and (AN / files[k]).exists()


def run_pipeline(job: Progress, stages: list[str] | None = None, force: bool = False):
    """Without explicit stages ("continue"), stages with stored results are skipped – no Bob cost."""
    explicit = stages is not None
    todo = stages or [k for k, _ in STAGES]
    for k in todo:
        if job.cancelled:
            job.log("Cancelled.")
            return
        if not explicit and not force and k != "export" and stage_done(k):
            job.log(f"{dict(STAGES)[k]}: stored result present – skipped (no Bob call)")
            continue
        STAGE_FUNCS[k](job, force=force)
