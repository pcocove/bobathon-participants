"""Declared security vocabulary for the Security Guard.

Like lexicon.py, nothing here is case evidence: it is general security knowledge — how
weaknesses tend to be written down in tickets, chat and notes; which process failures
produce them; what the standard remediations are. Every risk the Guard reports must still
point at lines in the data, and every quote is verified.
"""

from __future__ import annotations

SEVERITY = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# ---------------------------------------------------------------------------
# Risk detectors: what a weakness looks like in the data.
#   patterns   regexes on a single line (case-insensitive)
#   in         optional source-path prefixes to restrict noisy detectors
#   repeat     a chat line only counts as a risk if it recurs this often (chronic problem)
# ---------------------------------------------------------------------------
DETECTORS: dict[str, dict] = {
    "stale-access": {
        "title": "Access that was never revoked or re-scoped",
        "severity": "critical",
        "patterns": [r"never (?:been )?(?:revoked|re-?scoped)", r"broader than (?:intended|needed|it needed)",
                     r"were never revoked", r"roles revoked:\*{0,2}\s*[—–-]"],
        "why": "Standing access outlives its purpose; anyone who holds or can obtain the credential can still use it.",
    },
    "privileged-access": {
        "title": "Privileged access that nobody reviews",
        "severity": "high",
        "patterns": [r"admin(?:istrator)? accounts? on most systems", r"admin accounts? (?:that )?nobody reviewed",
                     r"passwords?[^.]{0,40}(?:notebook|on paper|post-?it|sticky)", r"(?:live|kept|written) in (?:this|a|the) notebook"],
        "why": "Unreviewed privileged accounts and written-down passwords are the easiest path to every system.",
    },
    "overexposed-information": {
        "title": "Sensitive information exposed beyond need-to-know",
        "severity": "high",
        "patterns": [r"permission(?:ed)? (?:it )?to (?:eng-all|all-?staff|everyone|the whole company)",
                     r"because that'?s the default", r"can'?t recall (?:those|them|it)\b", r"should not (?:circulate|exist)",
                     r"from any copy you keep"],
        "why": "Once sensitive material is in a broadly shared space or an e-mailed file, it cannot be taken back.",
    },
    "physical-access": {
        "title": "Physical access control that does not control access",
        "severity": "high",
        "patterns": [r"\bpropped\b", r"not badge[- ]controlled", r"come in behind (?:somebody|someone)", r"\btailgat",
                     r"badge record[^.]{0,30}(?:worth nothing|useless)", r"cameras?[^\n]{0,80}(?:refused|never installed)"],
        "repeat": 3,
        "why": "If doors stand open and badges are not needed, nobody knows who was in the building.",
    },
    "logging-gap": {
        "title": "Audit and monitoring gaps",
        "severity": "critical",
        "patterns": [r"hard stop the collector", r"no (?:audit (?:logs?|trail)|redundant copy)", r"nine hours with no audit trail",
                     r"not (?:wired|connected) (?:in)?to the audit", r"never wired to the audit",
                     r"(?:SIEM|cold tier)[^.]{0,80}(?:same backend|that backend)", r"no audit logs"],
        "why": "Planned or structural blind spots in logging are exactly when misuse goes unrecorded.",
    },
    "alerting-gap": {
        "title": "Nobody is alerted when something breaks",
        "severity": "medium",
        "patterns": [r"nobody paged", r"on-?call (?:gap|rotation has gaps)", r"gaps on public holidays"],
        "why": "Without on-call coverage, incidents during weekends and holidays run unnoticed for hours.",
    },
    "information-leak": {
        "title": "Confidential conversations can be overheard",
        "severity": "high",
        "patterns": [r"clearly audible", r"hear everything", r"sound transmission", r"speech[^.]{0,40}intelligible",
                     r"stop booking \S+ for anything confidential"],
        "why": "A room known to leak sound is being used for confidential work.",
    },
    "record-integrity": {
        "title": "Records whose clocks or content are known to be wrong",
        "severity": "medium",
        "patterns": [r"clock[^.]{0,60}(?:wrong|stayed on winter time|off by)", r"times? one hour off", r"hour off against"],
        "why": "Evidence from systems with wrong clocks cannot be relied on in an investigation.",
    },
    "removable-media": {
        "title": "Bulk copies to removable storage are possible",
        "severity": "high",
        "patterns": [r"externally attached (?:block )?device", r"USB identifiers", r"portable array class",
                     r"(?:borrowing|borrowed) [^.]{0,30}portable arrays?"],
        "why": "If a console accepts a portable drive, terabytes can leave the building in a bag.",
    },
    "credential-hygiene": {
        "title": "Credential and certificate hygiene not done",
        "severity": "medium",
        "patterns": [r"rotate service account credentials", r"cert(?:ificate)? expiry monitoring", r"shared (?:password|credential)s?"],
        "why": "Unrotated service credentials and unmonitored certificates fail silently until they are abused or expire.",
    },
    "insider-governance": {
        "title": "Outside interests and approaches that are not declared",
        "severity": "medium",
        "patterns": [r"\bmoonlighting\b", r"against (?:my|his|her|the) contract", r"\bsecond job\b", r"\b(?:continuing|future|new) role after\b",
                     r"\bjob offer\b"],
        "why": "Undeclared outside work or job offers from counterparties are classic insider-risk precursors.",
    },
}

# Chat channels are noisy: only these detectors look at chat, and only for recurring lines.
CHAT_DETECTORS = {"physical-access", "alerting-gap", "information-leak"}

# Words that mark a ticket as security work (by content, not by project key).
SECURITY_TICKET_TERMS = [
    r"\brevok", r"\baccess\b", r"\bpermission", r"\bcredential", r"\brotate\b", r"\bcert(?:ificate)?\b", r"\baudit\b",
    r"\bsecret", r"\btoken\b", r"\bpassword", r"\bservice accounts?\b", r"\bscope", r"\bexposure\b", r"\bmfa\b", r"\bbadge\b",
]
TICKET_DONE = {"done", "closed", "resolved", "fixed"}
# Routine requests that mention a security word but are not a weakness.
ROUTINE_TICKETS = [r"^password reset$", r"^request: ", r"^new (?:laptop|starter)"]
TICKET_DROPPED = {"won't fix", "wont fix", "rejected", "duplicate"}
# "…, regression", "… (again)", "… follow-up", "… on <environment>": the same work item filed again
RECURRENCE_SUFFIX = r"(?:,? regression| \(again\)| follow-up| on (?:the )?[\w-]+(?: cluster)?)+$"

# Tables that track grants: a column with one of these names and an empty cell means "still active".
GRANT_COLUMNS = ["revoked", "expires", "expiry", "end date", "valid until"]
EMPTY_CELL = {"", "—", "–", "-", "none", "n/a", "never"}

# Process signals: evidence of HOW a weakness came about.
PROCESS_SIGNALS: dict[str, list[str]] = {
    "pressure": [r"under time pressure", r"in a hurry", r"nobody had time", r"signed off,? reluctantly"],
    "deferral": [r"deferred(?: pending budget)?", r"after the migration,? i promise", r"still deferred", r"\bwon'?t fix\b",
                 r"(?:asked twice|said no twice|refused by the board)"],
    "repeat-raise": [r"raised (?:it )?(?:in standup )?again", r"raised in standup", r"i have said this", r"i will keep saying it",
                     r"still open\.?$", r"raised again"],
    "default": [r"because that'?s the default", r"default permissions?"],
    "ownership": [r"owner of record", r"actual revocation is an? \w+ task", r"not our system"],
}

# ---------------------------------------------------------------------------
# Process misdesign (root causes): which process failure lets a class of risk exist.
# ---------------------------------------------------------------------------
ROOT_CAUSES: dict[str, dict] = {
    "access-lifecycle": {
        "title": "Access is granted without an expiry date or an accountable owner",
        "from": ["stale-access", "credential-hygiene", "grant-table"], "signals": ["ownership", "pressure"],
        "explain": "Grants are created for a purpose (a project, a deal, a migration) but nothing ends them when the "
                   "purpose ends. The business owner of record is not the person who can revoke, and the person who "
                   "can revoke has no deadline.",
    },
    "no-escalation": {
        "title": "Known security issues have no deadline and no escalation path",
        "from": ["security-ticket"], "signals": ["repeat-raise", "deferral"],
        "explain": "Issues are raised, acknowledged and re-raised in standups for months. There is no SLA by severity "
                   "and no route to someone who can force the fix.",
    },
    "pressure-overrides": {
        "title": "Security controls are relaxed under delivery pressure without compensating controls",
        "from": ["logging-gap", "stale-access"], "signals": ["pressure"],
        "explain": "Sign-offs happen 'reluctantly' and scopes are broadened 'in a hurry'. Nothing replaces the control "
                   "that was relaxed, and nothing brings it back.",
    },
    "budget-deferral": {
        "title": "Physical and privacy controls are deferred for budget with no risk owner",
        "from": ["physical-access", "information-leak"], "signals": ["deferral"],
        "explain": "Fixes are costed, deferred and forgotten. The residual risk is never accepted in writing by someone "
                   "accountable, so the control stays broken by default.",
    },
    "uncontrolled-distribution": {
        "title": "Sensitive material is shared in channels that cannot be recalled or restricted",
        "from": ["overexposed-information"], "signals": ["default"],
        "explain": "Default-open spaces and e-mailed files are used for material that must stay need-to-know. Once "
                   "shared, copies cannot be withdrawn.",
    },
    "monitoring-spof": {
        "title": "Monitoring shares failure modes with what it monitors",
        "from": ["logging-gap", "alerting-gap", "record-integrity"], "signals": [],
        "explain": "The backup of the audit trail lives on the same backend, some systems are outside the audit "
                   "pipeline, on-call has gaps, and clocks drift unnoticed — one outage removes all visibility.",
    },
    "privilege-review": {
        "title": "Privileged access is never reviewed",
        "from": ["privileged-access"], "signals": [],
        "explain": "Admin rights accumulate with seniority and are never re-certified; credentials are kept outside any "
                   "managed store.",
    },
    "data-egress": {
        "title": "Nothing stops or detects bulk copies to removable media",
        "from": ["removable-media"], "signals": [],
        "explain": "Consoles accept external storage and there is no data-loss control or alert on large transfers.",
    },
    "insider-governance": {
        "title": "No declaration process for outside work and counterparty approaches",
        "from": ["insider-governance"], "signals": [],
        "explain": "Outside interests and job offers from counterparties are only discovered in an investigation, not "
                   "declared up front.",
    },
    "fixes-dont-stick": {
        "title": "Fixes don't stick — the same issue returns as 'again' and 'regression'",
        "from": ["security-ticket"], "signals": [], "needs_recurrence": 3,
        "explain": "Tickets are closed on a symptom; the same problem is re-filed. There is no root-cause review before "
                   "closing security work.",
    },
}

# ---------------------------------------------------------------------------
# Remediation playbooks (standard practice), per root cause.
# ---------------------------------------------------------------------------
REMEDIATIONS: dict[str, dict] = {
    "access-lifecycle": {
        "owner": "Security + Infrastructure",
        "now": "Revoke or re-scope every grant listed without an end date; rotate any credential those identities held; "
               "check access logs for use of those identities since the purpose ended.",
        "control": "Time-bound grants that expire automatically; alert on any use of a dormant or external service account.",
        "process": "Every grant to an external party needs a security co-signer and an end date tied to the engagement; "
                   "closing the engagement opens the revocation ticket automatically.",
        "verify": "Access review shows zero grants without an expiry; the revocation tickets are closed with evidence.",
    },
    "no-escalation": {
        "owner": "CISO / Head of Security",
        "now": "Put every open security ticket older than 30 days on one list with an owner and a date; escalate the "
               "oldest high-severity items to the executive team this week.",
        "control": "SLA by severity (e.g. critical 7 days, high 30 days) with automatic escalation when breached.",
        "process": "Monthly security review where open items are either fixed, or their risk is accepted in writing by a "
                   "named executive.",
        "verify": "No security ticket breaches its SLA without a written risk acceptance.",
    },
    "pressure-overrides": {
        "owner": "Change Advisory Board + Security",
        "now": "For every relaxed control, confirm it was restored and list what happened while it was off.",
        "control": "A change that disables a security control must name its compensating control (e.g. a second log "
                   "destination, on-site presence, disabled bulk-copy paths) and auto-restore time.",
        "process": "Security sign-off cannot be 'reluctant': either the compensating control exists or the change waits.",
        "verify": "Change records show a compensating control for every security-relevant change.",
    },
    "budget-deferral": {
        "owner": "Facilities + Security + Board",
        "now": "Stop using affected spaces for confidential work; close or alarm doors that are routinely propped.",
        "control": "Door-open alarms, badge-controlled secondary doors, sound masking or rebuilt partitions.",
        "process": "Deferred security fixes become written risk acceptances with an owner and a review date.",
        "verify": "Door alarm logs show no propped-door events; confidential rooms pass a speech-privacy check.",
    },
    "uncontrolled-distribution": {
        "owner": "Security + Legal",
        "now": "Restrict or remove the exposed material; ask recipients to confirm deletion; treat the exposed secret as "
               "compromised and change it where possible.",
        "control": "Need-to-know spaces by default for sensitive material; view-only, watermarked, expiring shares "
                   "instead of attachments.",
        "process": "Classification rules for board and security material; sensitive mappings never go into decks.",
        "verify": "Permission audit of documentation spaces shows no sensitive page open to all staff.",
    },
    "monitoring-spof": {
        "owner": "Infrastructure + Security Operations",
        "now": "Bring every storage system into the audit pipeline; ship audit logs to a second, independent destination.",
        "control": "Independent log store; clock synchronisation monitoring on every logging source; on-call coverage "
                   "with holiday rota and paging for security alerts.",
        "process": "Planned logging outages require a second destination or physical controls for their duration.",
        "verify": "A test outage of the primary log backend loses no audit events; clock-drift alerts fire in testing.",
    },
    "privilege-review": {
        "owner": "Security + IT",
        "now": "Inventory all admin accounts; remove those not needed; move remaining credentials into a managed vault "
               "and rotate them.",
        "control": "Quarterly privileged-access re-certification; MFA on every admin account; just-in-time elevation.",
        "process": "Admin rights follow role, not seniority; leavers and role changes trigger review.",
        "verify": "Re-certification report signed by system owners; no credentials outside the vault.",
    },
    "data-egress": {
        "owner": "IT + Security",
        "now": "Block USB mass storage on consoles that can reach model artifacts; inventory portable arrays.",
        "control": "Data-loss prevention and alerting on bulk reads from protected paths; allow-listed devices only.",
        "process": "Bulk copies of protected artifacts need a ticket and a second person.",
        "verify": "A test copy to an unapproved device is blocked and alerted.",
    },
    "insider-governance": {
        "owner": "HR + Legal",
        "now": "Ask staff with access to crown-jewel assets to declare outside work and counterparty approaches.",
        "control": "Annual conflict-of-interest declaration; counterparty contact during a deal logged by corp dev.",
        "process": "Approaches from counterparties are reported to legal within 24 hours.",
        "verify": "Declarations on file for everyone with privileged or deal access.",
    },
    "fixes-dont-stick": {
        "owner": "Engineering leads",
        "now": "Group recurring security tickets by root cause and assign one owner per group.",
        "control": "Regression tests or policy checks for each closed security issue.",
        "process": "A security ticket cannot be closed as 'again/regression' without a root-cause note.",
        "verify": "Re-opened security issues trend to zero over two quarters.",
    },
}
