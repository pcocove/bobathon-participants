# MERIDIAN Investigation Plan

## Top-Level Overview

**Goal:** Identify who stole the MERIDIAN model weights from Halcyon Systems during the audit-logging blackout window (Fri 10 Oct 21:00 → Sat 11 Oct 06:00 CEST) and produce a `verdict.json` with cited, verifiable evidence for all eight suspects.

**Approach:** Use the MCP unified-data server to query garage barrier logs, parking permits, Slack, calendar, and helpdesk records without loading large raw files directly. Cross-reference with interview transcripts, the forensic summary, and the investigator's notebook to clear seven suspects and convict one.

**Key forensic facts (from `investigator_notebook.md:37-39`, to be withheld):**
- Copy job started ~23:10 Fri on `scratch-02`
- First attempt failed partway (~40%), disk filled
- Old snapshot deleted at ~02:41 Sat (~9 TB freed)
- Job restarted and completed at **05:52 Sat** — 8 minutes before logging resumed

---

## Sub-Task 1: Establish physical presence on the night

**Intent:** The theft required physical presence in the building Friday night until approximately 05:52 Saturday morning.

**Expected Outcomes:** Identify which suspects' vehicles were in the garage that night and which had no corroborated departure before the window opened.

**Evidence collected:**
- `garage_barrier_log.csv` (via MCP) shows Renata Vogel (SG 482 117) entered at 08:41 Fri, NO recorded exit all day after that.
- June Okada posted to Slack at 18:58 Fri: *"garage is basically empty, just me and the usual green volvo"* (`slack_export/general/2025-10-10.json:10`). Parking permit PB-2400 confirms Renata's car is a **green Volvo V60 Kombi**.
- An unresolved partial-plate exit `SG 482 1?7` at **05:09 Sat** (confidence 61%) matches Renata's plate `SG 482 117`. The next possible match, M. Keller `SG 482 177`, exited on Friday at 17:10 and had no re-entry.
- Copy completed at 05:52 — 43 minutes after the 05:09 exit, meaning the car left *before* the job finished. Person could have left via alley door on foot first, retrieved car after triggering the exit.
- Noemi Rochat entered 09:02, exited 22:28 Fri — **before** the 23:10 copy start.
- Lukas Hofer was in the building **Saturday** (not Friday night): entered 11:58 Sat, exited 16:52 Sat. Confirmed by INC-0412 incident timeline in Slack.

**Status:** [x] done

---

## Sub-Task 2: Establish knowledge of which checkpoints were real

**Intent:** The decoys were not touched — the thief knew which bundles were genuine.

**Sources of the real/decoy mapping:**
1. Iris Ammann's own knowledge (she designed it)
2. Board pack February 2025, slide 11 — distribution: board members + presenters only
3. Confluence page "Storage Integrity Controls (WIP)" by Yannick Favre, March 2025, permissioned `eng-all` — 16 views, 9 accounts

**Renata Vogel and the board pack:**
- Renata assembled the board pack every quarter (`interview_08_renata_vogel.txt:53-58`)
- She says she reads sections "for formatting" and confirmed: *"Iris's security sections are the worst for that, lovely diagrams, I nod and fix the font sizes"*
- She passed the February pack to the board — she had the file and opened it.
- She claims she didn't understand the technical slides. But the slide showed paths by name, not requiring deep technical comprehension.

**Status:** [x] done

---

## Sub-Task 3: Explain Noemi Rochat's suspicious knowledge of forensic details

**Intent:** Noemi described the exact forensic details (disk full, snapshot deleted, job restarted) that were supposed to be withheld from all eight suspects.

**The innocent explanation:**
- Nadia Arslan's investigation room was **2F-3**; Noemi's office is **2F-4** (adjacent).
- FAC-330 (`helpdesk_and_facilities.md:897-908`): the partition between 2F-3 and 2F-4 is single-stud with no acoustic insulation. Speech at normal conversational volume is intelligible through it.
- Nadia called forensics expert Emory on speakerphone from 2F-3 on **Thu 20.11, 18:30** for forty minutes (`investigator_notebook.md:69`).
- Noemi was in her office "every day" that week (`interview_06_noemi_rochat.txt:34`).
- → Noemi overheard the speakerphone call through the wall and recycled the details in her own interview (Fri 21.11) to appear perceptive. Her knowledge is explained; it does not make her the thief.

**Status:** [x] done

---

## Sub-Task 4: Clear remaining suspects

**Iris Ammann:** Verifiable alibi — flew to Lisbon Thu evening, rehearsal dinner Fri night, wedding Sat, returned Mon. 300+ witnesses, photographer raw files. Boarding passes provided. (`interview_01_iris_ammann.txt`)

**Lukas Hofer:** Garage places him entering Sat 11:58 (not Friday night). Slack INC-0412 confirms he was responding to a cluster outage on Saturday. VPN network egress for checkpoint pull would show in the monthly bill — Lukas confirmed it didn't. (`interview_05_lukas_hofer.txt`, `slack_export/incidents/2025-10-11.json`)

**Andrin Caduff:** Ran a read-only evaluation sweep from home over VPN Fri night. No car, cannot enter garage. Lukas confirmed the sweep cannot copy data (`followup_01_lukas_hofer.txt`). Access pattern explained by paper-writing, confirmed by Lukas. (`interview_03_andrin_caduff.txt`)

**Yannick Favre:** Val Müstair, no car, PostBus last at 18:10 Fri. On video call Sat from farm kitchen. Alibi corroborated by Lukas and Slack. (`interview_04_yannick_favre.txt`, `slack_export/incidents/2025-10-11.json`)

**Chiara Bernasconi:** Candidate dinner in Winterthur at restaurant Rössli 20:00 Fri, left ~23:00, drove to Flims Sat 06:00. Garage shows she exited 16:35 Fri and no re-entry. (`interview_02_chiara_bernasconi.txt`, garage barrier log)

**Noemi Rochat:** Exited garage at 22:28 Fri, before the 23:10 copy start. Forensic knowledge explained by FAC-330 wall. Helpdesk HD-3001 (asking about alley door 4 days after) is slightly suspicious but is consistent with someone curious about how an unknown exit worked, not with guilt. (`garage barrier log`, `interview_06_noemi_rochat.txt`, `helpdesk_and_facilities.md:8-9`)

**Kurt Steiner:** No technical capability to execute the copy (own admission, investigator agrees). In building Sunday (after the theft). Friday dinner at Stadtclub — not in building Friday night. Admin accounts but no knowledge of real checkpoint paths. (`interview_07_kurt_steiner.txt`)

**Status:** [x] done

---

## Sub-Task 5: Make the case for Renata Vogel

**Motive:**
- 120-day day-to-day relationship with Gilles Aubert (Kestrel) — she was the bridge.
- Aubert offered her a "continuing role" after deal close in May (`interview_08_renata_vogel.txt:27-29`). She forwarded it to Dov and says she has nothing to hide — but the offer showed a channel.
- She knew the data room service accounts were never revoked (SEC-419) and had a broad read role.
- She ran the data room — she was the owner of record.

**Knowledge of real checkpoints:**
- Assembled the February board pack including Iris's slide 11 (real/decoy mapping by path).
- She is on record reading slides "for formatting" — she may have understood more than she admitted.
- Alternatively: she didn't need to know the paths in advance. With an unrevoked broad-scope service account she could list the full storage tree, see 20 checkpoint-looking objects, and simply copy ALL of them. But the decoys were not opened — this argues she DID know which were real.

**Physical presence:**
- Car (green Volvo V60, SG 482 117) remained in garage at ~19:00 Fri despite her claiming to have left "around six" (`interview_08_renata_vogel.txt:31`).
- Unresolved exit SG 482 1?7 at 05:09 Sat (61% confidence) matches her plate.
- No fuel/highway toll expense filed for the claimed Ascona drive.
- Expense on Oct 9: Swiss International Air Lines CHF 114.90 ("conference") — unexplained travel the day before.

**Technical execution:**
- She says she needed June to reset her password and once escalated to Lukas over a sorting bug.
- The forensic profile (amateur, ran out of disk, had to restart) is exactly consistent with a non-technical person doing this for the first time.
- She demonstrated in the interview detailed knowledge of the disk-full / snapshot-delete / restart sequence — knowledge that should only be known by the perpetrator or someone who overheard Nadia's call. Renata was NOT in 2F-4 (that's Noemi). She was not near 2F-3 during the 20.11 call.

**Confidence:** 0.72

**Status:** [x] done

---

## Sub-Task 6: Write verdict.json

**Intent:** Produce the output file in the required format with all eight suspects, verified quotes, and source citations.

**Status:** [ ] pending
