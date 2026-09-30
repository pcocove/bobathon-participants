"""
index_evidence.py — Sub-Task 1 of the Meridian investigation.

Loads every evidence file from meridian_case_bundle/case_bundle/,
normalises timestamps to UTC, resolves Slack user IDs, and builds:

  TIMELINE  : list of dicts {dt_utc, file, line, quote, persons}
              sorted by dt_utc (None-timestamped entries go last)
  PERSON_INDEX : dict  canonical_name → [evidence entry, ...]
  LINE_INDEX   : dict  "file:line" → raw line text  (for quote verification)

Run standalone for a sanity-check summary:
  python index_evidence.py
"""

from __future__ import annotations

import csv
import json
import mailbox
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BUNDLE = Path("meridian_case_bundle/case_bundle")

SUSPECT_NAMES = [
    "Iris Ammann",
    "Chiara Bernasconi",
    "Andrin Caduff",
    "Yannick Favre",
    "Lukas Hofer",
    "Noemi Rochat",
    "Kurt Steiner",
    "Renata Vogel",
]

# Theft window (UTC)  Fri 10 Oct 21:00 → Sat 11 Oct 06:00
WINDOW_START = datetime(2025, 10, 10, 21, 0, 0, tzinfo=timezone.utc)
WINDOW_END   = datetime(2025, 10, 11,  6, 0, 0, tzinfo=timezone.utc)

# Europe/Zurich offset (CEST = UTC+2 in October 2025)
ZURICH_OFFSET = timedelta(hours=2)

# ---------------------------------------------------------------------------
# Global stores
# ---------------------------------------------------------------------------

TIMELINE: list[dict] = []
PERSON_INDEX: dict[str, list[dict]] = {n: [] for n in SUSPECT_NAMES}
LINE_INDEX: dict[str, str] = {}   # "relpath:lineno" -> raw text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel(path: Path) -> str:
    """Return path relative to BUNDLE as a forward-slash string."""
    try:
        return path.relative_to(BUNDLE).as_posix()
    except ValueError:
        return str(path)


def _entry(file: Path, line: int, quote: str,
           dt_utc: Optional[datetime] = None,
           persons: Optional[list[str]] = None) -> dict:
    rel = _rel(file)
    key = f"{rel}:{line}"
    LINE_INDEX[key] = quote
    e = {
        "dt_utc": dt_utc,
        "file": rel,
        "line": line,
        "quote": quote,
        "persons": persons or [],
    }
    return e


def _register(entry: dict) -> None:
    TIMELINE.append(entry)
    for p in entry["persons"]:
        if p in PERSON_INDEX:
            PERSON_INDEX[p].append(entry)


def _persons_in(text: str, user_map: dict[str, str] | None = None) -> list[str]:
    """Return suspect names mentioned (by name or resolved Slack ID) in text."""
    found = []
    # Resolve Slack user IDs  <@Uxxxxxx>
    if user_map:
        for uid, name in user_map.items():
            if f"<@{uid}>" in text or uid in text:
                if name in SUSPECT_NAMES and name not in found:
                    found.append(name)
    for name in SUSPECT_NAMES:
        # Match last name OR full name (case-insensitive)
        parts = name.split()
        if any(p.lower() in text.lower() for p in parts):
            if name not in found:
                found.append(name)
    return found


def _zurich_to_utc(dt_str: str) -> Optional[datetime]:
    """Parse a naive Zurich datetime string (various formats) and return UTC."""
    formats = [
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            naive = datetime.strptime(dt_str.strip(), fmt)
            return (naive - ZURICH_OFFSET).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _slack_ts_to_utc(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_slack(user_map: dict[str, str]) -> None:
    """Load all Slack channel exports."""
    slack_dir = BUNDLE / "slack_export"
    for channel_dir in sorted(slack_dir.iterdir()):
        if not channel_dir.is_dir():
            continue
        for day_file in sorted(channel_dir.glob("*.json")):
            rel = _rel(day_file)
            try:
                messages = json.loads(day_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            for lineno_0, msg in enumerate(messages, start=1):
                if not isinstance(msg, dict):
                    continue
                text = msg.get("text", "")
                uid  = msg.get("user", "")
                ts   = msg.get("ts", "")
                dt   = _slack_ts_to_utc(ts)
                # Resolve sender
                sender_name = user_map.get(uid, uid)
                persons = _persons_in(text, user_map)
                if sender_name in SUSPECT_NAMES and sender_name not in persons:
                    persons.append(sender_name)
                # Build a readable quote: "sender: text"
                quote = f"{sender_name}: {text}"
                e = _entry(day_file, lineno_0, quote, dt, persons)
                # Store raw text in line index too (for exact-quote matching)
                LINE_INDEX[f"{rel}:{lineno_0}"] = text
                _register(e)


def load_text_file(path: Path) -> None:
    """Load a plain-text or markdown file line by line."""
    rel = _rel(path)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return
    for lineno, raw in enumerate(lines, start=1):
        LINE_INDEX[f"{rel}:{lineno}"] = raw
        persons = _persons_in(raw)
        if persons:
            e = _entry(path, lineno, raw, None, persons)
            _register(e)
        else:
            # Still register in TIMELINE (no persons) so LINE_INDEX is complete
            TIMELINE.append(_entry(path, lineno, raw, None, []))


def load_interviews() -> None:
    interview_dir = BUNDLE / "interviews"
    for f in sorted(interview_dir.glob("*.txt")):
        load_text_file(f)


def load_markdown_files() -> None:
    for fname in [
        "investigator_notebook.md",
        "helpdesk_and_facilities.md",
        "expense_reports.md",
        "meeting_notes.md",
        "kestrel_diligence_log.md",
    ]:
        load_text_file(BUNDLE / fname)


def load_jira() -> None:
    path = BUNDLE / "jira_export.json"
    rel = _rel(path)
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return
    # Index raw file line-by-line for quote verification
    lines = raw.splitlines()
    for lineno, line in enumerate(lines, start=1):
        LINE_INDEX[f"{rel}:{lineno}"] = line

    issues = data.get("issues", [])
    for issue in issues:
        key    = issue.get("key", "")
        fields = issue.get("fields", {})
        summary = fields.get("summary", "")
        desc    = fields.get("description", "") or ""
        reporter = fields.get("reporter", "")
        assignee = fields.get("assignee", "") or ""
        # Find the line number for this issue key in the raw file
        def _find_line(needle: str) -> int:
            for i, l in enumerate(lines, start=1):
                if needle in l:
                    return i
            return 1
        issue_line = _find_line(f'"{key}"')
        for text_block in [summary, desc]:
            if not text_block:
                continue
            persons = _persons_in(text_block)
            for pname in [reporter, assignee]:
                canon = next((s for s in SUSPECT_NAMES
                              if s.split()[-1].lower() == pname.split(".")[-1].lower()
                              or pname.replace(".", " ").title() == s), None)
                if canon and canon not in persons:
                    persons.append(canon)
            if persons:
                e = _entry(path, issue_line, f"{key}: {text_block[:200]}", None, persons)
                _register(e)
        for comment in fields.get("comments", []):
            body   = comment.get("body", "")
            author = comment.get("author", "")
            created = comment.get("created", "")
            comment_line = _find_line(body[:40].replace('"', '') if body else "")
            dt = None
            if created:
                try:
                    dt = datetime.fromisoformat(created).astimezone(timezone.utc)
                except ValueError:
                    pass
            persons = _persons_in(body)
            canon_author = next((s for s in SUSPECT_NAMES
                                 if author.split(".")[-1].lower() in s.lower()
                                 or author.replace(".", " ").title() == s), None)
            if canon_author and canon_author not in persons:
                persons.append(canon_author)
            if persons or body:
                e = _entry(path, comment_line,
                           f"{key} comment by {author}: {body[:200]}", dt, persons)
                _register(e)


def load_email() -> None:
    path = BUNDLE / "email_export.mbox"
    rel = _rel(path)
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return
    for lineno, line in enumerate(raw_lines, start=1):
        LINE_INDEX[f"{rel}:{lineno}"] = line

    try:
        mbox = mailbox.mbox(str(path))
    except Exception:
        return

    # We need line numbers; do a best-effort scan
    # Each message starts with "From " at the mbox boundary
    msg_start_lines: list[int] = []
    for i, l in enumerate(raw_lines, start=1):
        if l.startswith("From "):
            msg_start_lines.append(i)

    for idx, msg in enumerate(mbox):
        start_line = msg_start_lines[idx] if idx < len(msg_start_lines) else 1
        subject  = msg.get("subject", "") or ""
        from_hdr = msg.get("from", "") or ""
        to_hdr   = msg.get("to", "") or ""
        date_hdr = msg.get("date", "") or ""
        # Decode body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        body += part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace")
                    except Exception:
                        pass
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode(
                        msg.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                body = str(msg.get_payload())

        full_text = f"{subject} {from_hdr} {to_hdr} {body}"
        persons   = _persons_in(full_text)

        dt = None
        if date_hdr:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_hdr).astimezone(timezone.utc)
            except Exception:
                pass

        if persons:
            quote = f"Subject: {subject} | From: {from_hdr} | {body[:200].strip()}"
            e = _entry(path, start_line, quote, dt, persons)
            _register(e)


def load_calendars() -> None:
    try:
        from icalendar import Calendar
    except ImportError:
        print("WARNING: icalendar not installed, skipping calendars", file=sys.stderr)
        return

    cal_dir = BUNDLE / "calendars"
    for ics_file in sorted(cal_dir.glob("*.ics")):
        rel = _rel(ics_file)
        raw_lines = ics_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for lineno, l in enumerate(raw_lines, start=1):
            LINE_INDEX[f"{rel}:{lineno}"] = l

        try:
            cal = Calendar.from_ical(ics_file.read_bytes())
        except Exception:
            continue

        # Owner name from filename  e.g. iris.ammann.ics
        stem = ics_file.stem  # "iris.ammann"
        owner = next((s for s in SUSPECT_NAMES
                      if stem.replace(".", " ").lower() in s.lower()
                      or s.lower().replace(" ", ".") == stem.lower()), None)

        lineno = 1
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            summary = str(component.get("SUMMARY", ""))
            dtstart = component.get("DTSTART")
            dtend   = component.get("DTEND")

            dt_utc = None
            if dtstart:
                val = dtstart.dt
                if hasattr(val, "tzinfo") and val.tzinfo:
                    dt_utc = val.astimezone(timezone.utc)
                elif hasattr(val, "hour"):
                    # naive datetime — assume Zurich
                    dt_utc = (val - ZURICH_OFFSET).replace(tzinfo=timezone.utc)
                # date-only: skip time comparison
            overlaps_window = False
            if dt_utc and dtend:
                end_val = dtend.dt
                if hasattr(end_val, "tzinfo") and end_val.tzinfo:
                    end_utc = end_val.astimezone(timezone.utc)
                elif hasattr(end_val, "hour"):
                    end_utc = (end_val - ZURICH_OFFSET).replace(tzinfo=timezone.utc)
                else:
                    end_utc = dt_utc
                # Overlaps if event starts before window end AND ends after window start
                if dt_utc < WINDOW_END and end_utc > WINDOW_START:
                    overlaps_window = True

            persons = [owner] if owner else []
            persons += _persons_in(summary)
            persons = list(dict.fromkeys(persons))  # dedup

            # Find approximate line for this event in the ICS file
            event_line = lineno
            for i, l in enumerate(raw_lines, start=1):
                if summary and summary in l:
                    event_line = i
                    break

            quote = f"[{ics_file.stem}] {summary}"
            if overlaps_window:
                quote += "  *** OVERLAPS THEFT WINDOW ***"
            e = _entry(ics_file, event_line, quote, dt_utc, persons)
            _register(e)


def load_garage_log() -> None:
    path = BUNDLE / "garage_barrier_log.csv"
    rel = _rel(path)
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return
    for lineno, l in enumerate(raw_lines, start=1):
        LINE_INDEX[f"{rel}:{lineno}"] = l

    # Header: Datum;Uhrzeit;Kennzeichen;Richtung;Spur;Erkennung
    # Comments start with #
    reader = csv.DictReader(
        (l for l in raw_lines if not l.startswith("#")),
        delimiter=";",
    )
    for lineno_0, row in enumerate(reader, start=4):  # data starts line 4
        datum    = row.get("Datum", "")
        uhrzeit  = row.get("Uhrzeit", "")
        plate    = row.get("Kennzeichen", "")
        richtung = row.get("Richtung", "")  # Einfahrt / Ausfahrt
        dt_str   = f"{datum} {uhrzeit}"
        dt_utc   = _zurich_to_utc(dt_str)
        # Only register entries near or during the theft window ±24h
        if dt_utc:
            delta = abs((dt_utc - WINDOW_START).total_seconds())
            if delta > 86400 * 7:
                # Not near window; still store in LINE_INDEX, skip TIMELINE
                continue
        quote = f"{datum};{uhrzeit};{plate};{richtung}"
        e = _entry(path, lineno_0, quote, dt_utc, [])
        TIMELINE.append(e)   # no person yet; matched in sub-task 2 via permit list


def load_card_feed() -> None:
    path = BUNDLE / "card_feed_q4.csv"
    rel = _rel(path)
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return
    for lineno, l in enumerate(raw_lines, start=1):
        LINE_INDEX[f"{rel}:{lineno}"] = l

    reader = csv.DictReader(
        (l for l in raw_lines if not l.startswith("#")),
    )
    for lineno_0, row in enumerate(reader, start=4):
        cardholder   = row.get("cardholder", "")
        ts_utc_str   = row.get("timestamp_utc", "")
        merchant     = row.get("merchant", "")
        city         = row.get("merchant_city", "")
        amount       = row.get("amount_chf", "")
        dt_utc = None
        if ts_utc_str:
            try:
                dt_utc = datetime.fromisoformat(ts_utc_str.replace("Z", "+00:00"))
            except ValueError:
                pass
        # Resolve cardholder to suspect
        canon = next((s for s in SUSPECT_NAMES
                      if cardholder.split(".")[-1].lower() in s.lower()
                      or cardholder.replace(".", " ").title() == s), None)
        persons = [canon] if canon else []
        quote = f"{ts_utc_str},{cardholder},{merchant},{city},CHF {amount}"
        e = _entry(path, lineno_0, quote, dt_utc, persons)
        _register(e)


def load_parking_permits() -> None:
    path = BUNDLE / "parking_permits.xlsx"
    rel  = _rel(path)
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as ex:
        print(f"WARNING: could not load parking_permits.xlsx: {ex}", file=sys.stderr)
        return
    ws = wb.active
    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        row_str = "\t".join(str(c) if c is not None else "" for c in row)
        LINE_INDEX[f"{rel}:{row_idx}"] = row_str
        persons = _persons_in(row_str)
        if persons:
            e = _entry(path, row_idx, row_str, None, persons)
            _register(e)


def load_pdf(path: Path) -> None:
    rel = _rel(path)
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
    except Exception as ex:
        print(f"WARNING: could not load {path.name}: {ex}", file=sys.stderr)
        return
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for line_in_page, raw in enumerate(text.splitlines(), start=1):
            # Store with page as "line" for source citation
            LINE_INDEX[f"{rel}:{page_num}"] = text[:500]  # first 500 chars of page
        persons = _persons_in(text)
        if persons or page_num == 1:
            e = _entry(path, page_num, text[:300], None, persons)
            _register(e)


# ---------------------------------------------------------------------------
# Main index builder
# ---------------------------------------------------------------------------

def build_index() -> tuple[list[dict], dict[str, list[dict]]]:
    """Build and return (TIMELINE, PERSON_INDEX)."""
    # Load Slack user map
    users_path = BUNDLE / "slack_export" / "users.json"
    user_map: dict[str, str] = {}  # uid -> real_name
    if users_path.exists():
        for u in json.loads(users_path.read_text(encoding="utf-8")):
            user_map[u["id"]] = u["real_name"]

    print("Loading Slack …")
    load_slack(user_map)
    print(f"  {len(TIMELINE)} entries so far")

    print("Loading interviews …")
    load_interviews()
    print(f"  {len(TIMELINE)} entries so far")

    print("Loading markdown files …")
    load_markdown_files()
    print(f"  {len(TIMELINE)} entries so far")

    print("Loading Jira …")
    load_jira()
    print(f"  {len(TIMELINE)} entries so far")

    print("Loading email …")
    load_email()
    print(f"  {len(TIMELINE)} entries so far")

    print("Loading calendars …")
    load_calendars()
    print(f"  {len(TIMELINE)} entries so far")

    print("Loading garage log …")
    load_garage_log()
    print(f"  {len(TIMELINE)} entries so far")

    print("Loading card feed …")
    load_card_feed()
    print(f"  {len(TIMELINE)} entries so far")

    print("Loading parking permits …")
    load_parking_permits()
    print(f"  {len(TIMELINE)} entries so far")

    print("Loading forensic PDF …")
    load_pdf(BUNDLE / "forensic_summary_bakalian.pdf")
    print(f"  {len(TIMELINE)} entries so far")

    # Sort timeline: entries with dt_utc first (chronological), then None
    TIMELINE.sort(key=lambda e: (e["dt_utc"] is None, e["dt_utc"] or datetime.min))

    print(f"\nIndex complete: {len(TIMELINE)} total entries, "
          f"{len(LINE_INDEX)} line-index keys")
    return TIMELINE, PERSON_INDEX


# ---------------------------------------------------------------------------
# Sanity check (standalone run)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_index()

    print("\n=== Suspect mention counts ===")
    for name in SUSPECT_NAMES:
        count = len(PERSON_INDEX[name])
        print(f"  {name:<25} {count:>4} entries")

    print("\n=== Calendar events overlapping theft window ===")
    for entry in TIMELINE:
        if "OVERLAPS THEFT WINDOW" in entry["quote"]:
            print(f"  [{entry['file']}:{entry['line']}]  {entry['quote']}")

    print("\n=== Garage log entries near theft window ===")
    for entry in TIMELINE:
        if "garage_barrier_log" in entry["file"]:
            dt = entry["dt_utc"]
            if dt and WINDOW_START - timedelta(hours=3) <= dt <= WINDOW_END + timedelta(hours=3):
                print(f"  {dt.isoformat()}  {entry['quote']}")

    print("\n=== Card transactions during theft window (UTC) ===")
    for entry in TIMELINE:
        if "card_feed" in entry["file"]:
            dt = entry["dt_utc"]
            if dt and WINDOW_START <= dt <= WINDOW_END:
                print(f"  {dt.isoformat()}  {entry['quote']}")

    print("\nDone.")
