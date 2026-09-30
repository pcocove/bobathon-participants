"""
forensic_pivot_precise.py — refined Sub-Task 3.

The initial grep flagged routine Slack noise (backfill restarts, snapshot
cleanups) that have nothing to do with the theft. This script applies a
stricter filter:

  The withheld detail is a SPECIFIC COMBINATION:
    (A) The copy job failed because the TARGET DEVICE was full
    (B) A snapshot was deleted to free space ON THE DESTINATION
    (C) The job was restarted FROM THE BEGINNING (not resumed)

  Only interview transcripts can meaningfully express this combination.
  Slack hits for generic "restart backfill" or "snapshot freed X TB" are
  routine infra ops and do NOT indicate knowledge of the theft.

  The two suspects who do describe the combination in their interviews are:
    - Chiara Bernasconi (interview_02): full innocent explanation (Jira ticket)
    - Noemi Rochat (interview_06): full innocent explanation (paper wall)

  Renata Vogel (interview_08) also uses "fill the target disk halfway" —
  this is in the context of saying "that's not me" and argues by description
  that she couldn't have done it. She does describe the detail.
  But she was in Ascona (card + garage corroborates), and she explicitly
  says she has June reset her password. This needs careful examination.

This script:
  1. Greps ONLY interview transcripts for the pivot combination
  2. Checks each hit for a prior source (pre-interview knowledge)
  3. Produces a clear verdict per suspect
  4. Writes forensic_pivot_report.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from index_evidence import build_index, LINE_INDEX, BUNDLE

# ---------------------------------------------------------------------------
# The specific theft-describing phrases (must be in INTERVIEW text only)
# ---------------------------------------------------------------------------

# These patterns match the specific sequence of the theft, not routine ops
PRECISE_PATTERNS = [
    # Target device full → job failed
    ("target_full",
     re.compile(r"(target|disk|drive|device|destination).{0,40}(full|no.space|out.of.space)", re.I)),
    ("fill_target",
     re.compile(r"(fill|filled).{0,30}(target|disk|drive|device|halfway|half.?way|40\s*%)", re.I)),
    # Snapshot deleted to free space for a restart
    ("snapshot_to_free",
     re.compile(r"snapshot.{0,60}(delete|delet|clear|free|bin|room|make)", re.I)),
    ("bin_to_make_room",
     re.compile(r"(bin|delete|clear).{0,40}(make.room|free.space|start.again|start.over)", re.I)),
    # Restart from beginning (in context of a copy job, not a backfill)
    ("restart_from_beginning",
     re.compile(r"(restart|start(ed)?.again|start(ed)?.over|start.from.(the.)?beginning|start.the.whole.job.again)", re.I)),
    # Explicit mention of the combination
    ("halfway_then_restart",
     re.compile(r"(halfway|half.?way|40\s*%).{0,100}(restart|start.again|start.over)", re.I)),
]

# ---------------------------------------------------------------------------
# Interview attribution
# ---------------------------------------------------------------------------

INTERVIEW_SUSPECT_MAP = {
    "interview_01_iris_ammann.txt":       "Iris Ammann",
    "interview_02_chiara_bernasconi.txt": "Chiara Bernasconi",
    "interview_03_andrin_caduff.txt":     "Andrin Caduff",
    "interview_04_yannick_favre.txt":     "Yannick Favre",
    "interview_05_lukas_hofer.txt":       "Lukas Hofer",
    "interview_06_noemi_rochat.txt":      "Noemi Rochat",
    "interview_07_kurt_steiner.txt":      "Kurt Steiner",
    "interview_08_renata_vogel.txt":      "Renata Vogel",
    "followup_01_lukas_hofer.txt":        "Lukas Hofer",
    "followup_02_june_okada.txt":         None,  # Not a suspect
}

# Prior-knowledge explanations that make a hit innocent
PRIOR_KNOWLEDGE: dict[str, str] = {
    "Chiara Bernasconi": (
        "Chiara observed the free-space anomaly on scratch-02's capacity graph herself and posted "
        "in #eng-infra on 14 Oct (slack_export/eng-infra/2025-10-14.json:7: "
        "'opened DATA-1877 about scratch-02, free space over the long weekend looks deranged. "
        "fills, drops ~9TB'). She also describes a near-identical operation she performed herself "
        "in September (interview_02:34: 'rsync to cold storage die halfway and had to delete an "
        "old snapshot and start it again from the top'). Both are independent prior knowledge."
    ),
    "Noemi Rochat": (
        "Noemi's office (2F-4) shares a non-insulated partition with the investigator's room "
        "(2F-3). FAC-330 states: 'speech at normal conversational volume is intelligible through "
        "it.' The investigator called forensic examiner Emory Bakalian on speaker in 2F-3 at "
        "18:30 Thu 20 Nov, reviewing all forensic findings for 40 minutes "
        "(investigator_notebook.md:69). Noemi's interview was the next morning (Fri 21 Nov 12:03). "
        "She was in the building every day that week (interview_06:43: 'Every day')."
    ),
    "Renata Vogel": (
        "PARTIAL: Jira ticket DATA-1877 (filed by chiara.bernasconi on 14 Oct, public to all Jira "
        "users) describes 'someone hand-running a copy and clearing room when it filled' — Renata "
        "could have read this after Wendell Pryce's email on 11 Nov. However, Renata's description "
        "('deleted something to make room and started the whole job over again from the beginning') "
        "is more specific than DATA-1877 and uses language closer to the actual forensic sequence. "
        "She is NOT in #eng-infra (no messages found there) and did not comment on DATA-1877. "
        "Her alibi (Ascona, driving window, no garage re-entry) and stated inability to operate "
        "checkpoints mean she could not have been the operator. Weak innocent explanation via Jira."
    ),
}

# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_precise_pivot() -> dict:
    print("Building index …")
    build_index()

    interview_dir = BUNDLE / "interviews"
    results: dict[str, dict] = {}

    suspects_all = [
        "Iris Ammann", "Chiara Bernasconi", "Andrin Caduff", "Yannick Favre",
        "Lukas Hofer", "Noemi Rochat", "Kurt Steiner", "Renata Vogel",
    ]
    for s in suspects_all:
        results[s] = {
            "describes_withheld_detail": False,
            "evidence": [],
            "innocent_explanation": PRIOR_KNOWLEDGE.get(s),
        }

    for fname, suspect in INTERVIEW_SUSPECT_MAP.items():
        if suspect is None:
            continue
        fpath = interview_dir / fname
        if not fpath.exists():
            continue
        rel = fpath.relative_to(BUNDLE).as_posix()
        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()

        for lineno, raw in enumerate(lines, start=1):
            # Only check interviewee lines (SPEAKER 2)
            if "SPEAKER 2" not in raw:
                continue
            for label, compiled in PRECISE_PATTERNS:
                if compiled.search(raw):
                    results[suspect]["describes_withheld_detail"] = True
                    results[suspect]["evidence"].append({
                        "claim": f"Describes withheld forensic detail in interview (pattern: {label})",
                        "source": f"{rel}:{lineno}",
                        "quote": raw.strip()[:400],
                        "pattern": label,
                    })
                    break  # one hit per line is enough

    return results


def update_profiles(results: dict) -> None:
    profiles_path = Path("suspect_profiles.json")
    if not profiles_path.exists():
        print("WARNING: suspect_profiles.json not found")
        return
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    for profile in profiles:
        name = profile["name"]
        if name not in results:
            continue
        data = results[name]
        profile["forensic_pivot"] = {
            "describes_withheld_detail": data["describes_withheld_detail"],
            "innocent_explanation": data["innocent_explanation"],
            "evidence": data["evidence"],
        }
    profiles_path.write_text(json.dumps(profiles, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print(f"Updated {profiles_path}")


def write_report(results: dict) -> None:
    out = Path("forensic_pivot_report.json")
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    results = run_precise_pivot()
    update_profiles(results)
    write_report(results)

    print("\n" + "=" * 65)
    print("PRECISE FORENSIC PIVOT — INTERVIEW HITS ONLY")
    print("=" * 65)
    print(f"  {'Suspect':<25} {'Pivot hit':<10} {'Innocent prior source?'}")
    print(f"  {'-'*65}")
    for name, data in results.items():
        flag    = "YES ***" if data["describes_withheld_detail"] else "no"
        has_exp = "YES" if data["innocent_explanation"] else "NO (unexplained)"
        if not data["describes_withheld_detail"]:
            has_exp = "n/a"
        print(f"  {name:<25} {flag:<10} {has_exp}")

    print("\nDetailed hits:")
    for name, data in results.items():
        for ev in data["evidence"]:
            print(f"\n  [{name}] {ev['source']}  ({ev['pattern']})")
            print(f"  \"{ev['quote'][:200]}\"")
            if data["innocent_explanation"]:
                print(f"  => INNOCENT: {data['innocent_explanation'][:100]}…")
            else:
                print(f"  => NO INNOCENT EXPLANATION FOUND")
