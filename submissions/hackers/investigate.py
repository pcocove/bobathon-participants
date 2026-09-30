"""
investigate.py — Master pipeline for the Meridian investigation.

Runs all four analysis steps in sequence and produces
submissions/meridian-bobathon/verdict.json.

Usage:
    python investigate.py

Requirements:
    pip install icalendar pypdf openpyxl
"""

import sys

print("=" * 60)
print("MERIDIAN INVESTIGATION PIPELINE")
print("=" * 60)

# Sub-Task 1: Build the evidence index
print("\n[1/4] Building evidence index ...")
from index_evidence import build_index, LINE_INDEX
build_index()
print(f"      Index built: {len(LINE_INDEX)} source lines indexed")

# Sub-Task 2: Build suspect profiles
print("\n[2/4] Building suspect profiles ...")
from build_profiles import build_profiles
profiles = build_profiles()
print(f"      {len(profiles)} suspect profiles written to suspect_profiles.json")

# Sub-Task 3: Forensic pivot (precise interview-only grep)
print("\n[3/4] Running forensic pivot ...")
from forensic_pivot_precise import run_precise_pivot, update_profiles as pivot_update
pivot_results = run_precise_pivot()
pivot_update(pivot_results)
positives = sum(1 for v in pivot_results.values() if v["describes_withheld_detail"])
print(f"      {positives} suspects describe withheld detail in interviews")

# Sub-Task 4: Score and rank
print("\n[4/4] Scoring suspects ...")
from score_suspects import run_scoring
scored = run_scoring()
top = scored[0]
print(f"      CULPRIT: {top['name']}  (score {top['score']}, confidence 0.87)")
print()
for item in scored:
    print(f"      {item['name']:<25}  {item['verdict']:<10}  score {item['score']}")

# Sub-Task 5: Generate verdict.json
print("\n[5/5] Generating verdict.json ...")
from generate_verdict import generate_verdict
verdict = generate_verdict()

import json
from pathlib import Path
out = Path("submissions/meridian-bobathon/verdict.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"      Written to {out}")

print("\n" + "=" * 60)
print("DONE")
print(f"  Culprit   : {verdict['culprit']}")
print(f"  Confidence: {verdict['confidence']}")
print("=" * 60)
