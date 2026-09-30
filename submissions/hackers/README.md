# Meridian Investigation — Submission README

## Team

**meridian-bobathon**

---

## How to run

### Requirements

Python 3.10+ with three additional packages:

```
pip install icalendar pypdf openpyxl
```

### Run the full pipeline

```
python investigate.py
```

This runs all five steps in sequence and writes
`submissions/meridian-bobathon/verdict.json`.

You can also run each step individually:

| Step | Script | Output |
|---|---|---|
| 1 — Index evidence | `python index_evidence.py` | In-memory (`LINE_INDEX`, `TIMELINE`) |
| 2 — Suspect profiles | `python build_profiles.py` | `suspect_profiles.json` |
| 3 — Forensic pivot | `python forensic_pivot_precise.py` | `forensic_pivot_report.json` |
| 4 — Score & rank | `python score_suspects.py` | `scored_suspects.json` |
| 5 — Generate verdict | `python generate_verdict.py` | `submissions/meridian-bobathon/verdict.json` |

All scripts must be run from the repository root (the folder containing
`meridian_case_bundle/`).

---

## Architecture

```
index_evidence.py       ← loads all 16 file types, builds LINE_INDEX + TIMELINE
build_profiles.py       ← per-suspect: access / opportunity / motive / alibi
forensic_pivot_precise.py ← keyword grep on interviews only for withheld detail
score_suspects.py       ← additive scoring model, quote verification
generate_verdict.py     ← serialises to verdict.json schema
```

---

## Declaration of hand-typed facts (Rule 2)

Per contest rules, any fact typed into the code after reading the files
must be declared here. The following were typed in by hand after reading
the case bundle:

1. **The 8 suspect names** — listed in `investigator_notebook.md:23–24` and
   used as constants throughout.

2. **Parking permit → plate mapping** — read from `parking_permits.xlsx` rows 3–9
   and hardcoded in `build_profiles.py::PLATE_TO_SUSPECT` for cross-referencing
   with the garage log.

3. **Garage clock correction (+1 hour)** — read from `helpdesk_and_facilities.md:890`
   (FAC-352: "barrier system clock stayed on winter time after 30 March").
   The barrier was on CET (UTC+1) while real local time was CEST (UTC+2); real
   CEST = raw barrier time + 1 hour. Verified independently: Noemi Rochat's raw
   garage exit of 21:28 + 1h = 22:28 CEST, matching her interview statement
   "until about 22:30" (`interviews/interview_06_noemi_rochat.txt`).
   Hardcoded as `GARAGE_CLOCK_CORRECTION_HOURS = +1`.

4. **Forensic UTC times** — read from `forensic_summary_bakalian.pdf` page 1:
   copy started 21:10 UTC, failed ~00:20, snapshot deleted 00:41, restarted
   00:44, completed 03:52, device detached 03:58. Used to anchor the timeline
   in `build_profiles.py` and `generate_verdict.py`.

5. **FAC-330 wall detail** — read from `helpdesk_and_facilities.md:902`: the
   partition between 2F-3 and 2F-4 is non-insulated; speech intelligible.
   Used as the innocent explanation for Noemi Rochat's interview pivot hit.

6. **DATA-1877 ticket detail** — read from `jira_export.json:7249–7275`:
   Chiara filed the ticket on 14 Oct from the capacity graph; Yannick
   commented he was in Val Müstair. Used as innocent explanation for
   Chiara Bernasconi's interview pivot hit.

7. **Renata Vogel's board pack assembly role** — read from
   `interviews/interview_08_renata_vogel.txt:52–61`: she assembled the February
   board pack including slide 11 (the real/decoy mapping), and was instructed to
   delete it (`email_export.mbox:149–161`) but acknowledged she could not recall
   the distributed PDF.

8. **Garage overnight analysis** — read from `garage_barrier_log.csv`:
   SG 482 117 (Vogel) entered at raw 07:41 on 10 Oct with no corresponding
   departure that day. Partial plate SG 482 1?7 exits at raw 05:09 on 11 Oct
   (= 06:09 CEST = 04:09 UTC, 11 minutes post-device-detach at 03:58 UTC).
   M. Keller (SG 482 177) is excluded: departed at raw 16:10 on 10 Oct, no
   11 Oct entry.

No suspect names, dates, or evidence were invented or assumed without
being found in the bundle files at the cited source:line.

---

## Answer

**Culprit: Renata Vogel**  
**Confidence: 0.97**

### Why Vogel

| Evidence | Source |
|---|---|
| Car (SG 482 117) in garage all night — no departure recorded 10 Oct | `garage_barrier_log.csv:2990` + `parking_permits.xlsx:PB-2400` |
| Partial plate SG 482 1?7 exits raw 05:09 Sat = **06:09 CEST = 04:09 UTC** — 11 min after device detach | `garage_barrier_log.csv:3017` |
| Clock correction verified: raw + 1h = real CEST (Rochat raw 21:28 + 1h = 22:28 ≈ "~22:30") | `helpdesk_and_facilities.md:890` + interview_06 |
| Alibi refuted: card at St. Gallen 07:52 CEST Sat, then driving south — not returning from Ascona | `card_feed_q4.csv:TX880909–TX880911` |
| Assembled board pack, retained PDF with slide 11 (real/decoy mapping by path) | `email_export.mbox:149–161` |
| Kestrel "continuing role" offer (14 May); 120 days as Kestrel's counterpart | `email_export.mbox:4283` |
| Describes the exact heist methodology (all-night sit, snapshot delete, restart) in interview | `interviews/interview_08_renata_vogel.txt:38` |

### Why Andrin Caduff is cleared (not culprit)

Caduff was the previous leading suspect. The garage evidence resolves the case against him:
the forensic job ran from a **local console** on the engineering floor — Caduff has **no car**
and **no parking permit** (confirmed `interview_03_andrin_caduff.txt:36`, absent from
`parking_permits.xlsx`). His VPN sweep was independently confirmed read-only by Lukas Hofer
with no network egress (`followup_01_lukas_hofer.txt:13`). His 31 checkpoint accesses are
fully explained by his method-only paper, corroborated by Hofer (`followup_01:8`).

### Why not Chiara Bernasconi (misleading suspect 1)

Describes the snapshot deletion and restart in her interview — but she
filed Jira ticket **DATA-1877** on **14 October** (four days before the
investigator engaged) after observing the scratch-02 capacity graph herself.
The "withheld detail" was in her own ticket. She was also in Winterthur all
night: restaurant 23:04 CEST → friend's flat → fuel 06:15 → motorway 07:32.

### Why not Noemi Rochat (misleading suspect 2)

Describes the failure and restart with startling specificity. Innocent
because her office (2F-4) shares a **non-insulated partition wall** with
the investigator's room (2F-3) — facility ticket FAC-330 states "speech
at normal conversational volume is intelligible through it." The investigator
called forensic examiner Emory Bakalian on **speaker phone** in that room
at 18:30 on Thursday 20 November, reviewing all forensic findings. Noemi's
interview was the following morning at 12:03.

---

## Bonus — How to prevent a repeat

See `bonus_prevention.md` in this folder.
