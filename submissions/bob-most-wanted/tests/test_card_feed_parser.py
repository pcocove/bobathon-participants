"""Unit tests for CardFeedParser."""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure src/ is on the path when running from the project root
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from card_feed_parser import CardFeedParser  # noqa: E402
from unified_data import DataType  # noqa: E402

SAMPLE_CSV = (
    Path(__file__).parents[2]
    / "bobathon-participants"
    / "meridian_case_bundle"
    / "case_bundle"
    / "card_feed_q4.csv"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def all_records():
    return CardFeedParser().parse(SAMPLE_CSV)


# ---------------------------------------------------------------------------
# Tests against the real sample file
# ---------------------------------------------------------------------------


class TestSampleFile:
    def test_records_produced(self, all_records):
        """Parser must return at least one record from the real file."""
        assert len(all_records) > 0

    def test_all_are_credit_card_type(self, all_records):
        """data_type must be DataType.credit_card for every record."""
        assert all(r.data_type == DataType.credit_card for r in all_records)

    def test_first_record_fields(self, all_records):
        """Spot-check the first known transaction for correct field values."""
        r = all_records[0]
        assert r.id == "card-TX880000"
        assert r.persons == ["dessie.moran"]
        assert r.start_time == datetime(2025, 8, 1, 6, 0, 0, tzinfo=timezone.utc)
        assert r.location == "St. Gallen"
        assert r.metadata["merchant"] == "Office World"
        assert r.metadata["mcc"] == 5943
        assert r.metadata["amount_chf"] == pytest.approx(255.20)
        assert r.metadata["card_last4"] == "1686"

    def test_start_times_are_utc_aware(self, all_records):
        """All start_time values must be UTC-aware datetimes."""
        for r in all_records:
            assert r.start_time is not None
            assert r.start_time.tzinfo is not None
            assert r.start_time.utcoffset().total_seconds() == 0

    def test_no_end_times(self, all_records):
        """Card transactions are point-in-time events; end_time must be None."""
        assert all(r.end_time is None for r in all_records)

    def test_no_blank_ids_or_content(self, all_records):
        """Every record must have a non-blank id and content."""
        for r in all_records:
            assert r.id.strip()
            assert r.content.strip()

    def test_cardholder_in_persons(self, all_records):
        """Each record's cardholder handle must appear in persons."""
        for r in all_records:
            assert len(r.persons) == 1
            assert r.metadata["cardholder"] in r.persons

    def test_ids_are_unique(self, all_records):
        """Transaction IDs in the source file must be unique."""
        ids = [r.id for r in all_records]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Edge-case tests using minimal in-memory CSV content
# ---------------------------------------------------------------------------

MINIMAL_CSV = """\
# comment line – must be ignored
txn_id,timestamp_utc,cardholder,card_last4,merchant,merchant_city,mcc,amount_chf
TXTEST01,2025-09-01T12:00:00Z,test.user,1234,Test Merchant,Test City,5411,42.50
"""

MULTI_ROW_CSV = """\
txn_id,timestamp_utc,cardholder,card_last4,merchant,merchant_city,mcc,amount_chf
TXTEST02,2025-09-02T08:00:00Z,alice.smith,0001,Migros,Bern,5411,10.00
TXTEST03,2025-09-02T09:30:00Z,bob.jones,0002,SBB CFF FFS,Zürich,4111,55.00
"""


class TestEdgeCases:
    def test_comment_lines_skipped(self, tmp_path):
        """Lines starting with '#' must not produce records."""
        csv_file = tmp_path / "minimal.csv"
        csv_file.write_text(MINIMAL_CSV, encoding="utf-8")
        records = CardFeedParser().parse(csv_file)
        assert len(records) == 1

    def test_minimal_record_fields(self, tmp_path):
        """All required fields are correctly parsed from a minimal row."""
        csv_file = tmp_path / "minimal.csv"
        csv_file.write_text(MINIMAL_CSV, encoding="utf-8")
        r = CardFeedParser().parse(csv_file)[0]
        assert r.id == "card-TXTEST01"
        assert r.data_type == DataType.credit_card
        assert r.persons == ["test.user"]
        assert r.start_time == datetime(2025, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert r.end_time is None
        assert r.location == "Test City"
        assert r.metadata["merchant"] == "Test Merchant"
        assert r.metadata["mcc"] == 5411
        assert r.metadata["amount_chf"] == pytest.approx(42.50)
        assert r.metadata["card_last4"] == "1234"

    def test_multiple_rows(self, tmp_path):
        """Parser produces one DataPoint per data row."""
        csv_file = tmp_path / "multi.csv"
        csv_file.write_text(MULTI_ROW_CSV, encoding="utf-8")
        records = CardFeedParser().parse(csv_file)
        assert len(records) == 2
        assert records[0].metadata["cardholder"] == "alice.smith"
        assert records[1].metadata["cardholder"] == "bob.jones"

    def test_content_includes_key_fields(self, tmp_path):
        """The content string must reference txn_id, cardholder, amount and merchant."""
        csv_file = tmp_path / "minimal.csv"
        csv_file.write_text(MINIMAL_CSV, encoding="utf-8")
        r = CardFeedParser().parse(csv_file)[0]
        assert "TXTEST01" in r.content
        assert "test.user" in r.content
        assert "42.50" in r.content
        assert "Test Merchant" in r.content
