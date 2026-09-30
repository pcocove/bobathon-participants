# Bonus: How to stop a repeat

Each proposal below is grounded in a specific gap identified in the case files,
with the exact source citation used in the investigation.

---

## 1 — Enforce immediate credential revocation on deal termination

**Gap found:** After the Kestrel acquisition process collapsed on 24 June 2025,
the data-room service accounts were never revoked. The `dr-export-ro` role
retained read access to `/halcyon/artifacts/*` — a prefix that inadvertently
included the active model-staging tree — for more than three months.
Security lead Iris Ammann raised it in three consecutive standups and filed
it as SEC-419, but the ticket sat open until after the theft.

**Source:**
- `kestrel_diligence_log.md:412`: `**Roles revoked:** —`
- `kestrel_diligence_log.md:417`: `dr-export-ro | Service | 2025-04-03 | Read, storage prefix /halcyon/artifacts/* (broadened 03 Apr under time pressure; never re-scoped) | —`
- `jira_export.json:7280`: `"summary": "Revoke Kestrel diligence service accounts and scoped roles"`
- `jira_export.json:7301`: `"body": "After the migration, I promise."`

**Recommendation:** Treat deal-closure as a hard trigger. Add a mandatory
checklist item to the deal-closing workflow: all service accounts and external
credentials provisioned for the process must be revoked within 24 hours of
deal termination. Automate the revocation step; do not rely on a Jira ticket
assigned to a single engineer.

---

## 2 — Never disable audit logging and SIEM simultaneously

**Gap found:** Ticket INFRA-2291 shut down the audit collector and the SIEM
cold tier at the same time for a nine-hour window, because both wrote to the
same backend that was being migrated. This created a complete blind spot —
no session logs, no egress records, nothing. About 40 people knew the window
was coming.

**Source:**
- `investigator_notebook.md:14`: `Audit collector stopped on purpose, Fri 10.10 21:00 → Sat 11.10 06:00, ticket INFRA-2291. SIEM cold tier pointed at the same backend, so no copy. ~40 people knew the window (ticket, #eng-infra, standup).`
- `investigator_notebook.md:28`: `Audit logs: none (by design). SIEM: none.`

**Recommendation:** Require a second, independent approval path for any change
that simultaneously removes both primary and secondary audit coverage. Where
possible, route audit streams to a separate, immutable destination (write-once
object storage, isolated from migration scope) so that maintenance of the
primary pipeline does not blank the record.

---

## 3 — Treat the real/decoy path mapping as a classified document

**Gap found:** In February 2025 the board pack included a slide showing which
artifact paths were real versus decoy. That pack was distributed to the entire
board distribution list. In March, Yannick Favre wrote the same information
into a Confluence page with default `eng-all` permissions, where it received
16 views from 9 accounts. The "need to know" list of five people was
effectively rendered meaningless.

**Source:**
- `investigator_notebook.md:21`: `Board pack, Feb: Iris briefed the decoy programme, 4 slides, one of them the real/decoy mapping by path. **Distribution list: get it from the email, not from memory.**`
- `investigator_notebook.md:22`: `Confluence page "Storage Integrity Controls (WIP)", written by Yannick in March, permissioned to eng-all. Page analytics: 16 views, 9 distinct accounts.`
- `interviews/interview_01_iris_ammann.txt:19`: `[00:01:36] SPEAKER 2: The board asked me in February what the control actually was, so I showed them. Slide eleven. Which artifacts are real, by path. I said in the room that the slide should not exist after that day.`

**Recommendation:** Any document that reveals the real/decoy mapping or the
real staging path must be classified at the same level as the model weights.
Board briefings on sensitive security controls should use a live presentation
only, with no persistent slide deck. Confluence pages covering security
controls should be restricted to named individuals, not role groups.

---

## 4 — Make scratch arrays tamper-evident

**Gap found:** `scratch-02` was the only system that preserved any record of
the theft. It survived because it was not part of the migration. But the array
was writable — the thief deleted a snapshot from the target device to free
space. If the thief had deleted the journal on `scratch-02` itself, there would
be no forensic evidence at all.

**Source:**
- `investigator_notebook.md:31`: `The one thing that kept its own records: **scratch-02**, the fast non-redundant array used for bulk copies. Not part of the migration, never wired to the audit pipeline. Image sent to E. Bakalian (Winterthur) for analysis.`
- `forensic_summary_bakalian.pdf:1` (Annex A): copy completed 03:52 UTC, device detached 03:58 UTC

**Recommendation:** Wire scratch arrays to the audit pipeline with an
append-only, off-array journal (e.g., stream filesystem events to a separate
write-once log store). The journal itself should be on infrastructure the
operator cannot reach from the engineering floor. This ensures that even
ad-hoc arrays used for bulk work generate a tamper-evident record.

---

## 5 — Alert on anomalous checkpoint access patterns in near-real-time

**Gap found:** The investigation revealed a researcher had accessed checkpoints
31 times in four weeks against a company median of 2. The anomaly was known
only in retrospect. No alert fired at the time. Any anomalous pattern —
whether by a researcher writing a paper or by an insider preparing an
exfiltration — should be surfaced before, not after, the fact.

**Source:**
- `investigator_notebook.md:50`: `**Caduff** (Principal Research Eng): research line closed in the September replan, role ends August. 31 checkpoint accesses in 4 weeks, median 2.`

**Recommendation:** Instrument the checkpoint staging tree with access logging
(separate from the audit pipeline that went down for the migration). Define a
threshold — e.g., more than 5× the rolling 30-day median for that user — that
triggers a low-priority alert to the security lead. Access anomalies during an
audit-logging gap should automatically elevate to medium priority. This does
not prevent the access; it ensures it is reviewed.

---

## 6 — Require dual approval for audit-window changes

**Gap found:** The ticket that disabled audit logging (INFRA-2291) was signed
off by a single approver (Iris Ammann, the Head of Security). The 9-hour
window was communicated in a public channel, a standup, and a ticket visible
to approximately 40 people — including the eventual culprit. A single approver
had the authority to create the opportunity; no second check was required.

**Source:**
- `investigator_notebook.md:14`: `Audit collector stopped on purpose, Fri 10.10 21:00 → Sat 11.10 06:00, ticket INFRA-2291. SIEM cold tier pointed at the same backend, so no copy. ~40 people knew the window (ticket, #eng-infra, standup).`
- `investigator_notebook.md:48`: `**Ammann** (Head of Security): designed decoys and watermarks, signed off INFRA-2291.`

**Recommendation:** Any change that creates a logging gap should require
dual approval: the security lead plus a second, independent approver (e.g.,
the CTO or CISO). Additionally, access to the checkpoint staging tree should
be restricted for employees in a notice period or whose research lines have
been closed, pending a formal off-boarding review.
