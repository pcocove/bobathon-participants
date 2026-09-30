"""Unit tests for CalendarParser."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure src/ is on the path when running from the project root
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from calendar_parser import CalendarParser  # noqa: E402
from unified_data import DataType  # noqa: E402

SAMPLE_ICS = Path(__file__).parents[1] / "case_bundle" / "calendars" / "andrin.caduff.ics"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def all_records():
    return CalendarParser().parse(SAMPLE_ICS)


# ---------------------------------------------------------------------------
# Tests against the real sample file
# ---------------------------------------------------------------------------

class TestSampleFile:
    def test_record_count(self, all_records):
        """Every VEVENT in the sample file produces exactly one DataPoint."""
        assert len(all_records) == 111

    def test_all_are_calendar_type(self, all_records):
        """data_type must be DataType.calendar for every record."""
        assert all(r.data_type == DataType.calendar for r in all_records)

    def test_first_event_fields(self, all_records):
        """Spot-check the first known event for correct field values."""
        r = all_records[0]
        assert r.id == "andrin.caduff-20250801-0@halcyon-systems.ch"
        assert r.content == "All-hands"
        assert r.start_time == datetime(2025, 8, 1, 10, 45, tzinfo=timezone.utc)
        assert r.end_time == datetime(2025, 8, 1, 11, 45, tzinfo=timezone.utc)
        assert r.persons == ["halina.brzezinska"]
        assert r.location is None

    def test_start_times_are_utc_aware(self, all_records):
        """All start_time values must be UTC-aware datetimes."""
        for r in all_records:
            if r.start_time is not None:
                assert r.start_time.tzinfo is not None
                assert r.start_time.utcoffset().total_seconds() == 0

    def test_end_times_are_utc_aware(self, all_records):
        """All end_time values must be UTC-aware datetimes."""
        for r in all_records:
            if r.end_time is not None:
                assert r.end_time.tzinfo is not None
                assert r.end_time.utcoffset().total_seconds() == 0

    def test_no_blank_ids_or_content(self, all_records):
        """Every record must have a non-blank id and content."""
        for r in all_records:
            assert r.id.strip()
            assert r.content.strip()

    def test_description_metadata(self, all_records):
        """The one event with a DESCRIPTION must have it in metadata."""
        desc_events = [r for r in all_records if "description" in r.metadata]
        assert len(desc_events) == 1
        r = desc_events[0]
        assert r.content == "Checkpoint eval sweep (remote, from home)"
        assert r.metadata["description"] == "Read-only. For the method paper."


# ---------------------------------------------------------------------------
# Edge-case tests using minimal in-memory ICS content
# ---------------------------------------------------------------------------

MINIMAL_ICS = b"""\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:test-event-001
DTSTART:20250901T090000Z
DTEND:20250901T100000Z
SUMMARY:Minimal Event
END:VEVENT
END:VCALENDAR
"""

MINIMAL_WITH_ATTENDEES_ICS = b"""\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:test-event-002
DTSTART:20250902T090000Z
DTEND:20250902T100000Z
SUMMARY:Team Meeting
ORGANIZER;CN=Alice Smith:mailto:alice@example.com
ATTENDEE;CN=Bob Jones:mailto:bob@example.com
ATTENDEE;CN=Carol White:mailto:carol@example.com
END:VEVENT
END:VCALENDAR
"""


class TestEdgeCases:
    def test_missing_optional_fields_do_not_raise(self, tmp_path):
        """Parser must succeed when LOCATION, DESCRIPTION, ORGANIZER, ATTENDEE are absent."""
        ics_file = tmp_path / "minimal.ics"
        ics_file.write_bytes(MINIMAL_ICS)
        records = CalendarParser().parse(ics_file)
        assert len(records) == 1
        r = records[0]
        assert r.id == "test-event-001"
        assert r.content == "Minimal Event"
        assert r.location is None
        assert r.metadata == {}
        assert r.persons == []

    def test_organizer_and_attendees_all_in_persons(self, tmp_path):
        """ORGANIZER CN and all ATTENDEE CNs must appear in persons."""
        ics_file = tmp_path / "attendees.ics"
        ics_file.write_bytes(MINIMAL_WITH_ATTENDEES_ICS)
        records = CalendarParser().parse(ics_file)
        assert len(records) == 1
        r = records[0]
        assert "Alice Smith" in r.persons
        assert "Bob Jones" in r.persons
        assert "Carol White" in r.persons
        assert len(r.persons) == 3

    def test_start_and_end_times(self, tmp_path):
        """Parsed datetimes must be UTC-aware and match the ICS values."""
        ics_file = tmp_path / "minimal.ics"
        ics_file.write_bytes(MINIMAL_ICS)
        r = CalendarParser().parse(ics_file)[0]
        assert r.start_time == datetime(2025, 9, 1, 9, 0, tzinfo=timezone.utc)
        assert r.end_time == datetime(2025, 9, 1, 10, 0, tzinfo=timezone.utc)
