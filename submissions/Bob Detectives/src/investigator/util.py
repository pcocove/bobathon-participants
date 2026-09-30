"""Small shared helpers: time handling, text snippets, citations."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


def tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def fmt_dt(dt: datetime | None, with_day: bool = True) -> str:
    if dt is None:
        return "?"
    return dt.strftime("%a %d.%m.%Y %H:%M" if with_day else "%H:%M")


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def dst_shift_minutes(zone: ZoneInfo, when: datetime) -> int:
    """Minutes by which local time is ahead of standard time at `when` (60 in summer)."""
    aware = when if when.tzinfo else when.replace(tzinfo=zone)
    dst = aware.astimezone(zone).dst()
    return int(dst.total_seconds() // 60) if dst else 0


def dst_transitions(zone: ZoneInfo, start: date, end: date) -> list[date]:
    """Dates (local) on which the UTC offset changes."""
    out = []
    d = start
    prev = datetime(d.year, d.month, d.day, 12, tzinfo=zone).utcoffset()
    while d < end:
        d += timedelta(days=1)
        cur = datetime(d.year, d.month, d.day, 12, tzinfo=zone).utcoffset()
        if cur != prev:
            out.append(d)
        prev = cur
    return out


def stable_key(*parts: object) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return h[:12]


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[\"'(])")


def sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s.strip()]


def best_span(raw_line: str, needle: str | None = None, max_len: int = 220) -> str:
    """Pick an exact substring of `raw_line` to use as a quote.

    Prefers the sentence containing `needle`; never returns text that is not in the line.
    """
    line = raw_line.rstrip("\n")
    body = line
    # interview transcript lines: drop "[00:04:13] SPEAKER 2: " prefix
    m = re.match(r"^\s*\[\d\d:\d\d:\d\d\]\s+[^:]{1,20}:\s+", line)
    if m:
        body = line[m.end():]
    # JSON string lines: keep only the value
    m = re.match(r'^\s*"(?:text|body|description|summary)":\s+"(.*)",?\s*$', line)
    if m:
        body = m.group(1)
        # a quote must not straddle an escape sequence
        if "\\" in body:
            parts = [p for p in re.split(r"\\[nt\"\\/]|\\u[0-9a-fA-F]{4}", body) if p.strip()]
            if needle:
                parts = [p for p in parts if needle.lower() in p.lower()] or parts
            body = max(parts, key=len) if parts else body
    candidates = sentences(body) if len(body) > max_len else [body]
    if needle:
        hits = [s for s in candidates if needle.lower() in s.lower()]
        if hits:
            candidates = hits
    span = candidates[0].strip()
    if len(span) > max_len:
        if needle and needle.lower() in span.lower():
            i = span.lower().index(needle.lower())
            start = max(0, i - max_len // 2)
            span = span[start:start + max_len]
            # trim to word boundaries without leaving the line
            span = span[span.find(" ") + 1:] if start > 0 and " " in span else span
            if " " in span[-20:]:
                span = span[: span.rfind(" ")]
        else:
            span = span[:max_len]
            if " " in span[-20:]:
                span = span[: span.rfind(" ")]
    span = span.strip()
    assert span in line, (span, line)
    return span


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def clip(s: str, n: int = 160) -> str:
    s = norm_space(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
