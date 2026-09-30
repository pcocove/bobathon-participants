"""Declared search vocabulary.

Rule 2 of the challenge: anything typed into the code after reading the files must be
declared. Nothing in this file is case evidence. It is general-purpose vocabulary
(how people phrase a departure, what a card MCC code means, what words signal that a
source is unreliable) used to *find* evidence. Every conclusion still has to point at
a line in the bundle, and every quote is verified against the bundle as received.

If you extend this file, list the change in src/README.md under "Declared inputs".
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Hints that a source is inconsistent, unreliable or deliberately incomplete.
# The sweep scans every source for these first and resolves them before arguing.
# ---------------------------------------------------------------------------
HINT_PATTERNS: dict[str, list[str]] = {
    "clock": [
        r"not normali[sz]ed",
        r"not every clock",
        r"clock",
        r"systemuhr",
        r"time ?zone",
        r"terminal times",
        r"all times in this report are utc",
    ],
    "transcription": [
        r"not proofread",
        r"may be wrong",
        r"speaker labels",
        r"automatic transcription",
        r"unreliable",
    ],
    "narrative_mismatch": [
        r"differs from",
        r"does not match",
        r"inconsisten",
    ],
    "withheld": [
        r"\bwithhold",
        r"\bwithheld\b",
        r"do not disclose",
        r"strictly confidential",
        r"nobody .{0,40}hears? any of it",
    ],
    "recognition": [
        r"konfidenz",
        r"recognition confidence",
        r"degraded",
    ],
    "leak_channel": [
        r"clearly audible",
        r"hear everything",
        r"sound transmission",
        r"speech .{0,40}intelligible",
        r"lautsprecher",
        r"on speaker",
    ],
    "uncertain_identification": [
        r"weiss ich nicht sicher",
        r"not sure whose",
        r"\((?:[A-Z][a-z]+)\?\)",
    ],
}

# ---------------------------------------------------------------------------
# Operational concepts used to detect "knowledge only the operator could have".
# Keys are matched against the investigator's own list of withheld facts
# (e.g. a notebook line "WITHHOLD ... failure, snapshot, restart, the hours").
# The phrases are ordinary English paraphrases of those concepts.
# ---------------------------------------------------------------------------
CONCEPTS: dict[str, dict] = {
    "failure": {
        "aliases": ["failure", "fail", "failed", "crash", "died"],
        "patterns": [
            r"\bfail(?:ed|s|ure)?\b",
            r"\bdied\b",
            r"\bdie (?:halfway|partway)",
            r"\bcrash(?:ed|es)?\b",
            r"\bterminat(?:ed|es)\b",
            r"\bhalf ?way\b",
            r"\bpart ?way\b",
            r"\btarget (?:disk |device )?(?:is |was )?full\b",
            r"\bfill (?:the )?target\b",
        ],
    },
    "deletion": {
        "aliases": ["snapshot", "deletion", "delete", "deleted"],
        "patterns": [
            r"\bsnapshot",
            r"\bdelet(?:e|ed|ing) (?:something|an? old|the old)",
            r"\bmake room\b",
            r"\bbin something\b",
            r"\bclear(?:ing|ed)? (?:room|space)\b",
        ],
    },
    "restart": {
        "aliases": ["restart", "restarted", "rerun", "started again"],
        "patterns": [
            r"\brestart(?:ed|s)?\b",
            r"\bfrom the (?:top|beginning|start)\b",
            r"\bfrom scratch\b",
            r"\bover again\b",
            r"\bstart(?:ed|ing)? (?:it |the (?:whole )?job )?again\b",
        ],
    },
    "duration": {
        "aliases": ["the hours", "hours", "duration", "timing", "the times"],
        "patterns": [
            r"\ball night\b",
            r"\bsmall hours\b",
            r"\b(?:six|seven|eight|nine|several|\d+) hours\b",
            r"\bsat in (?:that|a|the) building\b",
            r"\bbabysit",
        ],
    },
}

# A statement "echoes" withheld facts when it hits at least this many concepts,
# at least one of which describes the operation itself (not just its length).
ECHO_MIN_CONCEPTS = 2
ECHO_CORE_CONCEPTS = {"failure", "restart", "deletion"}

# ---------------------------------------------------------------------------
# Presence / whereabouts phrasing.
# ---------------------------------------------------------------------------
SELF_LOCATION_AWAY = [
    r"\bfrom home\b",
    r"\bat home\b",
    r"\bfrom the hotel\b",
    r"\breachable but in ([a-zà-ÿ][a-zà-ÿ\- ]{2,30})",
    r"\bjoining remotely from ([a-zà-ÿ][a-zà-ÿ\- ]{2,30})",
    r"\bi will be in ([a-zà-ÿ][a-zà-ÿ\- ]{2,30})",
    r"\bno car\b",
]
SELF_LOCATION_ONSITE = [
    r"\bi am in the office\b",
    r"\bi'?m in the office\b",
    r"\bin the office\b",
    r"\bin the building\b",
    r"\b(?:office|building|floor) is (?:\w+ )?quiet\b",
]
NEGATED_KNOWLEDGE = [
    r"did(?: not|n'?t) know which",
    r"do(?: not|n'?t) (?:know|understand) (?:which|them)",
    r"couldn'?t tell (?:them|which)",
    r"no way .{0,40}to tell them apart",
]
VERIFIED_WORDS = [r"\bverified\b", r"\baccounted for\b", r"\bconfirms?\b", r"\breads clean\b"]
DEPARTURE_WORDS = [
    r"\bdrove\b", r"\bdrive\b", r"\bleft\b", r"\bleave\b", r"\bwent\b",
    r"\bflew\b", r"\btrain\b", r"\bhome by\b", r"\bgoing home\b", r"\bheading out\b",
]
LEAVING_MESSAGE = [r"\bgoing home\b", r"\bheading (?:out|home)\b", r"\bleaving (?:now|the office|for the day)\b", r"\boff home\b"]

WEEKDAYS = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4,
    "samstag": 5, "sonntag": 6,
}
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
PART_OF_DAY = {  # local hour ranges a narrative phrase implies
    "morning": (6, 12), "afternoon": (12, 18), "evening": (17, 23), "night": (20, 27),
    "abends": (17, 23), "morgens": (6, 12),
}

# ---------------------------------------------------------------------------
# Card data: ISO 18245 merchant category codes (general knowledge).
# ---------------------------------------------------------------------------
MCC = {
    "7011": "lodging",
    "5541": "fuel", "5542": "fuel", "5499": "convenience",
    "5812": "restaurant", "5813": "bar", "5814": "fast food",
    "4111": "transit", "4112": "rail", "4121": "taxi", "4131": "bus",
    "4511": "airline", "7512": "car rental", "7523": "parking",
    "5411": "grocery", "5732": "electronics",
}
TRANSPORT_MCC = {"4111", "4112", "4121", "4131", "4511", "7512"}

# ---------------------------------------------------------------------------
# Vehicle descriptions (German exports, English chat).
# ---------------------------------------------------------------------------
COLOURS = {
    "grün": "green", "gruen": "green", "rot": "red", "blau": "blue",
    "schwarz": "black", "weiss": "white", "weiß": "white", "grau": "grey",
    "silber": "silver", "gelb": "yellow",
}
COLOUR_WORDS = set(COLOURS) | set(COLOURS.values()) | {"gray"}
BODY_SYNONYMS = {
    "kombi": ["kombi", "estate", "wagon"],
    "dachbox": ["dachbox", "roof box", "roofbox"],
}

# ---------------------------------------------------------------------------
# Garage exports.
# ---------------------------------------------------------------------------
GARAGE_ENTRY = {"einfahrt", "entry", "in"}
GARAGE_EXIT = {"ausfahrt", "exit", "out"}
DEGRADED_CONFIDENCE = 70  # plate reads below this are treated as uncertain

# Clock checks: two records of the same moment must agree within this many minutes.
CLOCK_TOLERANCE_MIN = 20


def compile_all(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def concept_hits(text: str, concepts: list[str] | None = None) -> dict[str, str]:
    """Return {concept: matched phrase} for every concept whose phrasing appears."""
    out: dict[str, str] = {}
    for name, spec in CONCEPTS.items():
        if concepts is not None and name not in concepts:
            continue
        for pat in spec["patterns"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                out[name] = m.group(0)
                break
    return out


def concept_for_label(label: str) -> str | None:
    """Map a free-text label from the investigator ("the hours") to a concept key."""
    lab = label.strip().lower().strip(".*").strip()
    for name, spec in CONCEPTS.items():
        for alias in spec["aliases"]:
            if lab == alias or lab.startswith(alias) or alias in lab.split():
                return name
    return None
