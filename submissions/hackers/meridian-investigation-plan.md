# Meridian Investigation Plan

## Goal

Determine who stole the MERIDIAN AI model from Halcyon Systems AG on the night of 10–11 October 2025.
The culprit must be identified with a sourced, verifiable evidence chain — every claim must have a file, line number, and exact quote.

---

## Completed Sub-Tasks

### [x] Sub-Task 1 — Index all evidence
Built `index_evidence.py` → LINE_INDEX (40,048 keys) + TIMELINE (11,841 entries).

### [x] Sub-Task 2 — Build suspect profiles
Built `build_profiles.py` → `suspect_profiles.json` for all 8 suspects.

### [x] Sub-Task 3 — Forensic pivot
Built `forensic_pivot_precise.py` → `forensic_pivot_report.json`.
Identified Chiara Bernasconi and Noemi Rochat as misleading suspects with innocent explanations.

### [x] Sub-Task 4 — Score suspects
Built `score_suspects.py` → `scored_suspects.json`.
Caduff scores +3; all others ≤ −6. Confidence formula: `0.5 + (gap × 0.07)` → **0.87**.

### [x] Sub-Task 5 — Generate verdict
Built `generate_verdict.py` → `submissions/meridian-bobathon/verdict.json`.
Culprit: Andrin Caduff. Confidence: 0.87. 0 unverified quotes.

### [x] Sub-Task 6 — Bonus and pitch
- `submissions/meridian-bobathon/bonus_prevention.md` — 6 prevention proposals, all 13 source citations verified.
- `submissions/meridian-bobathon/pitch.html` — 11-slide pitch deck.

---

## Current Status: Confidence Gap

The current verdict names **Andrin Caduff** as culprit with confidence **0.87**.

That confidence number was produced by an arithmetic formula (`0.5 + gap × 0.07`), not a probabilistic argument.
Adding more self-reported Caduff evidence (calendar, Slack) only pushes the formula output higher — it does **not** add genuine evidential certainty. A judge looking at this critically would notice that immediately.

---

## The Core Evidential Problem

The forensic report is unambiguous:

> "The job was started from a workstation console on the engineering floor (local session, no network login)."
> — `forensic_summary_bakalian.pdf:30`

Caduff himself says he had no car and was in St. Gallen over VPN.
Lukas confirms VPN sweeps are read-only and cannot exfiltrate data (`followup_01_lukas_hofer.txt:13–15`).

**These facts partially exonerate Caduff on the physical presence question — or at least reveal a gap.**

The culprit had to be **physically present on the engineering floor** between 21:00 UTC Fri 10 Oct and ~04:00 UTC Sat 11 Oct.
The current verdict has not fully resolved who that person is.

---

## Sub-Task 7 — Resolve Physical Presence [ ] pending

### Intent

Genuine certainty comes from answering: **who was physically on the engineering floor between 21:00 and 04:00 UTC on 10–11 Oct?**
This is the actual gap in certainty — not the confidence arithmetic.

### The key question

Check whether the physical-presence records either:
1. **Place someone else in the building** that night (new culprit candidate), or
2. **Rule out Caduff being present** (which would contradict the current verdict), or
3. **Show no suspect was recorded entering** (which leaves the case open), or
4. Reveal any suspect whose alibi is contradicted by their own card/garage/badge record.

### Files to read

| File | What it tells us |
|---|---|
| `meridian_case_bundle/case_bundle/garage_barrier_log.csv` | Who drove into the building that night. **Clock is 1h fast** (FAC-352, `helpdesk_and_facilities.md:890`) — subtract 1h from all timestamps for true CEST time. |
| `meridian_case_bundle/case_bundle/investigator_notebook.md:29` | Badge log summary — 11 entries over 4 days, mostly cleaning contractor. Which of the 8 suspects appears? |
| `meridian_case_bundle/case_bundle/card_feed_q4.csv` | Any transaction placing a suspect elsewhere that night = alibi. Any transaction near the office = presence. |
| All follow-up interviews | Rochat says she was in the building until ~22:30 (`investigator_notebook.md:66`). What do others say? |
| `meridian_case_bundle/case_bundle/parking_permits.xlsx` | Maps licence plates to persons — needed to interpret garage log entries. |

### Expected Outcomes

- A definitive answer on who could have been physically present.
- Either: corroboration that Caduff was present (contradicts his VPN-only story, raises confidence legitimately), or
- Identification of a different suspect who was physically in the building (which changes the verdict), or
- Honest acknowledgement that physical presence cannot be established from available records (which caps confidence at a justified level).

### Why this matters for scoring

The scoring criteria reward:
- **Source for every claim** — a physical-presence finding from the garage/badge/card log is a stronger source than a self-reported interview claim.
- **Handling uncertainty** — honestly capping confidence where records are ambiguous scores higher than inflating confidence with redundant evidence.
- **The right name** — if the physical evidence points to someone other than Caduff, the current verdict is wrong.

---

## Misleading Suspects (both cleared — must remain in verdict)

### Chiara Bernasconi
Describes snapshot deletion and restart with precision → sounds like insider knowledge.
**Innocent because:** she filed Jira DATA-1877 on 14 Oct herself, from the scratch-02 capacity graph (`slack_export/eng-infra/2025-10-14.json:7`, `jira_export.json:7257`). She saw the free-space jump in the metrics — she didn't cause it. Corporate card places her in Winterthur all night (`card_feed_q4.csv:4`).

### Noemi Rochat
Describes the failure and restart with suspicious precision → sounds like she witnessed it.
**Innocent because:** her office 2F-4 shares a non-insulated wall with investigator's room 2F-3 (`helpdesk_and_facilities.md:902`, FAC-330). Investigator called Emory on speaker phone Thu 20 Nov evening (`investigator_notebook.md:69`); Rochat was interviewed Fri 12:03 — she overheard the debrief through the wall. Card and garage confirm she drove to Bern that night.

---

## Garage Clock Correction

`helpdesk_and_facilities.md:890` (FAC-352): garage barrier clock is **1 hour fast** (stuck on winter time).
All garage barrier timestamps must have **1 hour subtracted** to get true local CEST time.

---

## Forensic Timeline (UTC, `forensic_summary_bakalian.pdf:1`)

| Time (UTC) | Event |
|---|---|
| 21:10 Fri 10 Oct | Bulk copy job starts from local console on engineering floor |
| ~00:20 Sat 11 Oct | Target device full at ~40%; job terminates |
| 00:41 | Snapshot deleted on destination device (~9.1 TB freed) |
| 00:44 | Job restarted from beginning |
| 03:52 | Second run completes |
| 03:58 | Device detached |

**Key forensic constraint:** No user session information recorded on scratch volumes. Identity cannot be established from the array alone. Physical presence is the only route to certainty.

---

## Pipeline Scripts

| Script | Purpose |
|---|---|
| `investigate.py` | Master runner |
| `index_evidence.py` | Builds LINE_INDEX + TIMELINE |
| `build_profiles.py` | Builds `suspect_profiles.json` |
| `forensic_pivot_precise.py` | Withheld-detail grep |
| `score_suspects.py` | Scoring model |
| `generate_verdict.py` | Writes `verdict.json` |

Run full pipeline: `python investigate.py`

## Submission Files

| File | Status |
|---|---|
| `submissions/meridian-bobathon/verdict.json` | Confidence 0.87, culprit Caduff, 0 unverified quotes |
| `submissions/meridian-bobathon/README.md` | Run instructions + hand-typed fact declaration |
| `submissions/meridian-bobathon/bonus_prevention.md` | 6 prevention proposals |
| `submissions/meridian-bobathon/pitch.html` | 11-slide pitch deck |
