"""Unit tests for EmailParser."""

from __future__ import annotations

from datetime import timezone
from pathlib import Path

import pytest

from email_parser import EmailParser
from unified_data import DataType

MBOX_PATH = Path(__file__).parents[1] / "tests" / "fixtures" / "email_export.mbox"


class TestEmailParserWithSampleFile:
    """Tests against the real email_export.mbox fixture."""

    def setup_method(self):
        self.records = EmailParser().parse(MBOX_PATH)

    def test_record_count(self):
        assert len(self.records) == 2

    def test_all_records_are_email_type(self):
        for record in self.records:
            assert record.data_type == DataType.email

    def test_first_message_id(self):
        assert self.records[0].id == "20250000.5914@halcyon-systems.ch"

    def test_first_message_content_starts_with_subject(self):
        assert self.records[0].content.startswith("Q1 board pack: sections due Fri")

    def test_first_message_content_has_double_newline_separator(self):
        assert "\n\n" in self.records[0].content

    def test_first_message_persons_includes_sender(self):
        assert "renata.vogel@halcyon-systems.ch" in self.records[0].persons

    def test_first_message_persons_includes_recipients(self):
        persons = self.records[0].persons
        assert "iris.ammann@halcyon-systems.ch" in persons
        assert "noemi.rochat@halcyon-systems.ch" in persons
        assert "dessie.moran@halcyon-systems.ch" in persons
        assert "lukas.hofer@halcyon-systems.ch" in persons

    def test_second_message_attachment_metadata(self):
        assert self.records[1].metadata.get("attachments") == [
            "Halcyon_Board_Q1_2025_final.pdf"
        ]

    def test_second_message_persons_includes_cc(self):
        persons = self.records[1].persons
        assert "dov.halperin@halcyon-systems.ch" in persons
        assert "iris.ammann@halcyon-systems.ch" in persons

    def test_start_times_are_utc_aware(self):
        for record in self.records:
            assert record.start_time is not None
            assert record.start_time.tzinfo == timezone.utc

    def test_end_time_equals_start_time(self):
        for record in self.records:
            assert record.end_time == record.start_time

    def test_first_message_has_no_attachments_key(self):
        assert "attachments" not in self.records[0].metadata


class TestEmailParserEdgeCases:
    """Tests using minimal in-memory mbox content written to tmp_path."""

    _MINIMAL_MBOX = (
        "From sender@example.com Mon Jan 01 00:00:00 2024\n"
        "Message-ID: <minimal-001@example.com>\n"
        "Date: Mon, 01 Jan 2024 10:00:00 +0000\n"
        "From: sender@example.com\n"
        "To: recipient@example.com\n"
        "Subject: Minimal test\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "Hello world.\n"
    )

    def test_no_cc_no_attachment(self, tmp_path):
        mbox_file = tmp_path / "test.mbox"
        mbox_file.write_text(self._MINIMAL_MBOX, encoding="utf-8")
        records = EmailParser().parse(mbox_file)
        assert len(records) == 1
        record = records[0]
        assert "attachments" not in record.metadata
        assert record.data_type == DataType.email

    def test_missing_date_header(self, tmp_path):
        mbox_no_date = (
            "From sender@example.com Mon Jan 01 00:00:00 2024\n"
            "Message-ID: <no-date-001@example.com>\n"
            "From: sender@example.com\n"
            "To: recipient@example.com\n"
            "Subject: No date test\n"
            "Content-Type: text/plain; charset=utf-8\n"
            "\n"
            "Body text.\n"
        )
        mbox_file = tmp_path / "no_date.mbox"
        mbox_file.write_text(mbox_no_date, encoding="utf-8")
        records = EmailParser().parse(mbox_file)
        assert len(records) == 1
        assert records[0].start_time is None
        assert records[0].end_time is None

    def test_persons_deduplication(self, tmp_path):
        mbox_dup = (
            "From sender@example.com Mon Jan 01 00:00:00 2024\n"
            "Message-ID: <dup-001@example.com>\n"
            "Date: Mon, 01 Jan 2024 10:00:00 +0000\n"
            "From: sender@example.com\n"
            "To: sender@example.com, other@example.com\n"
            "Subject: Dedup test\n"
            "Content-Type: text/plain; charset=utf-8\n"
            "\n"
            "Body.\n"
        )
        mbox_file = tmp_path / "dup.mbox"
        mbox_file.write_text(mbox_dup, encoding="utf-8")
        records = EmailParser().parse(mbox_file)
        persons = records[0].persons
        assert persons.count("sender@example.com") == 1
