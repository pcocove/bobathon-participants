"""Parser for mbox (.mbox) files — produces DataPoint records."""

from __future__ import annotations

import mailbox
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

from unified_data import DataPoint, DataType


class EmailParser:
    """Parse an mbox file and return a list of normalised DataPoint records."""

    def parse(self, path: Path) -> list[DataPoint]:
        """Parse *path* (.mbox) and return one DataPoint per message."""
        mbox = mailbox.mbox(path, factory=None, create=False)

        records: list[DataPoint] = []
        for message in mbox:
            records.append(self._parse_message(message))
        return records

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_message(self, msg: mailbox.mboxMessage) -> DataPoint:
        msg_id: str = self._strip_angle_brackets(msg.get("Message-ID", ""))
        subject: str = self._decode_header_value(msg.get("Subject", ""))

        body: str = self._extract_body(msg)
        content: str = subject + "\n\n" + body.strip()

        start_time = self._parse_date(msg.get("Date"))
        end_time = start_time

        persons: list[str] = self._collect_persons(msg)

        metadata: dict = {}
        attachment = msg.get("X-Attachment")
        if attachment is not None:
            metadata["attachments"] = [attachment.strip()]

        return DataPoint(
            id=msg_id,
            data_type=DataType.email,
            content=content,
            start_time=start_time,
            end_time=end_time,
            persons=persons,
            metadata=metadata,
        )

    @staticmethod
    def _strip_angle_brackets(value: str) -> str:
        """Strip surrounding angle brackets and whitespace from a Message-ID."""
        return value.strip().lstrip("<").rstrip(">").strip()

    @staticmethod
    def _decode_header_value(value: str) -> str:
        """Decode an RFC 2047 encoded header value to a plain string."""
        parts = decode_header(value)
        decoded: list[str] = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return "".join(decoded).strip()

    @staticmethod
    def _extract_body(msg: mailbox.mboxMessage) -> str:
        """Return the plain-text body of *msg*."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
            return ""
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        # get_payload without decode=True returns str for non-encoded messages
        raw = msg.get_payload()
        return raw if isinstance(raw, str) else ""

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        """Parse an RFC 2822 Date header to a UTC-aware datetime, or None."""
        if not value:
            return None
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _collect_persons(msg: mailbox.mboxMessage) -> list[str]:
        """Collect unique persons from From, To, and Cc headers.

        Prefer display name when present; fall back to email address.
        """
        raw_headers: list[str] = []
        for header in ("From", "To", "Cc"):
            val = msg.get(header)
            if val:
                raw_headers.append(val)

        seen: set[str] = set()
        persons: list[str] = []
        for name, addr in getaddresses(raw_headers):
            label = name.strip() if name.strip() else addr.strip()
            if label and label not in seen:
                seen.add(label)
                persons.append(label)
        return persons
