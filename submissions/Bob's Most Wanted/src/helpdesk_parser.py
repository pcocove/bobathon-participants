"""Parser for helpdesk/facilities ticket exports (.md) — produces DataPoint records."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from unified_data import DataPoint, DataType

# Matches the heading line: ### HD-3000 · Laptop fan noise
_HEADING_RE = re.compile(r"^###\s+([\w-]+)\s+·\s+(.+)$")

# Matches the metadata line: Requester: tobias.krall · Opened: 2025-08-08 10:43 · Status: ...
_META_RE = re.compile(
    r"Requester:\s*(\S+)\s+·\s+Opened:\s*([\d]{4}-[\d]{2}-[\d]{2}\s+[\d]{2}:[\d]{2})"
)

# Matches a comment author line: [2024-09-30 10:12] june.okada: ...
_COMMENT_RE = re.compile(r"^\s*-\s+\[[\d\- :]+\]\s+(\S+?):")


class HelpdeskParser:
    """Parse a helpdesk/facilities ticket export (.md) and return DataPoint records."""

    def parse(self, path: Path) -> list[DataPoint]:
        """Parse *path* (.md) and return one DataPoint per ticket."""
        text = path.read_text(encoding="utf-8")

        # Split on '### ' headings; first element is any preamble (discarded).
        raw_sections = re.split(r"(?m)^(?=###\s)", text)

        records: list[DataPoint] = []
        for section in raw_sections:
            section = section.strip()
            if not section.startswith("###"):
                continue
            records.append(self._parse_ticket(section))
        return records

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_ticket(self, block: str) -> DataPoint:
        lines = block.splitlines()

        # --- Heading line ---
        heading_match = _HEADING_RE.match(lines[0].strip())
        ticket_id = heading_match.group(1) if heading_match else lines[0].strip()
        title = heading_match.group(2).strip() if heading_match else ""

        # --- Metadata line (second non-blank line) ---
        meta_line = ""
        meta_line_index = 1
        for i, line in enumerate(lines[1:], start=1):
            if line.strip():
                meta_line = line.strip()
                meta_line_index = i
                break

        meta_match = _META_RE.search(meta_line)
        requester = meta_match.group(1) if meta_match else ""
        start_time = self._parse_opened(meta_match.group(2)) if meta_match else None

        # --- Body: everything after the metadata line ---
        body_lines = lines[meta_line_index + 1:]
        body = "\n".join(body_lines).strip()

        content = title + ("\n\n" + body if body else "")

        persons = self._collect_persons(requester, body)

        return DataPoint(
            id=ticket_id,
            data_type=DataType.helpdesk,
            content=content,
            start_time=start_time,
            end_time=None,
            persons=persons,
            metadata={},
        )

    @staticmethod
    def _parse_opened(value: str) -> datetime | None:
        """Parse 'YYYY-MM-DD HH:MM' as a UTC-aware datetime, or None."""
        if not value:
            return None
        try:
            dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        return dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def _collect_persons(requester: str, body: str) -> list[str]:
        """Return deduplicated list of requester + all comment authors."""
        seen: set[str] = set()
        persons: list[str] = []

        if requester:
            seen.add(requester)
            persons.append(requester)

        for line in body.splitlines():
            m = _COMMENT_RE.match(line)
            if m:
                username = m.group(1)
                if username not in seen:
                    seen.add(username)
                    persons.append(username)

        return persons
