"""Independent validator for verdict.json.

Deliberately does not use the pipeline or the evidence resolution: reads the
template and the original files itself and checks structure, consistency and
every quote at its cited location.

Usage:  python -m alibi.validator <verdict.json> [--bundle PATH] [--template PATH]
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

VERDICTS = {"culprit", "cleared", "unresolved"}
TOP_KEYS = {"team", "culprit", "confidence", "suspects"}
SUSPECT_KEYS = {"name", "verdict", "reasoning", "evidence"}
EVIDENCE_KEYS = {"claim", "source", "quote"}
PLACEHOLDERS = {"culprit | cleared | unresolved", "One or two sentences on why.", "What this line shows",
                "exact text copied from that line", "file_name.md:LINE", "your-team-name",
                "Full Name of the person you think did it"}
TEXT_EXT = {".md", ".txt", ".json", ".csv", ".mbox", ".ics"}
IMAGE_EXT = {".jpg", ".jpeg", ".png"}


def _lines(p: Path) -> list[str]:
    parts = p.read_bytes().split(b"\n")
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    return [(b[:-1] if b.endswith(b"\r") else b).decode("utf-8") for b in parts]


def check_source(bundle: Path, source: str, quote: str) -> dict:
    m = re.match(r"^(?P<path>[^:]+?)(?::(?P<a>\d+)(?:-(?P<b>\d+))?)?$", source or "")
    if not m:
        return {"ok": False, "status": "unreadable_source"}
    rel = m.group("path")
    if rel.startswith("/") or ".." in Path(rel).parts:
        return {"ok": False, "status": "path_not_relative"}
    p = (bundle / rel)
    if not p.is_file():
        return {"ok": False, "status": "file_missing"}
    a = int(m.group("a")) if m.group("a") else None
    b = int(m.group("b")) if m.group("b") else a
    ext = p.suffix.lower()
    if not quote or not quote.strip():
        return {"ok": False, "status": "empty_quote"}
    if ext in TEXT_EXT:
        if a is None:
            return {"ok": False, "status": "line_missing"}
        ls = _lines(p)
        if not (1 <= a <= b <= len(ls)):
            return {"ok": False, "status": "line_out_of_range"}
        seg = ls[a - 1:b]
        ok = any(quote in s for s in seg) or quote in "\n".join(seg)
        return {"ok": ok, "status": "exact" if ok else "quote_not_found"}
    if ext == ".pdf":
        from pypdf import PdfReader
        pages = PdfReader(str(p)).pages
        if a is None or a != b or not 1 <= a <= len(pages):
            return {"ok": False, "status": "invalid_page"}
        text = pages[a - 1].extract_text() or ""
        if quote in text:
            return {"ok": True, "status": "exact"}
        ws = lambda s: re.sub(r"\s+", " ", s).strip()
        if ws(quote) in ws(text):
            return {"ok": True, "status": "exact_except_whitespace"}
        return {"ok": False, "status": "quote_not_found" if text.strip() else "pdf_without_text_layer"}
    if ext == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        ws_ = wb.worksheets[0]
        rows = list(ws_.iter_rows(values_only=True))
        wb.close()
        if a is None or a != b or not 1 <= a <= len(rows):
            return {"ok": False, "status": "invalid_excel_row"}
        cells = [str(int(v)) if isinstance(v, float) and v.is_integer() else str(v) for v in rows[a - 1] if v is not None]
        ok = any(quote in cval for cval in cells)
        return {"ok": ok, "status": "exact" if ok else "quote_not_found"}
    if ext in IMAGE_EXT:
        return {"ok": False, "status": "image_quote_not_verifiable"}
    return {"ok": False, "status": "unknown_file_type"}


def validate_verdict(obj, bundle: Path, template: Path) -> dict:
    errors, warnings, checks = [], [], []
    names = [s["name"] for s in json.loads(template.read_text(encoding="utf-8"))["suspects"]]
    if not isinstance(obj, dict):
        return {"valid": False, "errors": ["Root is not a JSON object"], "warnings": [], "evidence_checks": []}
    if set(obj) != TOP_KEYS:
        errors.append(f"Top level must contain exactly {sorted(TOP_KEYS)}, found {sorted(obj)}")
    team = obj.get("team")
    if not isinstance(team, str) or not team.strip() or team in PLACEHOLDERS:
        errors.append("team missing or placeholder")
    conf = obj.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf) or not 0 <= conf <= 1:
        errors.append("confidence must be a finite number between 0 and 1")
    culprit = obj.get("culprit")
    if culprit not in names:
        errors.append(f"culprit must be one of the eight names, found {culprit!r}")
    sus = obj.get("suspects")
    if not isinstance(sus, list):
        errors.append("suspects must be a list")
        sus = []
    got = [s.get("name") for s in sus if isinstance(s, dict)]
    for n in names:
        if got.count(n) != 1:
            errors.append(f"{n} must appear exactly once (found {got.count(n)}×)")
    for n in got:
        if n not in names:
            errors.append(f"Unknown person in suspects: {n!r}")
    culprits = []
    for s in sus:
        if not isinstance(s, dict):
            errors.append("Entry in suspects is not an object")
            continue
        n = s.get("name")
        if set(s) != SUSPECT_KEYS:
            errors.append(f"{n}: fields must be exactly {sorted(SUSPECT_KEYS)}, found {sorted(s)}")
        v = s.get("verdict")
        if v not in VERDICTS:
            errors.append(f"{n}: verdict {v!r} invalid")
        if v == "culprit":
            culprits.append(n)
        r = s.get("reasoning")
        if not isinstance(r, str) or not r.strip() or r in PLACEHOLDERS:
            errors.append(f"{n}: reasoning missing or placeholder")
        elif len(r) > 450 or len(re.findall(r"[.!?](\s|$)", r)) > 3:
            warnings.append(f"{n}: reasoning is longer than \"one or two sentences\"")
        evs = s.get("evidence")
        if not isinstance(evs, list):
            errors.append(f"{n}: evidence must be a list")
            evs = []
        verified = 0
        for i, e in enumerate(evs):
            if not isinstance(e, dict) or set(e) != EVIDENCE_KEYS:
                errors.append(f"{n} evidence {i + 1}: fields must be exactly claim/source/quote")
                continue
            if not isinstance(e.get("claim"), str) or not e["claim"].strip() or e["claim"] in PLACEHOLDERS:
                errors.append(f"{n} evidence {i + 1}: claim missing or placeholder")
            chk = check_source(bundle, str(e.get("source")), str(e.get("quote") or ""))
            checks.append({"name": n, "index": i, "source": e.get("source"), "quote": e.get("quote"), **chk})
            if chk["ok"]:
                verified += 1
            else:
                errors.append(f"{n} evidence {i + 1}: {chk['status']} ({e.get('source')})")
        if v == "cleared" and verified == 0:
            errors.append(f"{n}: cleared without verified evidence")
        if v == "culprit" and verified == 0:
            errors.append(f"{n}: culprit verdict without verified evidence")
    if len(culprits) != 1:
        errors.append(f"Exactly one person must have verdict 'culprit', found {culprits}")
    elif culprit != culprits[0]:
        errors.append(f"culprit ({culprit}) does not match the person verdict ({culprits[0]})")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "evidence_checks": checks,
            "verified_quotes": sum(1 for c in checks if c["ok"]), "total_quotes": len(checks)}


def main(argv=None):
    import argparse
    here = Path(__file__).resolve()
    repo = here.parents[4]
    ap = argparse.ArgumentParser(description="ALIBI export validator")
    ap.add_argument("verdict")
    ap.add_argument("--bundle", default=None)
    ap.add_argument("--template", default=str(repo / "verdict_template.json"))
    a = ap.parse_args(argv)
    if a.bundle:
        bundle = Path(a.bundle)
    else:
        from .config import SETTINGS
        bundle = SETTINGS.bundle
    obj = json.loads(Path(a.verdict).read_text(encoding="utf-8"))
    rep = validate_verdict(obj, bundle, Path(a.template))
    print(f"Valid: {rep['valid']} · quotes verified: {rep['verified_quotes']}/{rep['total_quotes']}")
    for e in rep["errors"]:
        print("  ERROR:", e)
    for w in rep["warnings"]:
        print("  Note:", w)
    return 0 if rep["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
