"""Unit tests for HelpdeskParser."""

from __future__ import annotations

from datetime import timezone
from pathlib import Path

from helpdesk_parser import HelpdeskParser
from unified_data import DataType

EXPORT_PATH = Path(__file__).parents[1] / "tests" / "fixtures" / "helpdesk_export.md"


class TestHelpdeskParserWithSampleFile:
    """Tests against the real helpdest-export.md fixture."""

    def setup_method(self):
        self.records = HelpdeskParser().parse(EXPORT_PATH)

    def test_record_count(self):
        assert len(self.records) == 5

    def test_all_records_are_helpdesk_type(self):
        for record in self.records:
            assert record.data_type == DataType.helpdesk

    def test_hd3000_id(self):
        assert self.records[0].id == "HD-3000"

    def test_hd3000_content_starts_with_title(self):
        assert self.records[0].content.startswith("Laptop fan noise")

    def test_hd3000_content_includes_resolution(self):
        assert "Dust. Cleaned." in self.records[0].content

    def test_hd3000_content_has_double_newline_separator(self):
        assert "\n\n" in self.records[0].content

    def test_hd3000_start_time_is_utc_aware(self):
        assert self.records[0].start_time is not None
        assert self.records[0].start_time.tzinfo == timezone.utc

    def test_hd3000_start_time_value(self):
        t = self.records[0].start_time
        assert t.year == 2025
        assert t.month == 8
        assert t.day == 8
        assert t.hour == 10
        assert t.minute == 43

    def test_hd3000_end_time_is_none(self):
        assert self.records[0].end_time is None

    def test_hd3000_persons_includes_requester(self):
        assert "tobias.krall" in self.records[0].persons

    def test_fac330_id(self):
        # FAC-330 is the 5th ticket in the file
        fac330 = next(r for r in self.records if r.id == "FAC-330")
        assert fac330 is not None

    def test_fac330_persons_includes_commenter(self):
        fac330 = next(r for r in self.records if r.id == "FAC-330")
        assert "june.okada" in fac330.persons

    def test_fac330_persons_deduplication(self):
        fac330 = next(r for r in self.records if r.id == "FAC-330")
        assert fac330.persons.count("june.okada") == 1

    def test_fac330_content_includes_comments_block(self):
        fac330 = next(r for r in self.records if r.id == "FAC-330")
        assert "june.okada" in fac330.content

    def test_all_end_times_are_none(self):
        for record in self.records:
            assert record.end_time is None

    def test_all_metadata_is_empty(self):
        for record in self.records:
            assert record.metadata == {}


class TestHelpdeskParserEdgeCases:
    """Tests using minimal in-memory ticket content written to tmp_path."""

    _MINIMAL_TICKET = (
        "### HD-9999 · Minimal ticket\n"
        "Requester: test.user · Opened: 2024-01-01 09:00 · Status: Open\n"
    )

    def test_minimal_ticket_no_body(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text(self._MINIMAL_TICKET, encoding="utf-8")
        records = HelpdeskParser().parse(md_file)
        assert len(records) == 1
        record = records[0]
        assert record.id == "HD-9999"
        assert record.data_type == DataType.helpdesk
        assert record.persons == ["test.user"]
        assert record.end_time is None
        assert record.metadata == {}

    def test_minimal_ticket_content_is_title(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text(self._MINIMAL_TICKET, encoding="utf-8")
        records = HelpdeskParser().parse(md_file)
        assert records[0].content == "Minimal ticket"

    def test_missing_opened_date(self, tmp_path):
        ticket = (
            "### HD-9998 · No date ticket\n"
            "Requester: test.user · Status: Open\n"
        )
        md_file = tmp_path / "no_date.md"
        md_file.write_text(ticket, encoding="utf-8")
        records = HelpdeskParser().parse(md_file)
        assert len(records) == 1
        assert records[0].start_time is None

    def test_persons_only_requester_when_no_comments(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text(self._MINIMAL_TICKET, encoding="utf-8")
        records = HelpdeskParser().parse(md_file)
        assert records[0].persons == ["test.user"]
