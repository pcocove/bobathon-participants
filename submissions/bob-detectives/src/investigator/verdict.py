"""Stage 8 — verdict.json, built only from verified evidence, then re-verified."""

from __future__ import annotations

import json
from pathlib import Path

from .corpus import Corpus
from .engine import Investigation
from .findings import Evidence, Finding

MAX_EVIDENCE = {"culprit": 10, "cleared": 4, "unresolved": 4}


def _usable(inv: Investigation, e: Evidence) -> Evidence | None:
    if e.usable:
        return e
    if e.status == "ocr":
        d = inv.tasks.decision("human", "ocr", e.source)
        if d and d["decision"] == "confirm":
            return e
        if d and d["decision"] == "correct" and d.get("text"):
            return Evidence(e.source, d["text"], e.note, "human-confirmed", True)
    return None


def _items(inv: Investigation, findings: list[Finding], limit: int, per_finding: int = 2) -> list[dict]:
    out, seen = [], set()
    for f in findings:
        n = 0
        for e in f.evidence:
            u = _usable(inv, e)
            if not u or (u.source, u.quote) in seen or not u.quote:
                continue
            seen.add((u.source, u.quote))
            claim = f.title if not e.note else f"{f.title} — {e.note}"
            out.append({"claim": claim, "source": u.source, "quote": u.quote})
            n += 1
            if n >= per_finding or len(out) >= limit:
                break
        if len(out) >= limit:
            break
    return out


def _reasoning(inv: Investigation, prof: dict, verdict: str, res: dict) -> str:
    p = inv.person(prof["key"])
    fs = inv.store.for_suspect(p.key)
    if verdict == "culprit":
        parts = []
        if prof["presence"] == "on site":
            parts.append("car on site through the whole copy window")
        if prof["statement"] == "contradicted":
            parts.append("own account of leaving is contradicted by card and barrier records")
        if prof["echo"] == "unexplained":
            parts.append("described withheld details of the copy before any record or leak could have told them")
        if prof["knowledge"] == "route":
            parts.append("had a documented route to which artifacts were real")
        if prof["link"] == "direct":
            parts.append("ran the contact with the party that received the model")
        gaps = [x["title"] for x in res["confidence_formula"]["penalties"]][:2]
        s = "Only suspect still standing: " + "; ".join(parts) + "."
        if gaps:
            s += " Open points: " + "; ".join(gaps) + "."
        return s
    ex = next((f for f in fs if f.cls == "PROVES_INNOCENCE"), None)
    if verdict == "cleared" and ex:
        s = f"Physically elsewhere: {ex.claim}"
    else:
        greens = sorted([f for f in fs if f.cls == "EXONERATES"], key=lambda f: f.score)
        s = "Lowered: " + "; ".join(f.title.lower() for f in greens[:2]) + "." if greens else "No decisive record either way."
    if prof["misleading"]:
        route = next((f for f in fs if f.explains), None)
        if route:
            s += f" Seemed to know withheld details, but {route.title[len('Innocent route: '):] if route.title.startswith('Innocent route: ') else route.title}."
    if verdict == "cleared" and not ex:
        s += " No unexplained incriminating record, and a single operator is established elsewhere."
    if verdict == "unresolved":
        s += " Not enough paperwork to clear."
    return s[:400]


def build(inv: Investigation, team: str, baseline: bool = False) -> dict:
    res = inv.results["baseline" if baseline else "argue"]
    prev = inv.store.include_proposed
    inv.store.include_proposed = baseline or inv.ws.mode == "autopilot"
    try:
        return _build(inv, team, res, baseline)
    finally:
        inv.store.include_proposed = prev


def _build(inv: Investigation, team: str, res: dict, baseline: bool) -> dict:
    suspects = []
    for prof in res["profiles"]:
        p = inv.person(prof["key"])
        v = prof["verdict"]
        fs = inv.store.for_suspect(p.key)
        if v == "culprit":
            order = sorted([f for f in fs if f.cls in ("INCRIMINATES", "WEAKLY_INCRIMINATES") and f.constraint != "lead"],
                           key=lambda f: -f.score)
        else:
            green = sorted([f for f in fs if f.cls in ("PROVES_INNOCENCE", "EXONERATES")], key=lambda f: f.score)
            susp = [f for f in fs if f.constraint == "echo" and f.cls == "WEAKLY_INCRIMINATES"]
            # the misleading part first: suspicion, then its explanation
            order = []
            for s in susp:
                order.append(s)
                order += [f for f in green if f.explains == s.key]
            order += [f for f in green if f not in order]
            if v == "unresolved":
                order += sorted([f for f in fs if f.cls in ("INCRIMINATES", "WEAKLY_INCRIMINATES")], key=lambda f: -f.score)
        draft = prof.get("draft")
        if draft:
            # the agent's own citations first, then the strongest supporting findings
            cited = [f for f in (inv.store.by_id(c) for c in draft.get("cites", [])) if f is not None and f.counts]
            order = cited + [f for f in order if f not in cited]
        suspects.append({
            "name": p.name, "verdict": v,
            "reasoning": (draft["reasoning"][:600] if draft else _reasoning(inv, prof, v, res)),
            "evidence": _items(inv, order, MAX_EVIDENCE.get(v, 4)),
        })
    # keep the template's order
    names = inv.case.suspect_names
    suspects.sort(key=lambda s: names.index(s["name"]) if s["name"] in names else 99)
    out = {"team": team, "culprit": res["culprit_name"] or "", "confidence": res["confidence"], "suspects": suspects}
    return out


def verify_file(corpus: Corpus, verdict: dict) -> dict:
    rows = []
    for s in verdict.get("suspects", []):
        for e in s.get("evidence", []):
            r = corpus.verify(e.get("source", ""), e.get("quote", ""))
            rows.append({"suspect": s.get("name"), **{k: r.get(k) for k in ("source", "quote", "status", "detail", "suggestion")}})
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    names_ok = len(verdict.get("suspects", [])) == 8 or None
    return {"total": len(rows), "counts": counts, "rows": rows,
            "all_verified": all(r["status"] in ("verified",) for r in rows),
            "suspects": len(verdict.get("suspects", [])), "eight_suspects": names_ok}


def write(inv: Investigation, verdict: dict, name: str = "verdict.json") -> tuple[Path, dict]:
    out = inv.paths.output
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    if name != "verdict.json":
        path.write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path, verify_file(inv.corpus, verdict)
    path.write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = verify_file(inv.corpus, verdict)
    (out / "verification.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    inv.results["verification"] = report
    inv.stage("verdict", f"{report['total']} quotes, {report['counts']}")
    return path, report
