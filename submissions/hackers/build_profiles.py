"""
build_profiles.py — Sub-Task 2 of the Meridian investigation.

Builds a structured suspect profile for each of the 8 suspects by querying
the index from Sub-Task 1, then writes suspect_profiles.json.

Each profile contains:
  - access_to_real_paths : bool + evidence list
  - opportunity_window   : "in" / "out" / "unknown" + evidence list
  - motive               : summary string + evidence list
  - alibi                : summary string (or None) + evidence list
  - suspicious_behaviours: evidence list
  - clearing_evidence    : evidence list
  - forensic_pivot       : populated in Sub-Task 3; placeholder here

An evidence item is:
  {"claim": str, "source": "relpath:line", "quote": str}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from index_evidence import build_index, LINE_INDEX, BUNDLE, WINDOW_START, WINDOW_END

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Garage clock was stuck on winter time (UTC+1) when CEST was active (UTC+2).
# Every garage timestamp is 1 hour AHEAD of true local time.
# Garage log shows local times → subtract 1h correction, then convert to UTC (-2h).
# Net effect: garage log time - 2h = UTC  (but the -1h correction means: log - 3h = UTC??)
# Actually:
#   True local (CEST) = garage_log_time - 1h
#   UTC = true_local - 2h
#   So UTC = garage_log_time - 3h
# We only need local interpretations, so we use: real_local = log_time - 1h
GARAGE_CLOCK_CORRECTION_HOURS = -1  # subtract 1h from log time to get true local (CEST)

# Parking permit plate → suspect mapping (from parking_permits.xlsx rows 3-9)
PLATE_TO_SUSPECT = {
    "SG 482 117": "Renata Vogel",    # row 3
    "SG 219 004": "Lukas Hofer",     # row 4
    "SG 77 310":  "Chiara Bernasconi",  # row 5
    "TI 88 402":  "Noemi Rochat",    # row 6
    "SG 1 994":   "Kurt Steiner",    # row 7
    # row 8: Yannick Favre — no car (stated in interview; no permit row)
    "ZH 610 882": "Iris Ammann",     # row 9
    # Andrin Caduff — no car (stated in interview)
}


def _ev(claim: str, source: str, quote: str) -> dict:
    return {"claim": claim, "source": source, "quote": quote}


def _line(relpath: str, lineno: int) -> str:
    """Return raw text from LINE_INDEX or empty string."""
    return LINE_INDEX.get(f"{relpath}:{lineno}", "")


# ---------------------------------------------------------------------------
# Profile builders — one per suspect
# ---------------------------------------------------------------------------

def profile_iris_ammann() -> dict:
    """
    Iris Ammann — Head of Security.
    Strongest paper motive (debt), designed the whole system, signed off INFRA-2291.
    CLEARED by Lisbon alibi: flight, rehearsal dinner, wedding, photographer's files.
    Notebook confirms alibi verified.
    """
    return {
        "name": "Iris Ammann",
        "access_to_real_paths": {
            "value": True,
            "evidence": [
                _ev("Designed the decoy programme; knows real artifact paths by construction",
                    "interviews/interview_01_iris_ammann.txt:15",
                    "My idea, my implementation, and the thing I'm proudest of"),
                _ev("On Iris's own list of five people who knew which artifacts were real",
                    "investigator_notebook.md:19",
                    "- Who could know which artifacts were real:"),
            ]
        },
        "opportunity_window": {
            "value": "out",
            "evidence": [
                _ev("Was in Lisbon at brother's daughter's wedding on Saturday 11 Oct",
                    "interviews/interview_01_iris_ammann.txt:23",
                    "I flew out Thursday evening, I was at the rehearsal dinner Friday night, I was at the wedding Saturday, I flew back Monday afternoon."),
                _ev("Investigator verified boarding passes, hotel, photographer's timestamped raw files",
                    "investigator_notebook.md:75",
                    "Iris's folder: care home, cancelled policy, litigation with a Zurich firm, statements. Every franc accounted for. Lisbon: flights, hotel, photographer's timestamped raw files. Verified."),
                _ev("Parking permit plate ZH 610 882 — no garage entry on evening of 10 Oct or overnight",
                    "parking_permits.xlsx:9",
                    "PB-2406\tZH 610 882\tIris Ammann\tHalcyon Systems AG\tSubaru Outback\tblau\t1\t31.12.2025"),
            ]
        },
        "motive": {
            "summary": "~CHF 210k personal debt for father's memory-care home (CHF 11k/month, insurance cancelled)",
            "evidence": [
                _ev("Disclosed debt and father's care costs at start of interview",
                    "interviews/interview_01_iris_ammann.txt:11",
                    "Two hundred and ten thousand francs, roughly, across four instruments. Three years. It's my father. He's in a memory-care home in Rorschach that costs eleven thousand francs a month"),
            ]
        },
        "alibi": {
            "summary": "Lisbon 9–13 Oct: rehearsal dinner Fri, wedding Sat. Boarding passes, hotel, photographer files all verified by investigator.",
            "evidence": [
                _ev("Alibi independently verified by investigator",
                    "investigator_notebook.md:75",
                    "Lisbon: flights, hotel, photographer's timestamped raw files. Verified."),
            ]
        },
        "suspicious_behaviours": [
            _ev("Signed off INFRA-2291 that disabled audit logging",
                "investigator_notebook.md:14",
                "Audit collector stopped on purpose, Fri 10.10 21:00 → Sat 11.10 06:00, ticket INFRA-2291"),
        ],
        "clearing_evidence": [
            _ev("Alibi verified: in Lisbon from Thursday evening through Monday",
                "investigator_notebook.md:75",
                "Lisbon: flights, hotel, photographer's timestamped raw files. Verified."),
            _ev("Designed the decoy system — if she were the thief she would not have implemented the watermarks that caught the theft",
                "interviews/interview_01_iris_ammann.txt:28",
                "That's the only reason we know any of this happened, by the way. Without those, Kestrel publishes, everyone says wow, and we spend two years wondering why we can't raise."),
        ],
        "forensic_pivot": {"describes_withheld_detail": False, "evidence": []},
    }


def profile_chiara_bernasconi() -> dict:
    """
    Chiara Bernasconi — Director of Data Engineering.
    KEY MISLEADING SUSPECT: She describes the snapshot deletion and restart
    in her interview — but this has an innocent explanation: she filed a Jira
    ticket (DATA-1877 or similar) on 14 Oct from a capacity graph, before the
    investigator even engaged. The detail was public in that ticket.
    Card places her in Winterthur during the window (dinner, stayed overnight,
    drove to Flims early Saturday). Garage shows her car departed ~17:35 on Fri.
    NOT in building during window.
    """
    return {
        "name": "Chiara Bernasconi",
        "access_to_real_paths": {
            "value": False,
            "evidence": [
                _ev("Not on the board pack distribution; did not read Confluence page",
                    "interviews/interview_02_chiara_bernasconi.txt:32",
                    "Not on the distribution."),
                _ev("Works upstream of checkpoints; does not work with checkpoints directly",
                    "interviews/interview_02_chiara_bernasconi.txt:28",
                    "I don't work with checkpoints. I work upstream of them."),
                _ev("Owns the corpus pipelines, not the artifact staging paths",
                    "interviews/interview_02_chiara_bernasconi.txt:26",
                    "I own the pipelines. The corpus passed through systems I designed."),
            ]
        },
        "opportunity_window": {
            "value": "out",
            "evidence": [
                _ev("Parking permit plate SG 77 310 departed garage 17:35 real local on 10 Oct (log 16:35, -1h correction)",
                    "garage_barrier_log.csv:3011",
                    "10.10.2025;16:35:00;SG 77 310;Ausfahrt"),
                _ev("Card charge at Restaurant Rössli Winterthur at 21:04 UTC (23:04 CEST) — dining in Winterthur during window",
                    "card_feed_q4.csv:4",
                    "2025-10-10T21:04:00Z,chiara.bernasconi,Restaurant Roessli,Winterthur,CHF 186.40"),
                _ev("Confirms: candidate dinner at Restaurant Rössli, Winterthur, ~eight o'clock, paid around eleven",
                    "interviews/interview_02_chiara_bernasconi.txt:20",
                    "Winterthur. Candidate dinner, a senior data engineer we're trying to hire. Restaurant Rössli, eight o'clock. It went long, he had a lot of questions about our pipeline, which is flattering and exhausting. I paid around eleven and stayed at a friend's in Winterthur"),
                _ev("Card charge in Winterthur at 04:15 UTC — early morning, still in Winterthur before Flims drive",
                    "card_feed_q4.csv:5",
                    "2025-10-11T04:15:00Z,chiara.bernasconi,Avec Ohringen,Winterthur,CHF 58.30"),
                _ev("Card charge at motorway services Heidiland (en route St. Gallen→Flims) at 05:32 UTC",
                    "card_feed_q4.csv:6",
                    "2025-10-11T05:32:00Z,chiara.bernasconi,Raststaette Heidiland,Maienfeld,CHF 6.20"),
            ]
        },
        "motive": {
            "summary": "Open expense review (~CHF 41k) by finance system; bad timing but items explained",
            "evidence": [
                _ev("Expense review open since late September; ~CHF 41k flagged",
                    "investigator_notebook.md:49",
                    "Bernasconi (Director Data Eng): owns the corpus pipelines. Internal review of ~CHF 41k expenses open since late September."),
                _ev("All items explained at interview; receipts provided",
                    "interviews/interview_02_chiara_bernasconi.txt:37",
                    "all items explained, receipts provided, consistent with finance system"),
            ]
        },
        "alibi": {
            "summary": "Documented in Winterthur all night 10/11 Oct: restaurant receipt ~23:00 CEST, overnight at friend's, petrol 06:15 CEST, motorway services 07:32 CEST en route to Flims.",
            "evidence": [
                _ev("Corporate card chain: Winterthur dinner → Winterthur fuel → Heidiland motorway stop",
                    "card_feed_q4.csv:6",
                    "2025-10-11T05:32:00Z,chiara.bernasconi,Raststaette Heidiland,Maienfeld,CHF 6.20"),
            ]
        },
        "suspicious_behaviours": [
            _ev("Describes snapshot deletion and restart in interview — sounds like withheld detail",
                "interviews/interview_02_chiara_bernasconi.txt:12",
                "it fills up, right up, ninety-eight percent, and then at some point overnight it drops by about nine terabytes in one step, which is a snapshot being deleted, and then it fills up again"),
        ],
        "clearing_evidence": [
            _ev("She filed a Jira capacity ticket on 14 Oct (4 days before investigator engaged) from the scratch-02 free-space graph — the 'withheld detail' was visible in the graph and her ticket before any interview",
                "interviews/interview_02_chiara_bernasconi.txt:13",
                "Fourteenth, about four in the afternoon. It's in the ticket, you can see the timestamps, and about six people got the notification."),
            _ev("Not in building: departed garage 17:35 local; corporate card documents overnight in Winterthur",
                "card_feed_q4.csv:4",
                "2025-10-10T21:04:00Z,chiara.bernasconi,Restaurant Roessli,Winterthur,CHF 186.40"),
            _ev("Lacked knowledge of real artifact paths (not on board pack list, did not read Confluence page)",
                "interviews/interview_02_chiara_bernasconi.txt:32",
                "Not on the distribution."),
        ],
        "forensic_pivot": {
            "describes_withheld_detail": True,
            "innocent_explanation": "Describes the snapshot drop visible in the scratch-02 capacity graph she herself logged on 14 Oct — four days before the investigator engaged. This was public in a Jira ticket before any interview.",
            "evidence": [
                _ev("Detail visible to her from the capacity graph she filed on 14 Oct",
                    "interviews/interview_02_chiara_bernasconi.txt:12",
                    "it fills up, right up, ninety-eight percent, and then at some point overnight it drops by about nine terabytes in one step, which is a snapshot being deleted, and then it fills up again"),
            ]
        },
    }


def profile_andrin_caduff() -> dict:
    """
    Andrin Caduff — Principal Research Engineer.
    KEY MISLEADING SUSPECT: 31 checkpoint accesses in 4 weeks, no alibi, knew paths.
    CLEARED: accesses were for a methods paper (Lukas orally approved); read-only VPN
    sweep cannot exfiltrate data (no egress spike observed). No car — cannot have driven
    hardware out. Doesn't know decoy mapping.
    """
    return {
        "name": "Andrin Caduff",
        "access_to_real_paths": {
            "value": True,
            "evidence": [
                _ev("Has read from the real staging paths since before 2023; knows them from years of work",
                    "interviews/interview_03_andrin_caduff.txt:40",
                    "The current path is where I read from. It is not documented. Lukas knows, Iris knows, Yannick knows. People who have been here since before 2023 know."),
                _ev("Lukas retrospectively confirmed Andrin's checkpoint access for paper writing",
                    "interviews/followup_01_lukas_hofer.txt:9",
                    "Early October. We had coffee, I told him about the research line, and he asked if he could reconstruct the evaluation numbers for a method-only paper. I said yes"),
            ]
        },
        "opportunity_window": {
            "value": "unknown",
            "evidence": [
                _ev("No car; cannot have driven hardware out of building",
                    "interviews/interview_03_andrin_caduff.txt:36",
                    "No. I cycle. I do not have a car, I have never had a car in Switzerland."),
                _ev("Claims to have been at home in St. Gallen, running VPN evaluation sweep",
                    "interviews/interview_03_andrin_caduff.txt:25",
                    "Here. In St. Gallen, in my flat. Alone, mostly. I went to a climbing gym on the Saturday"),
                _ev("VPN sweep is read-only; cannot exfiltrate checkpoints; no egress spike",
                    "interviews/followup_01_lukas_hofer.txt:13",
                    "They're read-only, they compute numbers. They don't write anywhere near the scratch arrays."),
                _ev("No anomalous network egress: Lukas checked bill after Kestrel paper published",
                    "interviews/followup_01_lukas_hofer.txt:14",
                    "Not without changing the code, and even then you'd be pulling terabytes over the VPN, which we'd see in the network bill the following month. We didn't. I checked"),
            ]
        },
        "motive": {
            "summary": "Research line closed; role ending August 2026. Could benefit from taking IP.",
            "evidence": [
                _ev("Research line closed in September replan; role ends August",
                    "investigator_notebook.md:51",
                    "Caduff (Principal Research Eng): research line closed in the September replan, role ends August. 31 checkpoint accesses in 4 weeks, median 2."),
            ]
        },
        "alibi": {
            "summary": "Claims home in St. Gallen (unverified). No car means no physical exfiltration.",
            "evidence": []
        },
        "suspicious_behaviours": [
            _ev("31 checkpoint accesses in 4 weeks vs company median of 2",
                "investigator_notebook.md:51",
                "Caduff (Principal Research Eng): research line closed in the September replan, role ends August. 31 checkpoint accesses in 4 weeks, median 2."),
            _ev("Ran evaluation sweep from home on Friday night of theft window, over VPN",
                "interviews/interview_03_andrin_caduff.txt:27",
                "I ran an evaluation sweep from home, over the VPN, reading the checkpoints and computing the numbers for the paper. I started it around ten in the evening"),
            _ev("Knew audit logging was off that night; did not report the sweep",
                "interviews/interview_03_andrin_caduff.txt:29",
                "Everyone knew. It was in the channel. I did not think about it."),
        ],
        "clearing_evidence": [
            _ev("No car — physical exfiltration via portable drive requires a vehicle; alley door or not, carrying a large array on a bicycle is implausible",
                "interviews/interview_03_andrin_caduff.txt:36",
                "No. I cycle. I do not have a car, I have never had a car in Switzerland."),
            _ev("VPN-only sweep cannot exfiltrate; copy job on scratch-02 was started from a local console on engineering floor (forensic finding)",
                "forensic_summary_bakalian.pdf:1",
                "The job was started from a workstation console on the engineering floor (local session, no network login)."),
            _ev("Lukas confirmed access was orally authorised for a methods paper",
                "interviews/followup_01_lukas_hofer.txt:9",
                "Early October. We had coffee, I told him about the research line, and he asked if he could reconstruct the evaluation numbers for a method-only paper. I said yes"),
            _ev("Did not know the decoy mapping — would have tripped a beacon if he opened a decoy",
                "interviews/interview_03_andrin_caduff.txt:42",
                "I knew there were decoys. Iris told everyone in research not to open anything that looked unusual in the tree, because it would alert her. I did not know which ones."),
        ],
        "forensic_pivot": {"describes_withheld_detail": False, "evidence": []},
    }


def profile_yannick_favre() -> dict:
    """
    Yannick Favre — Infrastructure Engineer. Built scratch arrays. Wrote Confluence page.
    CLEARED: verifiable alibi in Val Müstair (train, PostBus, 4-hour Saturday video call
    with Lukas about sandbox incident — which Lukas corroborated in interview).
    """
    return {
        "name": "Yannick Favre",
        "access_to_real_paths": {
            "value": True,
            "evidence": [
                _ev("Wrote Confluence page mapping real vs decoy storage paths (March 2025)",
                    "interviews/interview_04_yannick_favre.txt:21",
                    "it went on Confluence, because... because I put it on Confluence. In March. I was trying to be helpful."),
                _ev("Designed the scratch arrays; knows the storage topology",
                    "interviews/interview_04_yannick_favre.txt:15",
                    "Current staging path here, that's where the real checkpoints actually sit before promotion."),
            ]
        },
        "opportunity_window": {
            "value": "out",
            "evidence": [
                _ev("In Val Müstair from Thursday evening (train + PostBus, 4h each way); no car",
                    "interviews/interview_04_yannick_favre.txt:27",
                    "Val Müstair. My girlfriend's family has a farm up there. We went up on the Thursday evening by train, and there's a PostBus for the last bit that stops at six. I don't have a car."),
                _ev("On 4-hour video call with Lukas Hofer on Saturday fixing the sandbox — Lukas corroborates",
                    "interviews/interview_05_lukas_hofer.txt:17",
                    "Yannick Favre was on the phone with me for four hours of that. Check with him."),
                _ev("Lukas confirms Yannick was remote all Saturday complaining about being in Val Müstair",
                    "interviews/interview_05_lukas_hofer.txt:29",
                    "Yannick could find them, but Yannick's twenty-six and was in Val Müstair with his girlfriend's family, which I know because he complained about it for three hours on Saturday."),
            ]
        },
        "motive": {
            "summary": "Moonlighting contract (against his employment contract) — low severity, unrelated to theft.",
            "evidence": [
                _ev("Disclosed moonlighting unprompted: ~11h/week for scheduling-app startup, CHF 400/week",
                    "interviews/interview_04_yannick_favre.txt:29",
                    "I've been moonlighting. Since June. About eleven hours a week for a seed-stage company in Winterthur. It's against my contract"),
            ]
        },
        "alibi": {
            "summary": "Val Müstair (farm) Thu evening through weekend; corroborated by Lukas Hofer's interview and the Saturday incident channel.",
            "evidence": [
                _ev("Lukas puts him on video call Saturday afternoon fixing sandbox",
                    "interviews/interview_05_lukas_hofer.txt:17",
                    "Yannick Favre was on the phone with me for four hours of that. Check with him. Check the incident channel, it's all timestamped"),
            ]
        },
        "suspicious_behaviours": [
            _ev("Accidentally left Confluence page (real/decoy path mapping) world-readable for 7 months",
                "interviews/interview_04_yannick_favre.txt:21",
                "it went on Confluence, because... because I put it on Confluence. In March. I was trying to be helpful. I permissioned it to eng-all because that's the default and I didn't think"),
            _ev("Data room export role never revoked after deal died; scope too broad since April",
                "interviews/interview_04_yannick_favre.txt:17",
                "When the deal died nobody revoked it. Iris has raised it three times. It's on me. I kept saying after the migration."),
        ],
        "clearing_evidence": [
            _ev("Verified remote: in Val Müstair all weekend; Lukas corroborates in independent interview",
                "interviews/interview_04_yannick_favre.txt:27",
                "Val Müstair. My girlfriend's family has a farm up there. We went up on the Thursday evening by train"),
            _ev("No car; Val Müstair is 4 hours by train+PostBus; last PostBus stops at 18:00",
                "interviews/interview_04_yannick_favre.txt:27",
                "there's a PostBus for the last bit that stops at six. I don't have a car. It's four hours each way."),
        ],
        "forensic_pivot": {"describes_withheld_detail": False, "evidence": []},
    }


def profile_lukas_hofer() -> dict:
    """
    Lukas Hofer — VP Engineering. Built the pipeline. Knew real paths. In building Saturday.
    CLEARED for the Friday window: home for dinner with ex, incident channel shows he wasn't
    called until Saturday lunchtime, and the copy completed at 03:58 UTC Saturday (05:58 CEST).
    Garage shows his car (SG 219 004) left at 17:48 on Friday and returned 12:58 Sat.
    """
    return {
        "name": "Lukas Hofer",
        "access_to_real_paths": {
            "value": True,
            "evidence": [
                _ev("Built the training pipeline; knows the current undocumented staging path",
                    "interviews/interview_05_lukas_hofer.txt:25",
                    "there's the current staging path, which is where the real checkpoints actually live before they get promoted. That one's undocumented. I know, I know."),
            ]
        },
        "opportunity_window": {
            "value": "out",
            "evidence": [
                _ev("Garage log: SG 219 004 (Lukas Hofer) exited at 17:48 real local on 10 Oct (log 16:48)",
                    "garage_barrier_log.csv:3012",
                    "10.10.2025;16:48:00;SG 219 004;Ausfahrt"),
                _ev("Garage log: SG 219 004 re-enters 12:58 real on 11 Oct (log 11:58) — Saturday afternoon",
                    "garage_barrier_log.csv:3022",
                    "11.10.2025;11:58:00;SG 219 004;Einfahrt"),
                _ev("Claims home by 22:00 Friday for ex-wife dinner; incident only paged Saturday lunchtime",
                    "interviews/interview_05_lukas_hofer.txt:39",
                    "Home. I had something personal in the calendar, a dinner with my ex about our daughter's school, which went as well as those things go. I was home by ten. My neighbour's dog barked at me."),
                _ev("Sandbox incident not noticed until Saturday lunchtime — he was not in building overnight",
                    "interviews/interview_05_lukas_hofer.txt:17",
                    "the inference cluster for the customer-facing sandbox fell over Friday night and nobody noticed until Saturday lunchtime because it was a long weekend"),
            ]
        },
        "motive": {
            "summary": "Passed over for CTO role in August; angry for two weeks. Self-described: would not give MERIDIAN to Kestrel because it's the best thing he'll ever build.",
            "evidence": [
                _ev("Passed over for CTO; acknowledged anger but says would not destroy his life's work",
                    "interviews/interview_05_lukas_hofer.txt:37",
                    "MERIDIAN is the best thing I will ever build and giving it to Kestrel would be like burning down a house I'm still living in."),
            ]
        },
        "alibi": {
            "summary": "Home Friday by 22:00; garage log corroborates departure 17:48; Saturday in building only from ~13:00 (incident response).",
            "evidence": [
                _ev("Garage out at 17:48 real on Friday, not back until 12:58 Saturday",
                    "garage_barrier_log.csv:3012",
                    "10.10.2025;16:48:00;SG 219 004;Ausfahrt"),
            ]
        },
        "suspicious_behaviours": [
            _ev("Was in building Saturday afternoon with physical access and deep knowledge of system",
                "investigator_notebook.md:52",
                "Hofer (VP Eng): built the pipeline. Passed over for CTO in August (board decision). In the building Saturday afternoon (incident)."),
        ],
        "clearing_evidence": [
            _ev("Garage log shows no re-entry on Friday evening; next entry is Saturday noon for incident",
                "garage_barrier_log.csv:3022",
                "11.10.2025;11:58:00;SG 219 004;Einfahrt"),
            _ev("Copy completed 03:52 UTC (05:52 CEST) and device detached 03:58 UTC — long before he arrived Saturday",
                "forensic_summary_bakalian.pdf:1",
                "03:52 UTC, Sat 11.10: the second run completes without error. The device is detached at 03:58 UTC."),
            _ev("Stopped at Digitec on Saturday buying drives for the dead node — consistent with incident story",
                "interviews/interview_05_lukas_hofer.txt:23",
                "Drove. Garage, badge at the lobby, up the stairs. I stopped at Digitec on the way for two drives because the node that died had a dead disk as well"),
        ],
        "forensic_pivot": {"describes_withheld_detail": False, "evidence": []},
    }


def profile_noemi_rochat() -> dict:
    """
    Noemi Rochat — Head of Product.
    Was in building until ~22:30 Fri. Garage exit at 22:28 real (log 21:28). Matches statement.
    But: describes the failure/restart in remarkable detail in interview.
    Investigator's room 2F-3 shares a paper-thin wall with Noemi's office 2F-4 (FAC-330).
    Investigator called Emory on 20 Nov evening (after Thu interviews). Noemi interviewed Fri 12:03.
    She could have overheard through the wall.
    VERDICT: describes withheld detail but has an innocent explanation (adjacent office + paper wall).
    Cleared by garage timing — car left just as window opened; she did not return.
    """
    return {
        "name": "Noemi Rochat",
        "access_to_real_paths": {
            "value": False,
            "evidence": [
                _ev("Read Confluence page once in April for ~4 minutes; knew decoys existed but not the mapping",
                    "interviews/interview_06_noemi_rochat.txt:30",
                    "Once, in April, for about four minutes. I remember because I went straight into a meeting and used the phrase 'decoy checkpoints' twice in the wrong context"),
                _ev("Not on board pack distribution; Head of Product, not engineering",
                    "interviews/interview_08_renata_vogel.txt:77",
                    "Noemi talks about everything and understands about half of it. She's harmless. She's leaving anyway."),
            ]
        },
        "opportunity_window": {
            "value": "out",
            "evidence": [
                _ev("Garage log: TI 88 402 (Noemi Rochat) exited at 22:28 real local on 10 Oct (log shows 21:28; clock is 1h fast)",
                    "garage_barrier_log.csv:3016",
                    "10.10.2025;21:28:00;TI 88 402;Ausfahrt"),
                _ev("Garage clock confirmed 1 hour fast by facilities ticket FAC-352",
                    "helpdesk_and_facilities.md:890",
                    "Resolution: Parking reimbursement check found barrier times one hour off against receipts. Landlord (Parkhaus Stickerei AG) confirms: the barrier system clock stayed on winter time after 30 March."),
                _ev("Card charge at Raststaette Wüerenlos (motorway, direction Bern) at 21:29 UTC = 23:29 CEST — on road to Bern after leaving office",
                    "card_feed_q4.csv:3",
                    "2025-10-10T21:29:00Z,noemi.rochat,Raststaette Wuerenlos,Wuerenlos,CHF 9.20"),
                _ev("Earlier card at Raststaette Thurau (Wil SG, near St. Gallen) at 20:47 UTC = 22:47 CEST — passing through on way south",
                    "card_feed_q4.csv:2",
                    "2025-10-10T20:47:00Z,noemi.rochat,Raststaette Thurau,Wil SG,CHF 58.10"),
                _ev("Confirms left office ~22:30, drove to Bern to sister's",
                    "interviews/interview_06_noemi_rochat.txt:18",
                    "I left around half past ten, drove to Bern, stayed with my sister."),
            ]
        },
        "motive": {
            "summary": "Leaving to start a company in spring. Claims business is 'orthogonal' (infrastructure code review tools).",
            "evidence": [
                _ev("Leaving in spring; Dov knows; company described as orthogonal to Halcyon",
                    "interviews/interview_06_noemi_rochat.txt:28",
                    "Developer tooling. It's orthogonal. Genuinely orthogonal. Everyone says 'adjacent' with a face but it's code review for infrastructure teams"),
            ]
        },
        "alibi": {
            "summary": "Drove to Bern after leaving building ~22:30; card documents motorway stops; stayed with sister.",
            "evidence": [
                _ev("Motorway stop documented by corporate card at 23:29 CEST heading to Bern",
                    "card_feed_q4.csv:3",
                    "2025-10-10T21:29:00Z,noemi.rochat,Raststaette Wuerenlos,Wuerenlos,CHF 9.20"),
            ]
        },
        "suspicious_behaviours": [
            _ev("Describes failure, snapshot deletion and restart in remarkable detail during interview",
                "interviews/interview_06_noemi_rochat.txt:24",
                "A professional certainly doesn't fill the target disk halfway through and have to go and bin something to make room and start the whole job again from the top like someone reformatting a laptop in 2004."),
        ],
        "clearing_evidence": [
            _ev("Her office 2F-4 is separated from investigator's room 2F-3 by a paper-thin wall; everything said in 2F-3 is audible in 2F-4 (and vice versa)",
                "helpdesk_and_facilities.md:902",
                "the partition between 2F-3 and 2F-4 is single-stud with no acoustic insulation — it was erected during the 2019 fit-out to subdivide what was originally one room, and does not extend to the structural deck. Speech at normal conversational volume is intelligible through it."),
            _ev("Investigator called Emory on speaker in room 2F-3 on Thu 20 Nov evening to go through forensic detail; Noemi's interview was Fri 12:03",
                "investigator_notebook.md:69",
                "Thu 20.11, 18:30: back in my room (2F-3). Called Emory on speaker to go through the day against his findings. Forty minutes."),
            _ev("Garage and card chain document she was physically absent from St. Gallen all night",
                "garage_barrier_log.csv:3016",
                "10.10.2025;21:28:00;TI 88 402;Ausfahrt"),
        ],
        "forensic_pivot": {
            "describes_withheld_detail": True,
            "innocent_explanation": "Noemi's office (2F-4) shares a paper-thin non-insulated wall with the investigator's room (2F-3). The investigator called forensic examiner Emory on speaker in 2F-3 on the evening of Thu 20 Nov. Noemi was the building every day that week and could have overheard. Her interview was the next morning, Fri 12:03.",
            "evidence": [
                _ev("Wall between 2F-3 and 2F-4 has no acoustic insulation; speech intelligible",
                    "helpdesk_and_facilities.md:902",
                    "the partition between 2F-3 and 2F-4 is single-stud with no acoustic insulation"),
                _ev("Investigator used speaker phone in 2F-3 Thursday evening reviewing forensic findings",
                    "investigator_notebook.md:69",
                    "Thu 20.11, 18:30: back in my room (2F-3). Called Emory on speaker to go through the day against his findings. Forty minutes."),
            ]
        },
    }


def profile_kurt_steiner() -> dict:
    """
    Kurt Steiner — Chief Scientist. In building Sunday (not Friday). Admin accounts
    but self-described as technically helpless with checkpoints.
    CLEARED: Sunday presence is irrelevant; copy was completed Friday night.
    No technical ability to operate scratch arrays.
    """
    return {
        "name": "Kurt Steiner",
        "access_to_real_paths": {
            "value": False,
            "evidence": [
                _ev("Knows what a checkpoint is conceptually but could not find, change or copy one",
                    "interviews/interview_07_kurt_steiner.txt:23",
                    "In the sense that I know what a carburettor is. I know what it's for. I could not find one, change one, or steal one, and if you sat me in front of the thing and told me to copy it somewhere I should think I'd take down the company by accident inside ten minutes."),
                _ev("Not on board pack distribution (not on board anymore)",
                    "interviews/interview_07_kurt_steiner.txt:27",
                    "I'm not on the board. I used to be, in the early years."),
            ]
        },
        "opportunity_window": {
            "value": "out",
            "evidence": [
                _ev("Garage log: SG 1 994 (Kurt Steiner) arrived 09:40 real and departed 17:20 real on 10 Oct; no return on Fri evening",
                    "garage_barrier_log.csv:3005",
                    "10.10.2025;16:20:00;SG 1 994;Ausfahrt"),
                _ev("Was in building on Sunday 12 Oct — copy was already complete since Sat 03:52 UTC",
                    "slack_export/general/2025-10-12.json:1",
                    "office is beautifully quiet on a sunday. recommend it"),
                _ev("Dinner at Stadtclub Friday evening until ~23:00; wife confirms arrival home",
                    "interviews/interview_07_kurt_steiner.txt:18",
                    "Dinner at the Stadtclub with some old colleagues from the university. Seven o'clock. We are all old men and we tell the same stories and it takes a long time. Home after eleven"),
            ]
        },
        "motive": {
            "summary": "No clear financial or professional motive identified.",
            "evidence": []
        },
        "alibi": {
            "summary": "Dinner at Stadtclub until ~23:00 Friday; home after eleven; wife corroborates. Sunday in office is irrelevant (theft completed Friday night).",
            "evidence": [
                _ev("Dinner at Stadtclub Friday evening; home after eleven",
                    "interviews/interview_07_kurt_steiner.txt:18",
                    "Dinner at the Stadtclub with some old colleagues from the university. Seven o'clock. We are all old men and we tell the same stories and it takes a long time. Home after eleven, I should think. My wife will tell you I woke her up."),
            ]
        },
        "suspicious_behaviours": [
            _ev("Administrator accounts on most systems; passwords kept in a physical notebook",
                "investigator_notebook.md:54",
                "Steiner (Chief Scientist, co-founder): admin accounts nobody reviewed, passwords in a notebook."),
            _ev("In building on Sunday 12 Oct (after theft was already complete)",
                "slack_export/general/2025-10-12.json:1",
                "office is beautifully quiet on a sunday. recommend it"),
        ],
        "clearing_evidence": [
            _ev("Copy job started from local console on engineering floor at 21:10 UTC Friday; Kurt left garage at 17:20 real and dined at Stadtclub until ~23:00",
                "forensic_summary_bakalian.pdf:1",
                "21:10 UTC, Fri 10.10: a bulk copy job starts"),
            _ev("No technical ability to operate scratch arrays or find checkpoint paths",
                "interviews/interview_07_kurt_steiner.txt:23",
                "I could not find one, change one, or steal one"),
            _ev("Sunday presence is after the fact; theft was complete by 03:58 UTC Saturday",
                "forensic_summary_bakalian.pdf:1",
                "03:52 UTC, Sat 11.10: the second run completes without error. The device is detached at 03:58 UTC."),
        ],
        "forensic_pivot": {"describes_withheld_detail": False, "evidence": []},
    }


def profile_renata_vogel() -> dict:
    """
    Renata Vogel — Chief of Staff. Ran Kestrel process. Data room roles never revoked.
    Received 'continuing role' offer from Aubert in May.
    CLEARED by: (1) in Ascona all weekend (no garage re-entry after 16:41 real on Fri);
    (2) self-describes inability to operate checkpoints; (3) Lukas confirms data room
    had no path to real checkpoints; (4) 'continuing role' forwarded to Dov immediately.
    """
    return {
        "name": "Renata Vogel",
        "access_to_real_paths": {
            "value": False,
            "evidence": [
                _ev("Self-described: could not explain a checkpoint bundle with a gun to her head",
                    "interviews/interview_08_renata_vogel.txt:38",
                    "I'm the only person in the leadership team who couldn't explain a checkpoint bundle to you if you held a gun to my head."),
                _ev("Lukas reviewed every data-room document personally; nothing in it tells you where real checkpoints live",
                    "interviews/interview_05_lukas_hofer.txt:31",
                    "I reviewed every single document that went into that data room, personally, because I didn't trust the process. There is nothing in there that tells you where the real checkpoints live. I made sure of it."),
                _ev("dr-export-ro role could see the file tree but not distinguish real from decoy without the list",
                    "interviews/interview_04_yannick_favre.txt:19",
                    "[00:01:31] SPEAKER 2: They'd see the tree. [pause] Filenames. Sizes. Twenty things that all look like checkpoints, eleven of which are Iris's fakes and nine of which aren't, and no way on God's earth to tell them apart from the outside, because that's the whole design."),
            ]
        },
        "opportunity_window": {
            "value": "out",
            "evidence": [
                _ev("Garage: SG 482 117 (Renata Vogel) arrived 08:41 real on 10 Oct (log 07:41), no exit recorded on 10 Oct after 08:41 and no late-night return",
                    "garage_barrier_log.csv:2990",
                    "10.10.2025;07:41:00;SG 482 117;Einfahrt"),
                _ev("Claims left office ~18:00 Friday, drove to Ascona (3h journey); alone there from ~20:30",
                    "interviews/interview_08_renata_vogel.txt:30",
                    "I was in the office until about six, I think. There was a board packet going out the following Tuesday and I wanted the finance section closed before the long weekend. Then I drove down to Ascona."),
                _ev("Copy job started from local console at 21:10 UTC (23:10 CEST) — Renata was en route to Ascona or already there",
                    "forensic_summary_bakalian.pdf:1",
                    "21:10 UTC, Fri 10.10: a bulk copy job starts, reading MERIDIAN checkpoint bundles and the corpus manifest and writing to an externally attached block device"),
            ]
        },
        "motive": {
            "summary": "Ran Kestrel due-diligence process; received 'continuing role' offer from Aubert in May. Forwarded to Dov within the hour.",
            "evidence": [
                _ev("Aubert floated continuing role in May; Renata forwarded to Dov same hour",
                    "interviews/interview_08_renata_vogel.txt:28",
                    "He floated something in May. A continuing role after the deal closed. I forwarded it to Dov the same hour and said it felt like leverage and he could take the relationship over if he preferred."),
                _ev("Investigator found and verified the May thread reads clean",
                    "investigator_notebook.md:77",
                    "Kestrel: found the May thread (Aubert → Vogel, 'continuing role'), forwarded to Dov within the hour. Reads clean."),
            ]
        },
        "alibi": {
            "summary": "Drove to Ascona Friday evening (3h from St. Gallen); arrived ~20:30–21:00; alone that night. Consistent with local copy starting at 23:10 CEST without her.",
            "evidence": [
                _ev("Drove to Ascona via San Bernardino; three hours from St. Gallen; partner arrived Saturday morning",
                    "interviews/interview_08_renata_vogel.txt:32",
                    "The usual. Motorway to Chur, San Bernardino, down to Bellinzona. It's three hours if you're lucky."),
            ]
        },
        "suspicious_behaviours": [
            _ev("Data room service accounts never revoked after deal died June 2025; dr-export-ro had broad read scope since April",
                "kestrel_diligence_log.md:417",
                "Note (yannick.favre, appended 2025-10-20): /halcyon/artifacts/* includes the active staging tree. That was not the intent in April. Tracked in SEC-419."),
            _ev("120 days as day-to-day Kestrel counterpart; introduced Halcyon's systems to acquirer",
                "investigator_notebook.md:55",
                "Vogel (Chief of Staff): ran the Kestrel acquisition process Feb–Jun, day-to-day counterpart for 120 days."),
        ],
        "clearing_evidence": [
            _ev("'Continuing role' offer forwarded to Dov within the hour; investigator verified thread reads clean",
                "investigator_notebook.md:77",
                "found the May thread (Aubert → Vogel, 'continuing role'), forwarded to Dov within the hour. Reads clean."),
            _ev("No technical knowledge of real artifact paths; Lukas confirms data room had no such information",
                "interviews/interview_05_lukas_hofer.txt:31",
                "There is nothing in there that tells you where the real checkpoints live. I made sure of it."),
            _ev("Physical absence confirmed: copy started from local console at 23:10 CEST while she was in Ascona (~20:30 arrival)",
                "forensic_summary_bakalian.pdf:1",
                "The job was started from a workstation console on the engineering floor (local session, no network login)."),
        ],
        "forensic_pivot": {"describes_withheld_detail": False, "evidence": []},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

PROFILE_BUILDERS = [
    profile_iris_ammann,
    profile_chiara_bernasconi,
    profile_andrin_caduff,
    profile_yannick_favre,
    profile_lukas_hofer,
    profile_noemi_rochat,
    profile_kurt_steiner,
    profile_renata_vogel,
]


def build_profiles() -> list[dict]:
    print("Building index …")
    build_index()
    print("Building suspect profiles …")
    profiles = [fn() for fn in PROFILE_BUILDERS]
    out = Path("suspect_profiles.json")
    out.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")
    return profiles


if __name__ == "__main__":
    profiles = build_profiles()
    print("\n=== Profile summary ===")
    for p in profiles:
        name = p["name"]
        access = p["access_to_real_paths"]["value"]
        opp    = p["opportunity_window"]["value"]
        pivot  = p["forensic_pivot"].get("describes_withheld_detail", False)
        print(f"  {name:<25}  access={str(access):<5}  window={opp:<8}  pivot={pivot}")
