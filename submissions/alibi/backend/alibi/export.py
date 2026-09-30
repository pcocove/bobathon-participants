"""Competition export: build a draft, validate independently, write atomically.

Deterministic safety rules (no content conclusions):
- only evidence with an exactly verified quote on a single line/page/Excel row;
- image/OCR evidence is never exported (cannot be verified exactly);
- "cleared" without verified evidence is exported as "unresolved";
- no fields beyond the format of verdict_template.json.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import SETTINGS
from .corpus import AN, Corpus
from .store import read_json, write_json
from .validator import validate_verdict

MAX_EVIDENCE = 4


def _claim(e: dict) -> str:
    return (e.get("claim_en") or e.get("claim") or e.get("claim_de") or e.get("text") or "").strip()


def build_draft(write: bool = True) -> dict:
    c = Corpus()
    f = read_json(AN / "final.json")
    notes = []
    if not f:
        d = {"status": "no_analysis", "draft": None, "notes": ["No Bob analysis yet – no export possible."],
             "report": {"valid": False, "errors": ["No analysis available"], "warnings": [], "evidence_checks": []}}
        if write:
            write_json(AN / "verdict_draft.json", d)
        return d
    persons = {p["id"]: p for p in f.get("persons") or []}
    suspects = []
    for name, h in zip(c.suspect_names, c.suspects):
        p = persons.get(h, {})
        ev, seen = [], set()
        pool = list(p.get("evidence") or [])
        # fall back to the person review if the verdict has too little exportable evidence
        pr = (read_json(AN / "persons" / f"{h}.json", {}) or {}).get("result") or {}
        if p.get("verdict") == "cleared":
            pool += [e for x in pr.get("explanations") or [] if x.get("status") in ("belegt", "teilweise_belegt") for e in x.get("evidence") or []]
        elif p.get("verdict") == "culprit":
            pool += [e for x in pr.get("remaining") or [] for e in x.get("evidence") or []]
        dropped = 0
        for e in pool:
            if not e.get("exportable"):
                dropped += 1
                continue
            k = (e["source"], e["quote"])
            if k in seen or not _claim(e):
                continue
            seen.add(k)
            ev.append({"claim": _claim(e), "source": e["source"], "quote": e["quote"]})
            if len(ev) >= MAX_EVIDENCE:
                break
        if dropped:
            notes.append(f"{name}: {dropped} evidence item(s) not exported (quote not exactly verified, multi-line or image source).")
        verdict = p.get("verdict") or "unresolved"
        if verdict == "cleared" and not ev:
            verdict = "unresolved"
            notes.append(f"{name}: cleared without verified evidence → exported as \"unresolved\" (safety rule).")
        reasoning = (p.get("reasoning_en") or p.get("reasoning_de") or "").strip()
        if len(reasoning) > 420:
            reasoning = reasoning[:417].rsplit(" ", 1)[0] + "…"
        suspects.append({"name": name, "verdict": verdict, "reasoning": reasoning, "evidence": ev})
    lead = f.get("leading")
    culprit = c.person_by_id[lead]["name"] if lead in c.person_by_id else None
    # names exactly as in the template
    if lead in c.suspects:
        culprit = c.suspect_names[c.suspects.index(lead)]
    conf = f.get("verdict_confidence")
    obj = {"team": SETTINGS.team, "culprit": culprit,
           "confidence": round(float(conf), 2) if isinstance(conf, (int, float)) else None, "suspects": suspects}
    report = validate_verdict(obj, SETTINGS.bundle, SETTINGS.template)
    d = {"status": "DRAFT", "draft": obj, "report": report, "notes": notes + (f.get("merge_notes") or []),
         "built_at": datetime.now(timezone.utc).isoformat()}
    if write:
        write_json(AN / "verdict_draft.json", d)
    return d


def write_final() -> dict:
    d = build_draft()
    if not d["report"]["valid"]:
        return {"written": False, "reason": "Draft is not valid", "report": d["report"]}
    path = SETTINGS.verdict_path
    write_json(path, d["draft"], indent=2)
    # cross-check: validate the written file again independently
    rep = validate_verdict(read_json(path), SETTINGS.bundle, SETTINGS.template)
    meta = read_json(AN / "meta.json", {})
    meta["export"] = {"written_at": datetime.now(timezone.utc).isoformat(), "path": str(path.relative_to(SETTINGS.team_dir.parents[1])),
                      "valid": rep["valid"]}
    write_json(AN / "meta.json", meta)
    return {"written": rep["valid"], "path": str(path), "report": rep}
