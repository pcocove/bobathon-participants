#!/usr/bin/env python3
"""MCP Server for querying unified_data JSONL files.

Exposes tools:
  - query_unified_data   : search across all data types
  - query_garage         : search garage barrier events
  - query_parking_permits: search parking permits
  - query_calendar       : search calendar events
  - query_slack          : search Slack messages
  - fuzzy_search_persons : fuzzy-match a name fragment across all data sources
  - fuzzy_search_content : fuzzy-match a query against all words in every record
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Resolve unified_data directory relative to this file
# ---------------------------------------------------------------------------
UNIFIED_DATA_DIR = Path(__file__).parent.parent / "unified_data"

DATA_FILES: dict[str, Path] = {
    "garage": UNIFIED_DATA_DIR / "garage.jsonl",
    "parking_permit": UNIFIED_DATA_DIR / "parking_permits.jsonl",
    "calendar": UNIFIED_DATA_DIR / "calendar.jsonl",
    "slack": UNIFIED_DATA_DIR / "slack.jsonl",
    "email": UNIFIED_DATA_DIR / "email.jsonl",
    "helpdesk": UNIFIED_DATA_DIR / "helpdesk.jsonl",
    "card_feed": UNIFIED_DATA_DIR / "card_feed.jsonl",
}

mcp = FastMCP("unified-data-server")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load all records from a JSONL file."""
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _person_tokens(person_str: str) -> list[str]:
    """Extract searchable lowercase tokens from a persons-field value.

    Handles the formats found across all data sources:
      - email address : ``renata.vogel@halcyon-systems.ch``  -> [renata, vogel, renata.vogel]
      - display name  : ``Iris Ammann``                      -> [iris, ammann]
      - abbreviated   : ``M. Keller``                        -> [m, keller]
      - username      : ``tobias.krall``                     -> [tobias, krall, tobias.krall]
    """
    s = person_str.lower()
    # Strip domain from e-mail addresses
    local = s.split("@")[0]
    # Split on dots, spaces, hyphens, underscores
    parts = re.split(r"[\s.\-_]+", local)
    tokens = [p for p in parts if p]
    # Also keep the joined local part (e.g. "tobias.krall") as-is so substring
    # matching still works for callers who pass the full username.
    if "." in local:
        tokens.append(local)
    return tokens


def _fuzzy_score(query: str, candidate: str, threshold: float = 0.75) -> float:
    """Return a similarity ratio in [0, 1]; 0 means below threshold."""
    q = query.lower().strip()
    c = candidate.lower().strip()
    if not q or not c:
        return 0.0
    # Skip very short tokens (single-letter abbreviations) to avoid false positives;
    # they would trivially be substrings of any longer query.
    if len(c) < 2:
        return 0.0
    # Exact substring match is a full score, but only when the candidate is at
    # least half the length of the query (prevents "a" matching "renata").
    if q in c or (c in q and len(c) >= max(2, len(q) // 2)):
        return 1.0
    ratio = SequenceMatcher(None, q, c).ratio()
    return ratio if ratio >= threshold else 0.0


def _record_person_tokens(record: dict[str, Any]) -> list[str]:
    """Collect all person tokens from persons list + metadata resolved_person."""
    tokens: list[str] = []
    for p in record.get("persons", []):
        tokens.extend(_person_tokens(p))
    resolved = record.get("metadata", {}).get("resolved_person", "")
    if resolved:
        tokens.extend(_person_tokens(resolved))
    return tokens


def _matches(record: dict[str, Any], person: str | None, keyword: str | None, date: str | None) -> bool:
    """Return True when a record satisfies all provided filter criteria."""
    if person:
        persons_lower = [p.lower() for p in record.get("persons", [])]
        content_lower = record.get("content", "").lower()
        meta_str = json.dumps(record.get("metadata", {})).lower()
        needle = person.lower()
        if not any(needle in p for p in persons_lower) and needle not in content_lower and needle not in meta_str:
            return False

    if keyword:
        haystack = json.dumps(record).lower()
        if keyword.lower() not in haystack:
            return False

    if date:
        # Accept YYYY-MM-DD or partial date strings like "2025-08-01"
        haystack = json.dumps(record).lower()
        if date.lower() not in haystack:
            return False

    return True


def _format_results(records: list[dict[str, Any]], limit: int) -> str:
    if not records:
        return "No matching records found."
    subset = records[:limit]
    lines = [f"Found {len(records)} record(s), showing first {len(subset)}:\n"]
    for r in subset:
        lines.append(json.dumps(r, ensure_ascii=False))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _parse_dt(value: str) -> datetime | None:
    """Parse an ISO 8601 string (with or without time/timezone) into a UTC-aware datetime."""
    if not value:
        return None
    # Try progressively shorter formats
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value.rstrip("Z").split("+")[0], fmt.rstrip("Z"))
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _in_time_range(record: dict[str, Any], after: datetime | None, before: datetime | None) -> bool:
    """Return True when the record's start_time falls within [after, before]."""
    if after is None and before is None:
        return True
    ts = record.get("start_time")
    if not ts:
        # Records without a timestamp are excluded when a time filter is active
        return False
    dt = _parse_dt(ts)
    if dt is None:
        return False
    if after and dt < after:
        return False
    if before and dt > before:
        return False
    return True


@mcp.tool(
    description=(
        "Fuzzy-search for a person by first name, last name, display name, e-mail address, "
        "or any name fragment across ALL data sources (email, helpdesk, garage, parking_permits, "
        "calendar, slack). Returns records where the query fuzzy-matches any token extracted from "
        "the persons field (first name / last name / username parts / e-mail local part). "
        "Use this when you only know a partial name such as a first name and want to discover "
        "matching e-mail addresses, full names, and associated records. "
        "The `threshold` parameter (0–1, default 0.75) controls how strict the matching is. "
        "Optionally restrict results to a time range with `after` and `before` "
        "(ISO 8601 strings, e.g. '2025-08-01' or '2025-08-04T07:00:00Z')."
    )
)
def fuzzy_search_persons(
    query: str,
    threshold: float = 0.75,
    limit: int = 20,
    after: str = "",
    before: str = "",
) -> str:
    """Fuzzy-match *query* against person tokens in every data source."""
    if not query:
        return "Please provide a query string."

    after_dt = _parse_dt(after)
    before_dt = _parse_dt(before)

    if after and after_dt is None:
        return f"Could not parse `after` value: {after!r}. Use ISO 8601 format, e.g. '2025-08-01'."
    if before and before_dt is None:
        return f"Could not parse `before` value: {before!r}. Use ISO 8601 format, e.g. '2025-08-31'."

    scored: list[tuple[float, dict[str, Any]]] = []

    for path in DATA_FILES.values():
        if not path.exists():
            continue
        for record in _load_jsonl(path):
            if not _in_time_range(record, after_dt, before_dt):
                continue
            tokens = _record_person_tokens(record)
            best = max((_fuzzy_score(query, tok, threshold) for tok in tokens), default=0.0)
            if best > 0:
                scored.append((best, record))

    range_desc = ""
    if after_dt or before_dt:
        range_desc = f", time range: [{after or '…'} → {before or '…'}]"

    if not scored:
        return f"No records found matching '{query}' (threshold={threshold}{range_desc})."

    # Sort by descending score, deduplicate by record id
    scored.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    unique: list[tuple[float, dict[str, Any]]] = []
    for score, rec in scored:
        rid = rec.get("id", "")
        if rid not in seen:
            seen.add(rid)
            unique.append((score, rec))

    subset = unique[:limit]
    lines = [f"Found {len(unique)} matching record(s), showing first {len(subset)} (threshold={threshold}{range_desc}):\n"]
    for score, rec in subset:
        lines.append(f"[score={score:.2f}] {json.dumps(rec, ensure_ascii=False)}")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Fuzzy-search for any word or phrase across ALL fields of every record in ALL data sources "
        "(email, helpdesk, garage, parking_permits, calendar, slack, card_feed). "
        "Tokenises the full JSON of each record into words and fuzzy-matches each word against the query. "
        "Use this when you want to find records mentioning a specific place, merchant, subject, "
        "channel, or any other non-name term. "
        "The `threshold` parameter (0–1, default 0.75) controls how strict the matching is. "
        "Optionally restrict results to a time range with `after` and `before` "
        "(ISO 8601 strings, e.g. '2025-08-01' or '2025-08-04T07:00:00Z')."
    )
)
def fuzzy_search_content(
    query: str,
    threshold: float = 0.75,
    limit: int = 20,
    after: str = "",
    before: str = "",
) -> str:
    """Fuzzy-match *query* against every word token found in each record's full JSON."""
    if not query:
        return "Please provide a query string."

    after_dt = _parse_dt(after)
    before_dt = _parse_dt(before)

    if after and after_dt is None:
        return f"Could not parse `after` value: {after!r}. Use ISO 8601 format, e.g. '2025-08-01'."
    if before and before_dt is None:
        return f"Could not parse `before` value: {before!r}. Use ISO 8601 format, e.g. '2025-08-31'."

    def _content_tokens(record: dict[str, Any]) -> list[str]:
        """Extract all word tokens from the full JSON of a record."""
        raw = json.dumps(record, ensure_ascii=False).lower()
        # Split on anything that is not a letter, digit, dot, hyphen, or @
        return [t for t in re.split(r'[^\w.\-@]+', raw) if len(t) >= 2]

    scored: list[tuple[float, dict[str, Any]]] = []

    for path in DATA_FILES.values():
        if not path.exists():
            continue
        for record in _load_jsonl(path):
            if not _in_time_range(record, after_dt, before_dt):
                continue
            tokens = _content_tokens(record)
            best = max((_fuzzy_score(query, tok, threshold) for tok in tokens), default=0.0)
            if best > 0:
                scored.append((best, record))

    range_desc = ""
    if after_dt or before_dt:
        range_desc = f", time range: [{after or '…'} → {before or '…'}]"

    if not scored:
        return f"No records found matching '{query}' (threshold={threshold}{range_desc})."

    scored.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    unique: list[tuple[float, dict[str, Any]]] = []
    for score, rec in scored:
        rid = rec.get("id", "")
        if rid not in seen:
            seen.add(rid)
            unique.append((score, rec))

    subset = unique[:limit]
    lines = [f"Found {len(unique)} matching record(s), showing first {len(subset)} (threshold={threshold}{range_desc}):\n"]
    for score, rec in subset:
        lines.append(f"[score={score:.2f}] {json.dumps(rec, ensure_ascii=False)}")
    return "\n".join(lines)


@mcp.tool(description="Search across ALL unified_data sources (garage, parking_permits, calendar, slack, email, helpdesk, card_feed). "
          "Optionally filter by person name, keyword, or date (YYYY-MM-DD). "
          "Returns up to `limit` matching records as JSON lines.")
def query_unified_data(
    person: str = "",
    keyword: str = "",
    date: str = "",
    limit: int = 20,
) -> str:
    results: list[dict[str, Any]] = []
    p = person or None
    k = keyword or None
    d = date or None
    for data_type, path in DATA_FILES.items():
        if not path.exists():
            continue
        for record in _load_jsonl(path):
            if _matches(record, p, k, d):
                results.append(record)
    return _format_results(results, limit)


@mcp.tool(description="Search garage barrier events (entries and exits). "
          "Filter by person name, license plate (keyword), or date (YYYY-MM-DD).")
def query_garage(
    person: str = "",
    keyword: str = "",
    date: str = "",
    limit: int = 20,
) -> str:
    path = DATA_FILES["garage"]
    if not path.exists():
        return f"File not found: {path}"
    results = [r for r in _load_jsonl(path) if _matches(r, person or None, keyword or None, date or None)]
    return _format_results(results, limit)


@mcp.tool(description="Search parking permits. "
          "Filter by permit holder name, permit ID, license plate, or vehicle keyword.")
def query_parking_permits(
    person: str = "",
    keyword: str = "",
    date: str = "",
    limit: int = 20,
) -> str:
    path = DATA_FILES["parking_permit"]
    if not path.exists():
        return f"File not found: {path}"
    results = [r for r in _load_jsonl(path) if _matches(r, person or None, keyword or None, date or None)]
    return _format_results(results, limit)


@mcp.tool(description="Search calendar events across all employees. "
          "Filter by person (calendar owner or attendee), keyword in summary, or date (YYYY-MM-DD).")
def query_calendar(
    person: str = "",
    keyword: str = "",
    date: str = "",
    limit: int = 20,
) -> str:
    path = DATA_FILES["calendar"]
    if not path.exists():
        return f"File not found: {path}"
    results = [r for r in _load_jsonl(path) if _matches(r, person or None, keyword or None, date or None)]
    return _format_results(results, limit)


@mcp.tool(description="Search Slack messages. "
          "Filter by person (author), channel name or message keyword, or date (YYYY-MM-DD).")
def query_slack(
    person: str = "",
    keyword: str = "",
    date: str = "",
    limit: int = 20,
) -> str:
    path = DATA_FILES["slack"]
    if not path.exists():
        return f"File not found: {path}"
    results = [r for r in _load_jsonl(path) if _matches(r, person or None, keyword or None, date or None)]
    return _format_results(results, limit)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
