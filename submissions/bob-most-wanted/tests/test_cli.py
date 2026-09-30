"""CLI smoke tests — verify dispatch to the correct parser by file suffix."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import cli  # noqa: E402
from unified_data import DataType, UnifiedData  # noqa: E402

_MINIMAL_MBOX = (
    "From sender@example.com Mon Jan 01 00:00:00 2024\n"
    "Message-ID: <cli-smoke-001@example.com>\n"
    "Date: Mon, 01 Jan 2024 10:00:00 +0000\n"
    "From: sender@example.com\n"
    "To: recipient@example.com\n"
    "Subject: CLI smoke test\n"
    "Content-Type: text/plain; charset=utf-8\n"
    "\n"
    "Body text.\n"
)

_MINIMAL_ICS = (
    "BEGIN:VCALENDAR\n"
    "VERSION:2.0\n"
    "BEGIN:VEVENT\n"
    "UID:cli-smoke-ics-001@example.com\n"
    "SUMMARY:CLI ICS smoke test\n"
    "DTSTART:20240101T100000Z\n"
    "DTEND:20240101T110000Z\n"
    "END:VEVENT\n"
    "END:VCALENDAR\n"
)

_MINIMAL_MD = (
    "### HD-9001 · CLI smoke test ticket\n"
    "Requester: cli.smoker · Opened: 2024-01-01 09:00 · Status: Open\n"
)


@pytest.fixture(autouse=True)
def reset_unified_data():
    """Reset the global unified_data accumulator before each test."""
    cli.unified_data = UnifiedData()
    yield
    cli.unified_data = UnifiedData()


def test_mbox_dispatches_to_email_parser(tmp_path, monkeypatch):
    mbox_file = tmp_path / "test.mbox"
    mbox_file.write_text(_MINIMAL_MBOX, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["bobathon", "--input", str(mbox_file)])
    cli.main()

    assert len(cli.unified_data.records) == 1
    assert cli.unified_data.records[0].data_type == DataType.email


def test_ics_dispatches_to_calendar_parser(tmp_path, monkeypatch):
    ics_file = tmp_path / "test.ics"
    ics_file.write_text(_MINIMAL_ICS, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["bobathon", "--input", str(ics_file)])
    cli.main()

    assert len(cli.unified_data.records) == 1
    assert cli.unified_data.records[0].data_type == DataType.calendar


def test_md_dispatches_to_helpdesk_parser(tmp_path, monkeypatch):
    md_file = tmp_path / "test.md"
    md_file.write_text(_MINIMAL_MD, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["bobathon", "--input", str(md_file)])
    cli.main()

    assert len(cli.unified_data.records) == 1
    assert cli.unified_data.records[0].data_type == DataType.helpdesk


def test_mbox_writes_jsonl(tmp_path, monkeypatch):
    mbox_file = tmp_path / "test.mbox"
    mbox_file.write_text(_MINIMAL_MBOX, encoding="utf-8")
    out_file = tmp_path / "out.jsonl"

    monkeypatch.setattr(sys, "argv", ["bobathon", "--input", str(mbox_file), "--output", str(out_file)])
    cli.main()

    assert out_file.exists()
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["data_type"] == "email"


def test_ics_writes_jsonl(tmp_path, monkeypatch):
    ics_file = tmp_path / "test.ics"
    ics_file.write_text(_MINIMAL_ICS, encoding="utf-8")
    out_file = tmp_path / "out.jsonl"

    monkeypatch.setattr(sys, "argv", ["bobathon", "--input", str(ics_file), "--output", str(out_file)])
    cli.main()

    assert out_file.exists()
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["data_type"] == "calendar"


def test_md_writes_jsonl(tmp_path, monkeypatch):
    md_file = tmp_path / "test.md"
    md_file.write_text(_MINIMAL_MD, encoding="utf-8")
    out_file = tmp_path / "out.jsonl"

    monkeypatch.setattr(sys, "argv", ["bobathon", "--input", str(md_file), "--output", str(out_file)])
    cli.main()

    assert out_file.exists()
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["data_type"] == "helpdesk"


def test_no_output_flag_does_not_write_file(tmp_path, monkeypatch):
    mbox_file = tmp_path / "test.mbox"
    mbox_file.write_text(_MINIMAL_MBOX, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["bobathon", "--input", str(mbox_file)])
    cli.main()

    assert not any(tmp_path.glob("*.jsonl"))


def test_output_must_end_in_jsonl(tmp_path, monkeypatch):
    mbox_file = tmp_path / "test.mbox"
    mbox_file.write_text(_MINIMAL_MBOX, encoding="utf-8")
    out_file = tmp_path / "out.json"

    monkeypatch.setattr(sys, "argv", ["bobathon", "--input", str(mbox_file), "--output", str(out_file)])
    with pytest.raises(SystemExit):
        cli.main()
