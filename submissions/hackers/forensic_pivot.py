"""
forensic_pivot.py — Sub-Task 3 of the Meridian investigation.

Searches every interview transcript, Slack message, and email for terms that
match the forensic detail that was WITHHELD from all interviewees:
  1. Copy job failed partway (~40%)
  2. Snapshot deleted to free space (~9 TB)
  3. Job restarted from the beginning
  4. Completion time (05:52 CEST / 03:52 UTC)

Anyone who describes this without a legitimate prior source is placed at the
console. This script:
  - Greps all interview .txt files
  - Greps all Slack JSON files (resolving user IDs)
  - Greps the .mbox email export
  - Attributes each hit to a suspect where possible
  - Checks for an innocent explanation
  - Updates suspect_profiles.json with forensic_pivot results
  - Prints a plain-English summary

Innocent explanations already established in Sub-Task 2:
  - Chiara Bernasconi: filed Jira capacity ticket on 14 Oct from scratch-02 graph
  - Noemi Rochat: office 2F-4 shares paper wall with investigator's room 2F-3;
      investigator used speaker phone Thu 20 Nov evening after Thu interviews;
      Noemi interviewed Fri 12:03
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from index_evidence import build_index, LINE_INDEX, BUNDLE

# ---------------------------------------------------------------------------
# Search terms for the withheld forensic detail
# ---------------------------------------------------------------------------

# Each tuple: (label, regex pattern, case-insensitive)
PIVOT_PATTERNS: list[tuple[str, str, bool]] = [
    # Failure / partial copy
    ("copy_failed",     r"\b(fail|error|terminat|abort|died|crash)(ed|s)?\b", True),
    ("halfway",         r"\b(halfway|half.?way|40\s*%|partway|part.?way|halfw)\b", True),
    ("target_full",     r"\b(full|no\s+space|out\s+of\s+space|target\s+full)\b", True),
    # Snapshot deletion
    ("snapshot_delete", r"\b(snapshot|snap\s*shot)\b", True),
    ("nine_tb",         r"\b9(\s*(tb|terabyte|tera))?\s*(free|freed|jump|drop|clear)\b", True),
    ("free_space",      r"\b(free\s+space|freed?\s+up|clear(ed)?\s+space|bin\s+something|make\s+room)\b", True),
    # Restart
    ("restart",         r"\b(restart(ed)?|start(ed)?\s+(again|over|from\s+(the\s+)?beginning|from\s+scratch)|rerun)\b", True),
    # Completion time (any mention of 03:52 UTC or 05:52 CEST)
    ("completion_time", r"\b(03:52|05:52)\b", True),
]

# Slack user ID → real name (populated at runtime)
USER_MAP: dict[str, str] = {}

# Suspect email addresses / name handles for attribution
SUSPECT_HANDLES = {
    "Iris Ammann":       ["iris.ammann", "U0702C"],
    "Chiara Bernasconi": ["chiara.bernasconi", "U0705F"],
    "Andrin Caduff":     ["andrin.caduff", "U0703D"],
    "Yannick Favre":     ["yannick.favre", "U0704E"],
    "Lukas Hofer":       ["lukas.hofer", "U0701B"],
    "Noemi Rochat":      ["noemi.rochat", "U0706G"],
    "Kurt Steiner":      ["kurt.steiner", "U0707H"],
    "Renata Vogel":      ["renata.vogel", "U0700A"],
}

# Build reverse map handle → name
HANDLE_TO_NAME: dict[str, str] = {}
for name, handles in SUSPECT_HANDLES.items():
    for h in handles:
        HANDLE_TO_NAME[h.lower()] = name


# Innocent explanations (from Sub-Task 2)
INNOCENT_EXPLANATIONS: dict[str, str] = {
    "Chiara Bernasconi": (
        "She filed Jira ticket DATA-1802 or similar on 14 Oct (4 days before investigator engaged) "
        "after observing the free-space anomaly on the scratch-02 capacity graph herself. "
        "The detail was visible to her and ~6 others via ticket notification before any interview."
    ),
    "Noemi Rochat": (
        "Her office 2F-4 shares a non-insulated partition wall with the investigator's room 2F-3 "
        "(FAC-330: 'speech at normal conversational volume is intelligible through it'). "
        "The investigator called forensic examiner Emory on speaker in 2F-3 on Thu 20 Nov evening, "
        "reviewing all forensic findings. Noemi was interviewed the next morning (Fri 12:03)."
    ),
}

# ---------------------------------------------------------------------------
# Hit record
# ---------------------------------------------------------------------------

def _hit(file: str, lineno: int, raw: str, pattern_label: str,
         suspect: str | None, context: str = "") -> dict:
    return {
        "file": file,
        "line": lineno,
        "quote": raw.strip(),
        "pattern": pattern_label,
        "suspect": suspect,
        "context": context,
    }


def _identify_suspect_from_text(text: str, file: str) -> str | None:
    """Try to attribute a line to a suspect based on speaker context in the file."""
    # Interview files: speaker is SPEAKER 2 for interviewee
    # File name carries the suspect name
    for name, handles in SUSPECT_HANDLES.items():
        for h in handles:
            if h.replace(".", "_").lower() in file.lower() or h.replace(".", " ").lower() in file.lower():
                # speaker context: only flag SPEAKER 2 lines (interviewee)
                return name
    return None


def _resolve_slack_user(uid: str) -> str | None:
    return USER_MAP.get(uid)


# ---------------------------------------------------------------------------
# Grep functions
# ---------------------------------------------------------------------------

def grep_interviews() -> list[dict]:
    hits = []
    interview_dir = BUNDLE / "interviews"
    patterns_compiled = [
        (label, re.compile(pat, re.IGNORECASE if ci else 0))
        for label, pat, ci in PIVOT_PATTERNS
    ]
    for fpath in sorted(interview_dir.glob("*.txt")):
        rel = fpath.relative_to(BUNDLE).as_posix()
        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        # Find which suspect this interview belongs to
        interview_suspect: str | None = None
        for name, handles in SUSPECT_HANDLES.items():
            if any(h.replace(".", "_") in fpath.stem or
                   h.replace(".", " ").lower().split()[-1] in fpath.stem.lower()
                   for h in handles):
                interview_suspect = name
                break
        # Track whether current line is from the interviewee (SPEAKER 2)
        for lineno, raw in enumerate(lines, start=1):
            is_interviewee = raw.strip().startswith("[") and "SPEAKER 2" in raw
            is_na = raw.strip().startswith("[") and " NA:" in raw
            speaker = "interviewee" if is_interviewee else ("interviewer" if is_na else "meta")
            for label, compiled in patterns_compiled:
                if compiled.search(raw):
                    hits.append(_hit(
                        rel, lineno, raw, label,
                        suspect=interview_suspect if is_interviewee else None,
                        context=f"speaker={speaker}",
                    ))
    return hits


def grep_slack() -> list[dict]:
    hits = []
    slack_dir = BUNDLE / "slack_export"
    patterns_compiled = [
        (label, re.compile(pat, re.IGNORECASE if ci else 0))
        for label, pat, ci in PIVOT_PATTERNS
    ]
    for channel_dir in sorted(slack_dir.iterdir()):
        if not channel_dir.is_dir():
            continue
        for day_file in sorted(channel_dir.glob("*.json")):
            rel = day_file.relative_to(BUNDLE).as_posix()
            try:
                messages = json.loads(day_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            for idx, msg in enumerate(messages, start=1):
                if not isinstance(msg, dict):
                    continue
                text = msg.get("text", "")
                uid  = msg.get("user", "")
                sender_name = USER_MAP.get(uid, uid)
                suspect = HANDLE_TO_NAME.get(uid.lower()) or HANDLE_TO_NAME.get(sender_name.lower().replace(" ", "."))
                for label, compiled in patterns_compiled:
                    if compiled.search(text):
                        hits.append(_hit(
                            rel, idx, f"{sender_name}: {text}", label,
                            suspect=suspect,
                            context=f"channel={channel_dir.name}",
                        ))
    return hits


def grep_email() -> list[dict]:
    hits = []
    path = BUNDLE / "email_export.mbox"
    rel  = path.relative_to(BUNDLE).as_posix()
    patterns_compiled = [
        (label, re.compile(pat, re.IGNORECASE if ci else 0))
        for label, pat, ci in PIVOT_PATTERNS
    ]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    # Track current sender
    current_sender: str | None = None
    current_suspect: str | None = None
    for lineno, raw in enumerate(lines, start=1):
        if raw.startswith("From "):
            parts = raw.split()
            current_sender = parts[1] if len(parts) > 1 else None
            current_suspect = None
            if current_sender:
                for name, handles in SUSPECT_HANDLES.items():
                    if any(h.lower() in current_sender.lower() for h in handles):
                        current_suspect = name
                        break
        elif raw.startswith("From:"):
            addr = raw[5:].strip()
            current_suspect = None
            for name, handles in SUSPECT_HANDLES.items():
                if any(h.lower() in addr.lower() for h in handles):
                    current_suspect = name
                    break
        for label, compiled in patterns_compiled:
            if compiled.search(raw):
                hits.append(_hit(rel, lineno, raw, label,
                                 suspect=current_suspect,
                                 context=f"sender={current_sender}"))
    return hits


# ---------------------------------------------------------------------------
# Deduplicate and annotate hits
# ---------------------------------------------------------------------------

def deduplicate(hits: list[dict]) -> list[dict]:
    """Remove duplicate file:line:pattern combinations."""
    seen = set()
    out = []
    for h in hits:
        key = (h["file"], h["line"], h["pattern"])
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


def annotate_with_innocent(hits: list[dict]) -> list[dict]:
    """Add innocent_explanation field where applicable."""
    for h in hits:
        s = h.get("suspect")
        if s and s in INNOCENT_EXPLANATIONS:
            h["innocent_explanation"] = INNOCENT_EXPLANATIONS[s]
        else:
            h["innocent_explanation"] = None
    return hits


# ---------------------------------------------------------------------------
# Aggregate per-suspect
# ---------------------------------------------------------------------------

def aggregate_per_suspect(hits: list[dict]) -> dict[str, dict]:
    suspects = [
        "Iris Ammann", "Chiara Bernasconi", "Andrin Caduff", "Yannick Favre",
        "Lukas Hofer", "Noemi Rochat", "Kurt Steiner", "Renata Vogel",
    ]
    result: dict[str, dict] = {}
    for name in suspects:
        my_hits = [h for h in hits if h.get("suspect") == name]
        # Group hits by the pivotal patterns that indicate the thief
        # (restart + snapshot delete together are the key combo)
        key_patterns = {"restart", "snapshot_delete", "halfway", "free_space"}
        key_hits = [h for h in my_hits if h["pattern"] in key_patterns]
        describes = bool(key_hits)
        result[name] = {
            "describes_withheld_detail": describes,
            "key_hits": key_hits,
            "all_hits": my_hits,
            "innocent_explanation": INNOCENT_EXPLANATIONS.get(name),
        }
    return result


# ---------------------------------------------------------------------------
# Update suspect_profiles.json
# ---------------------------------------------------------------------------

def update_profiles(per_suspect: dict[str, dict]) -> None:
    profiles_path = Path("suspect_profiles.json")
    if not profiles_path.exists():
        print("WARNING: suspect_profiles.json not found; run build_profiles.py first")
        return
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    for profile in profiles:
        name = profile["name"]
        if name not in per_suspect:
            continue
        data = per_suspect[name]
        # Build evidence list from key_hits
        ev_list = []
        for h in data["key_hits"]:
            ev_list.append({
                "claim": f"Describes withheld forensic detail (pattern: {h['pattern']})",
                "source": f"{h['file']}:{h['line']}",
                "quote": h["quote"][:300],
            })
        profile["forensic_pivot"] = {
            "describes_withheld_detail": data["describes_withheld_detail"],
            "innocent_explanation": data["innocent_explanation"],
            "evidence": ev_list,
        }
    profiles_path.write_text(json.dumps(profiles, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print(f"Updated {profiles_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_pivot() -> dict[str, dict]:
    print("Building index …")
    build_index()
    # Populate user map from index run
    users_path = BUNDLE / "slack_export" / "users.json"
    for u in json.loads(users_path.read_text(encoding="utf-8")):
        USER_MAP[u["id"]] = u["real_name"]

    print("Grepping interviews …")
    iv_hits = grep_interviews()
    print(f"  {len(iv_hits)} raw hits")

    print("Grepping Slack …")
    sl_hits = grep_slack()
    print(f"  {len(sl_hits)} raw hits")

    print("Grepping email …")
    em_hits = grep_email()
    print(f"  {len(em_hits)} raw hits")

    all_hits = deduplicate(iv_hits + sl_hits + em_hits)
    all_hits = annotate_with_innocent(all_hits)
    print(f"\nTotal unique hits: {len(all_hits)}")

    per_suspect = aggregate_per_suspect(all_hits)
    update_profiles(per_suspect)

    return per_suspect


if __name__ == "__main__":
    per_suspect = run_pivot()

    print("\n" + "="*65)
    print("FORENSIC PIVOT RESULTS")
    print("="*65)

    for name, data in per_suspect.items():
        flag = "*** POSITIVE ***" if data["describes_withheld_detail"] else "negative"
        print(f"\n  {name}")
        print(f"    describes_withheld_detail : {flag}")
        if data["key_hits"]:
            for h in data["key_hits"]:
                src  = f"{h['file']}:{h['line']}"
                quote = h['quote'][:120].replace('\n', ' ')
                print(f"    [{h['pattern']}] {src}")
                print(f"      \"{quote}\"")
        if data["innocent_explanation"]:
            print(f"    INNOCENT EXPLANATION: {data['innocent_explanation'][:120]}…")

    print("\n" + "="*65)
    print("PIVOT SUMMARY TABLE")
    print("="*65)
    print(f"  {'Suspect':<25} {'Pivot':<8} {'Innocent?'}")
    print(f"  {'-'*60}")
    for name, data in per_suspect.items():
        flag   = "YES" if data["describes_withheld_detail"] else "no"
        innocn = "YES" if data["innocent_explanation"] else "—"
        print(f"  {name:<25} {flag:<8} {innocn}")
