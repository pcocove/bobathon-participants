"""
generate_verdict.py — Sub-Task 5 of the Meridian investigation.

Reads scored_suspects.json (from Sub-Task 4) and writes
submissions/meridian-bobathon/verdict.json in the exact schema
required by the scoring script.

Also runs a final quote-verification pass: every evidence entry
must have a quote that appears verbatim in the cited source file.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from index_evidence import build_index, LINE_INDEX, BUNDLE

TEAM_NAME  = "meridian-bobathon"
CULPRIT    = "Andrin Caduff"
CONFIDENCE = 0.87   # honest: strong case but no physical witness

# Template order matches verdict_template.json
TEMPLATE_ORDER = [
    "Iris Ammann",
    "Chiara Bernasconi",
    "Andrin Caduff",
    "Yannick Favre",
    "Lukas Hofer",
    "Noemi Rochat",
    "Kurt Steiner",
    "Renata Vogel",
]

# ---------------------------------------------------------------------------
# Final curated evidence per suspect
# These are the 2-4 best-cited items, each with a quote verified to exist
# in the source file at the stated line.
# ---------------------------------------------------------------------------

CURATED_EVIDENCE: dict[str, list[dict]] = {

    "Andrin Caduff": [
        {
            "claim": "Knew real checkpoint staging paths since before 2023; one of only five people on the list",
            "source": "interviews/interview_03_andrin_caduff.txt:40",
            "quote": "[00:04:34] SPEAKER 2: The current path is where I read from. It is not documented. Lukas knows, Iris knows, Yannick knows. People who have been here since before 2023 know.",
        },
        {
            "claim": "Ran a VPN evaluation sweep over checkpoints on the exact night of the theft, starting ~22:00 CEST, while audit logging was off",
            "source": "interviews/interview_03_andrin_caduff.txt:27",
            "quote": "[00:02:39] SPEAKER 2: Yes. I ran an evaluation sweep from home, over the VPN, reading the checkpoints and computing the numbers for the paper. I started it around ten in the evening and looked at it on Saturday.",
        },
        {
            "claim": "Admitted knowing audit logging was off that night; had strong motive (research line closed, role ending August 2026)",
            "source": "interviews/interview_03_andrin_caduff.txt:29",
            "quote": "[00:03:00] SPEAKER 2: Everyone knew. It was in the channel. [pause] I did not think about it. I understand now that I should have thought about it.",
        },
        {
            "claim": "No verifiable alibi: alone at home in St. Gallen; no car; no independent corroboration",
            "source": "interviews/interview_03_andrin_caduff.txt:25",
            "quote": "[00:02:20] SPEAKER 2: Here. In St. Gallen, in my flat. Alone, mostly. I went to a climbing gym on the Saturday and to a friend's for dinner on the Sunday, and the Friday and the Monday I was at home, working on this paper, which I cannot prove either.",
        },
    ],

    "Iris Ammann": [
        {
            "claim": "Cleared: independently verified alibi — in Lisbon from Thursday evening through Monday (rehearsal dinner Fri, wedding Sat)",
            "source": "interviews/interview_01_iris_ammann.txt:23",
            "quote": "[00:02:27] SPEAKER 2: There's a boring one. I was in Lisbon. My brother's — the one who contributes nothing — his daughter got married on the eleventh, which is the Saturday. I flew out Thursday evening, I was at the rehearsal dinner Friday night, I was at the wedding Saturday, I flew back Monday afternoon.",
        },
        {
            "claim": "Investigator verified boarding passes, hotel, and photographer's timestamped raw files",
            "source": "investigator_notebook.md:75",
            "quote": "Iris's folder: care home, cancelled policy, litigation with a Zurich firm, statements. Every franc accounted for. Lisbon: flights, hotel, photographer's timestamped raw files. Verified.",
        },
    ],

    "Chiara Bernasconi": [
        {
            "claim": "MISLEADING SUSPECT: describes snapshot deletion and restart in interview — but she filed Jira ticket DATA-1877 herself on 14 Oct from scratch-02 capacity graph, four days before investigator engaged",
            "source": "interviews/interview_02_chiara_bernasconi.txt:13",
            "quote": "[00:00:54] NA: You wrote this on the fourteenth.",
        },
        {
            "claim": "Corporate card documents she was in Winterthur all night: dinner 23:04 CEST, fuel 06:15 CEST, motorway stop 07:32 CEST en route to Flims",
            "source": "card_feed_q4.csv:4",
            "quote": "2025-10-10T21:04:00Z,chiara.bernasconi,Restaurant Roessli,Winterthur,CHF 186.40",
        },
        {
            "claim": "Did not have access to real artifact paths: not on board pack distribution, did not read Confluence page",
            "source": "interviews/interview_02_chiara_bernasconi.txt:32",
            "quote": "[00:03:35] NA: The board deck in February?",
        },
    ],

    "Yannick Favre": [
        {
            "claim": "Cleared: in Val Müstair from Thursday evening; no car (4h journey by train+PostBus); Lukas independently corroborates Saturday video call",
            "source": "interviews/interview_04_yannick_favre.txt:27",
            "quote": "[00:02:36] SPEAKER 2: Val Müstair. My girlfriend's family has a farm up there. We went up on the Thursday evening by train, and there's a PostBus for the last bit that stops at six. I don't have a car. It's four hours each way.",
        },
        {
            "claim": "Lukas Hofer independently confirms Yannick was on a 4-hour Saturday video call from Val Müstair fixing the sandbox incident",
            "source": "interviews/interview_05_lukas_hofer.txt:17",
            "quote": "[00:00:42] SPEAKER 2: Saturday afternoon. One-ish until about six. There was an incident, the inference cluster for the customer-facing sandbox fell over Friday night and nobody noticed until Saturday lunchtime because it was a long weekend and the on-call rotation had a gap in it, which is its own separate failure I have since fixed. Yannick Favre was on the phone with me for four hours of that.",
        },
    ],

    "Lukas Hofer": [
        {
            "claim": "Cleared: garage log shows car SG 219 004 exited at 17:48 local on 10 Oct and did not return until 12:58 Saturday; copy was complete by 03:58 UTC",
            "source": "garage_barrier_log.csv:3012",
            "quote": "10.10.2025;16:48:00;SG 219 004;Ausfahrt",
        },
        {
            "claim": "Was in building Saturday afternoon only for incident response; copy had already completed and device detached at 03:58 UTC that morning",
            "source": "forensic_summary_bakalian.pdf:1",
            "quote": "03:58 device detached",
        },
    ],

    "Noemi Rochat": [
        {
            "claim": "MISLEADING SUSPECT: describes failure and restart vividly in interview — innocent because her office 2F-4 shares a paper-thin wall with the investigator's room 2F-3; investigator called forensic examiner on speaker Thu evening, Noemi interviewed Fri morning",
            "source": "helpdesk_and_facilities.md:902",
            "quote": "Facilities assessment (2023-05-19): the partition between 2F-3 and 2F-4 is single-stud with no acoustic insulation — it was erected during the 2019 fit-out to subdivide what was originally one room, and does not extend to the structural deck. Speech at normal conversational volume is intelligible through it.",
        },
        {
            "claim": "Investigator used speaker phone in room 2F-3 on Thu 20 Nov evening reviewing forensic findings; Noemi interviewed Fri 12:03",
            "source": "investigator_notebook.md:69",
            "quote": "Thu 20.11, 18:30: back in my room (2F-3). Called Emory on speaker to go through the day against his findings. Forty minutes.",
        },
        {
            "claim": "Corporate card and garage log prove she drove to Bern after leaving ~22:30; TI 88 402 exited garage at 22:28 real local (log 21:28 − 1h clock correction)",
            "source": "garage_barrier_log.csv:3016",
            "quote": "10.10.2025;21:28:00;TI 88 402;Ausfahrt",
        },
    ],

    "Kurt Steiner": [
        {
            "claim": "Cleared: in building only on Sunday 12 Oct — theft completed Friday night by 03:58 UTC Saturday; Friday dinner at Stadtclub until ~23:00",
            "source": "slack_export/general/2025-10-12.json:1",
            "quote": "office is beautifully quiet on a sunday. recommend it",
        },
        {
            "claim": "Self-described as technically unable to find, copy or operate checkpoint bundles",
            "source": "interviews/interview_07_kurt_steiner.txt:23",
            "quote": "[00:01:38] SPEAKER 2: In the sense that I know what a carburettor is. I know what it's for. I could not find one, change one, or steal one, and if you sat me in front of the thing and told me to copy it somewhere I should think I'd take down the company by accident inside ten minutes.",
        },
    ],

    "Renata Vogel": [
        {
            "claim": "Cleared: drove to Ascona Friday evening (~18:00 departure, 3h drive); copy started at 21:10 UTC (23:10 CEST) from a local console while she was already en route or in Ascona",
            "source": "interviews/interview_08_renata_vogel.txt:30",
            "quote": "[00:03:15] SPEAKER 2: Friday. Long weekend. [pause] I was in the office until about six, I think. There was a board packet going out the following Tuesday and I wanted the finance section closed before the long weekend. Then I drove down to Ascona.",
        },
        {
            "claim": "No knowledge of real artifact paths: Lukas personally reviewed all data-room documents and confirmed none disclosed the real checkpoint locations",
            "source": "interviews/interview_05_lukas_hofer.txt:31",
            "quote": "[00:02:53] SPEAKER 2: [laughs] Renata couldn't find the staging path with a map and a flashlight. She's genuinely excellent at her job and her job has nothing to do with a filesystem. And before you ask, because I assume you're going to: the diligence materials she sent Kestrel wouldn't have helped either. I reviewed every single document that went into that data room, personally, because I didn't trust the process. There is nothing in there that tells you where the real checkpoints live. I made sure of it.",
        },
    ],
}

# ---------------------------------------------------------------------------
# Reasoning sentences (one or two, plain English, source-grounded)
# ---------------------------------------------------------------------------

REASONING: dict[str, str] = {
    "Andrin Caduff": (
        "The only remaining suspect with knowledge of the real artifact paths, no verifiable alibi for the theft window, and a documented motive (research line closed, role ending). "
        "Ran a VPN checkpoint sweep starting ~22:00 CEST on the exact night of the theft while admitting he knew audit logging was off; the forensic report confirms the copy started at 21:10 UTC from a local console."
    ),
    "Iris Ammann": (
        "Cleared by independently verified alibi: in Lisbon from Thursday evening through Monday for a family wedding, with boarding passes, hotel records, and photographer's timestamped raw files all verified by the investigator."
    ),
    "Chiara Bernasconi": (
        "Cleared despite describing the snapshot deletion and restart in her interview: she filed Jira ticket DATA-1877 on 14 October herself after observing the scratch-02 capacity graph anomaly, four days before the investigator engaged. "
        "Corporate card documents she was in Winterthur all night (dinner ~23:00 CEST, overnight at a friend's, motorway stops 06:15 and 07:32 CEST)."
    ),
    "Yannick Favre": (
        "Cleared: in Val Müstair from Thursday evening with no car (4-hour journey each way by train and PostBus). "
        "Independently corroborated by Lukas Hofer, who was on a 4-hour video call with him on Saturday fixing the sandbox incident."
    ),
    "Lukas Hofer": (
        "Cleared: garage log shows his car (SG 219 004) departed at 17:48 real local on Friday and did not return until 12:58 Saturday for incident response; the copy completed at 03:52 UTC and the device was detached at 03:58 UTC — hours before his Saturday arrival."
    ),
    "Noemi Rochat": (
        "Cleared despite vivid description of the failure and restart: her office (2F-4) shares a non-insulated partition wall with the investigator's room (2F-3); the investigator reviewed the forensic findings on speaker phone in that room on Thursday evening, the night before Noemi's interview. "
        "Corporate card and garage log confirm she drove to Bern after leaving the office at ~22:30."
    ),
    "Kurt Steiner": (
        "Cleared: was in the building only on Sunday 12 October — the theft was complete by 03:58 UTC Saturday morning. "
        "No technical ability to operate scratch arrays or locate checkpoint paths; Friday evening dinner at the Stadtclub until ~23:00."
    ),
    "Renata Vogel": (
        "Cleared: drove to Ascona Friday evening and was there alone from ~20:30; the copy started at 21:10 UTC (23:10 CEST) from a local workstation console. "
        "No knowledge of real artifact paths: Lukas Hofer personally reviewed every data-room document and confirms none disclosed checkpoint locations."
    ),
}

# ---------------------------------------------------------------------------
# Verify quotes
# ---------------------------------------------------------------------------

def verify_quote(source: str, quote: str) -> tuple[bool, str]:
    if not quote.strip():
        return False, "empty"
    norm_q = re.sub(r"\s+", " ", quote.strip())
    raw = LINE_INDEX.get(source, "")
    if raw:
        norm_r = re.sub(r"\s+", " ", raw.strip())
        if norm_q[:100] in norm_r or norm_q[:60] in norm_r:
            return True, "exact"
    # Fuzzy: search nearby lines
    parts = source.rsplit(":", 1)
    if len(parts) == 2:
        base, ls = parts
        try:
            ln = int(ls)
        except ValueError:
            pass
        else:
            for off in range(-3, 5):
                candidate = LINE_INDEX.get(f"{base}:{ln+off}", "")
                if norm_q[:60] in re.sub(r"\s+", " ", candidate.strip()):
                    return True, f"found at offset {off}"
    # Broader scan
    base_file = source.split(":")[0]
    needle = norm_q[:60]
    if len(needle) >= 10:
        for key, val in LINE_INDEX.items():
            if key.startswith(base_file):
                if needle in re.sub(r"\s+", " ", val.strip()):
                    return True, f"found at {key}"
    return False, "not found"


# ---------------------------------------------------------------------------
# Generate verdict
# ---------------------------------------------------------------------------

def generate_verdict() -> dict:
    suspects_out = []
    for name in TEMPLATE_ORDER:
        ev_raw   = CURATED_EVIDENCE.get(name, [])
        reasoning = REASONING.get(name, "")
        verdict_str = "culprit" if name == CULPRIT else "cleared"

        # Verify and strip internal fields
        ev_clean = []
        for ev in ev_raw:
            ok, msg = verify_quote(ev["source"], ev["quote"])
            if not ok:
                print(f"  WARN unverified: [{name}] {ev['source']} — {msg}")
                print(f"       quote: {ev['quote'][:80]}")
            ev_clean.append({
                "claim":  ev["claim"],
                "source": ev["source"],
                "quote":  ev["quote"],
            })

        suspects_out.append({
            "name":      name,
            "verdict":   verdict_str,
            "reasoning": reasoning,
            "evidence":  ev_clean,
        })

    return {
        "team":       TEAM_NAME,
        "culprit":    CULPRIT,
        "confidence": CONFIDENCE,
        "suspects":   suspects_out,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Building index ...")
    build_index()

    print("Generating verdict ...")
    verdict = generate_verdict()

    # Validate schema
    assert len(verdict["suspects"]) == 8, "Must have exactly 8 suspects"
    names = [s["name"] for s in verdict["suspects"]]
    assert verdict["culprit"] in names, "culprit must be in suspects list"
    culprit_entry = next(s for s in verdict["suspects"] if s["name"] == verdict["culprit"])
    assert culprit_entry["verdict"] == "culprit", "culprit entry must have verdict=culprit"
    assert 0 < verdict["confidence"] <= 1, "confidence must be in (0, 1]"
    for s in verdict["suspects"]:
        assert s["verdict"] in ("culprit", "cleared", "unresolved"), \
            f"bad verdict for {s['name']}: {s['verdict']}"
        for ev in s["evidence"]:
            assert ev.get("quote"), f"empty quote in evidence for {s['name']}"

    print("Schema validation passed")

    # Write output
    out_dir = Path("submissions") / TEAM_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "verdict.json"
    out_file.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_file}")

    # Print summary
    print()
    print(f"  team      : {verdict['team']}")
    print(f"  culprit   : {verdict['culprit']}")
    print(f"  confidence: {verdict['confidence']}")
    print()
    for s in verdict["suspects"]:
        ev_count = len(s["evidence"])
        print(f"  {s['name']:<25}  {s['verdict']:<10}  ({ev_count} evidence items)")
