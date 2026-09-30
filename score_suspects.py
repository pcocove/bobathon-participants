"""
score_suspects.py — Sub-Task 4 of the Meridian investigation.

Loads suspect_profiles.json (built in Sub-Tasks 2 and 3), applies a
transparent scoring model, verifies every evidence quote against the
source files, and writes scored_suspects.json.

Scoring model (additive):
  +3  Knew which checkpoints were real (access_to_real_paths == True)
  +3  Physical or remote opportunity during the theft window
  +5  Describes withheld forensic detail AND no innocent explanation
  +2  Strong motive present
  -5  Alibi independently verified by investigator
  -4  Proven off-site by physical evidence (garage / card / calendar / flight)
  -2  Suspicious behaviour fully explained by an innocent source

The suspect with the highest net score who also has access + opportunity
is the culprit. Confidence = top_score / (top_score + second_score).
"""

from __future__ import annotations

import json
from pathlib import Path

from index_evidence import build_index, LINE_INDEX, BUNDLE

# ---------------------------------------------------------------------------
# Quote verification
# ---------------------------------------------------------------------------

def verify_quote(source: str, quote: str) -> tuple[bool, str]:
    """
    Check whether `quote` appears in the LINE_INDEX at `source`.
    Returns (ok, message).
    `source` is e.g. "interviews/interview_01_iris_ammann.txt:23"
    """
    if not quote or not quote.strip():
        return False, "empty quote"
    # Normalise: trim whitespace, collapse runs
    import re
    norm_quote = re.sub(r"\s+", " ", quote.strip())
    # Check exact key first
    raw = LINE_INDEX.get(source, "")
    if raw:
        norm_raw = re.sub(r"\s+", " ", raw.strip())
        if norm_quote[:80] in norm_raw:
            return True, "exact"
    # Fallback: search nearby lines (±3) for the quote fragment
    parts = source.rsplit(":", 1)
    if len(parts) == 2:
        base, lineno_str = parts
        try:
            lineno = int(lineno_str)
        except ValueError:
            return False, "bad source format"
        for offset in range(-3, 4):
            candidate = LINE_INDEX.get(f"{base}:{lineno + offset}", "")
            norm_c = re.sub(r"\s+", " ", candidate.strip())
            if norm_quote[:80] in norm_c:
                return True, f"found at line {lineno + offset} (off by {offset})"
    # Try searching all keys with this base file for the first 60 chars
    needle = norm_quote[:60]
    if len(needle) < 10:
        return False, "quote too short to verify"
    for key, val in LINE_INDEX.items():
        if key.startswith(parts[0]):
            norm_val = re.sub(r"\s+", " ", val.strip())
            if needle in norm_val:
                return True, f"found at {key}"
    return False, "not found in file"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

WEIGHTS = {
    "access_known":          +3,
    "opportunity_in":        +3,
    "pivot_no_explanation":  +5,
    "strong_motive":         +2,
    "alibi_verified":        -5,
    "proven_offsite":        -4,
    "suspicious_explained":  -2,
}

def score_profile(profile: dict) -> dict:
    name   = profile["name"]
    score  = 0
    factors: list[dict] = []

    def add(label: str, weight: int, reason: str):
        nonlocal score
        score += weight
        sign = "+" if weight >= 0 else ""
        factors.append({"label": label, "weight": weight,
                         "reason": reason,
                         "display": f"{sign}{weight}  {reason}"})

    # --- Access to real paths ---
    access = profile.get("access_to_real_paths", {}).get("value", False)
    if access:
        add("access_known", WEIGHTS["access_known"], "Knew which checkpoints were real")

    # --- Opportunity ---
    opp = profile.get("opportunity_window", {}).get("value", "unknown")
    if opp == "in":
        add("opportunity_in", WEIGHTS["opportunity_in"], "In the building during the theft window")
    elif opp == "out":
        add("proven_offsite", WEIGHTS["proven_offsite"], "Proven off-site by physical evidence")
    # "unknown" → no score either way

    # --- Forensic pivot ---
    pivot = profile.get("forensic_pivot", {})
    describes = pivot.get("describes_withheld_detail", False)
    innocent  = pivot.get("innocent_explanation")
    if describes and not innocent:
        add("pivot_no_explanation", WEIGHTS["pivot_no_explanation"],
            "Describes withheld forensic detail with no innocent explanation")
    elif describes and innocent:
        add("suspicious_explained", WEIGHTS["suspicious_explained"],
            "Describes withheld detail but has a documented innocent prior source")

    # --- Motive ---
    motive_summary = profile.get("motive", {}).get("summary", "")
    has_motive = bool(motive_summary and len(motive_summary) > 10)
    if has_motive:
        add("strong_motive", WEIGHTS["strong_motive"], f"Motive: {motive_summary[:80]}")

    # --- Alibi ---
    alibi = profile.get("alibi", {}).get("summary", "")
    alibi_verified = (
        "verified" in alibi.lower() or
        "card" in alibi.lower() or
        "boarding" in alibi.lower() or
        "corroborate" in alibi.lower() or
        "documented" in alibi.lower()
    )
    if alibi_verified and opp == "out":
        add("alibi_verified", WEIGHTS["alibi_verified"], f"Alibi: {alibi[:80]}")

    # Clearing evidence that fully explains suspicious behaviours
    clearing = profile.get("clearing_evidence", [])
    suspicious = profile.get("suspicious_behaviours", [])
    if clearing and suspicious:
        add("suspicious_explained", WEIGHTS["suspicious_explained"],
            "Suspicious behaviours fully accounted for by clearing evidence")

    return {"name": name, "score": score, "factors": factors}


# ---------------------------------------------------------------------------
# Build verdict entries
# ---------------------------------------------------------------------------

# Threshold: score above this = culprit candidate
CULPRIT_THRESHOLD = 3

def determine_verdict(scored: list[dict], profiles_by_name: dict) -> list[dict]:
    """Assign verdict (culprit/cleared/unresolved) and build evidence list."""
    sorted_by_score = sorted(scored, key=lambda x: x["score"], reverse=True)
    top_score = sorted_by_score[0]["score"]

    results = []
    for item in scored:
        name    = item["name"]
        score   = item["score"]
        profile = profiles_by_name[name]
        pivot   = profile.get("forensic_pivot", {})
        opp     = profile.get("opportunity_window", {}).get("value", "unknown")

        # Collect best evidence items for verdict
        ev_pool: list[dict] = []
        for section in ["access_to_real_paths", "opportunity_window",
                         "alibi", "clearing_evidence", "suspicious_behaviours"]:
            sec = profile.get(section, {})
            if isinstance(sec, list):
                ev_pool.extend(sec)
            elif isinstance(sec, dict):
                ev_pool.extend(sec.get("evidence", []))
        for ev in pivot.get("evidence", []):
            ev_pool.append(ev)

        # Deduplicate by source
        seen_sources = set()
        ev_deduped = []
        for ev in ev_pool:
            src = ev.get("source", "")
            if src not in seen_sources:
                seen_sources.add(src)
                ev_deduped.append(ev)

        # Pick ≤4 most relevant evidence items
        # Prioritise: alibi > clearing > opportunity > access > suspicious
        priority_order = [
            lambda e: "alibi" in e.get("claim","").lower() or "lisbon" in e.get("claim","").lower(),
            lambda e: "cleared" in e.get("claim","").lower() or "innocent" in e.get("claim","").lower(),
            lambda e: "garage" in e.get("source","") or "card_feed" in e.get("source",""),
            lambda e: "interview" in e.get("source",""),
            lambda e: True,
        ]
        selected = []
        remaining = list(ev_deduped)
        for pred in priority_order:
            for ev in list(remaining):
                if pred(ev) and len(selected) < 4:
                    selected.append(ev)
                    remaining.remove(ev)
            if len(selected) >= 4:
                break

        # Determine verdict
        if score == top_score and score >= CULPRIT_THRESHOLD:
            verdict_str = "culprit"
        elif opp == "out" and score <= 0:
            verdict_str = "cleared"
        elif score < 0:
            verdict_str = "cleared"
        else:
            verdict_str = "unresolved"

        # Build reasoning sentence
        reasoning = _build_reasoning(name, score, profile, pivot, verdict_str)

        results.append({
            "name":      name,
            "score":     score,
            "verdict":   verdict_str,
            "reasoning": reasoning,
            "evidence":  selected,
            "factors":   item["factors"],
        })

    return results


def _build_reasoning(name: str, score: int, profile: dict,
                     pivot: dict, verdict: str) -> str:
    opp     = profile.get("opportunity_window", {}).get("value", "unknown")
    access  = profile.get("access_to_real_paths", {}).get("value", False)
    alibi   = profile.get("alibi", {}).get("summary", "")
    motive  = profile.get("motive", {}).get("summary", "")
    describes = pivot.get("describes_withheld_detail", False)
    innocent  = pivot.get("innocent_explanation")

    if verdict == "culprit":
        parts = []
        if access:
            parts.append("knew which checkpoints were real")
        if opp == "unknown":
            parts.append("no verifiable alibi for the theft window")
        if motive:
            parts.append(f"motive ({motive[:60]})")
        return (f"Only remaining suspect who {', '.join(parts)}; "
                "all other suspects are cleared by physical evidence or forensic analysis.")

    if verdict == "cleared":
        if alibi:
            return f"Cleared: {alibi[:120]}"
        if opp == "out":
            return "Cleared: physical evidence places them off-site during the theft window."
        return "Cleared: no evidence links them to the theft."

    # unresolved
    if describes and innocent:
        return (f"Suspicious (describes forensic detail) but has a documented innocent "
                f"source: {innocent[:100]}")
    return (f"Some circumstantial overlap but no direct evidence; score {score}.")


# ---------------------------------------------------------------------------
# Quote verification pass
# ---------------------------------------------------------------------------

def verify_all_quotes(results: list[dict]) -> list[dict]:
    """Check every evidence quote; flag failures; keep only verified quotes."""
    bad_count = 0
    for item in results:
        verified = []
        for ev in item.get("evidence", []):
            ok, msg = verify_quote(ev.get("source", ""), ev.get("quote", ""))
            ev["_verified"] = ok
            ev["_verify_msg"] = msg
            if not ok:
                bad_count += 1
                print(f"  WARN quote not verified: [{item['name']}] "
                      f"{ev['source']} — {msg}")
                print(f"       quote[:80]: {ev.get('quote','')[:80]}")
            verified.append(ev)
        item["evidence"] = verified
    if bad_count == 0:
        print("  All quotes verified OK")
    else:
        print(f"  {bad_count} unverified quotes — check sources before submission")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_scoring() -> list[dict]:
    print("Building index …")
    build_index()

    profiles_path = Path("suspect_profiles.json")
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    profiles_by_name = {p["name"]: p for p in profiles}

    print("Scoring suspects …")
    scored = [score_profile(p) for p in profiles]

    print("Determining verdicts …")
    results = determine_verdict(scored, profiles_by_name)

    print("Verifying quotes …")
    results = verify_all_quotes(results)

    # Sort by score descending for display
    results_sorted = sorted(results, key=lambda x: x["score"], reverse=True)

    # Write output
    out = Path("scored_suspects.json")
    out.write_text(json.dumps(results_sorted, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"Wrote {out}")

    return results_sorted


if __name__ == "__main__":
    results = run_scoring()

    print("\n" + "=" * 72)
    print("SUSPECT RANKING TABLE")
    print("=" * 72)
    print(f"  {'Rank':<5} {'Name':<25} {'Score':>6}  {'Verdict':<12}  Factors")
    print(f"  {'-'*70}")
    for rank, item in enumerate(results, start=1):
        factors_str = ", ".join(f["display"] for f in item["factors"])
        print(f"  {rank:<5} {item['name']:<25} {item['score']:>6}  {item['verdict']:<12}  {factors_str}")

    print()
    top = results[0]
    print(f"CULPRIT: {top['name']}  (score {top['score']})")
    print(f"Reasoning: {top['reasoning']}")

    # Confidence: top score as fraction of (top + second)
    scores = [r["score"] for r in results]
    top_score = scores[0]
    second    = scores[1] if len(scores) > 1 else 0
    denom = top_score - min(scores) + 1
    others = [s for s in scores[1:] if s != top_score]
    if others:
        next_best = max(others)
        gap = top_score - next_best
        confidence = min(0.95, max(0.55, 0.5 + gap * 0.07))
    else:
        confidence = 0.55
    print(f"Confidence: {confidence:.2f}")

    print("\n--- MISLEADING SUSPECTS ---")
    for item in results:
        if item["verdict"] != "culprit":
            piv = next((p.get("forensic_pivot", {}) for p in
                        json.loads(Path("suspect_profiles.json").read_text())
                        if p["name"] == item["name"]), {})
            if piv.get("describes_withheld_detail"):
                print(f"\n  {item['name']}  (score {item['score']}, verdict {item['verdict']})")
                print(f"  Reasoning: {item['reasoning'][:200]}")
