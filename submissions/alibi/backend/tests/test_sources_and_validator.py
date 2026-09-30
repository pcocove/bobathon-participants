"""Quote verification, line numbers, escaping and the independent export validator."""
import copy
import json
from pathlib import Path

import pytest

from alibi import sources
from alibi.config import SETTINGS
from alibi.validator import check_source, validate_verdict

BUNDLE = SETTINGS.bundle
TEMPLATE = SETTINGS.template


# ------------------------------------------------------------------ echte Fallakten (nur lesend)

def test_handout_example_quote_is_exact():
    r = sources.verify_quote("slack_export/general/2025-10-12.json:5", "office is beautifully quiet on a sunday")
    assert r["ok"] and r["status"] == "exact"


def test_altered_quote_is_rejected():
    r = sources.verify_quote("slack_export/general/2025-10-12.json:5", "office is beautifully quiet on a saturday")
    assert not r["ok"] and r["status"] == "not_found"


def test_wrong_line_is_rejected():
    r = sources.verify_quote("slack_export/general/2025-10-12.json:6", "office is beautifully quiet on a sunday")
    assert not r["ok"]


def test_missing_file_and_out_of_range():
    assert sources.verify_quote("nope/does_not_exist.md:1", "x")["status"] == "invalid_source"
    assert sources.verify_quote("README.md:99999", "HALCYON")["status"] == "invalid_source"
    assert sources.verify_quote("README.md", "HALCYON")["status"] == "invalid_source"  # Textquelle ohne Zeile


def test_empty_quote_is_not_verification():
    assert sources.verify_quote("README.md:1", "")["ok"] is False
    assert check_source(BUNDLE, "README.md:1", "")["ok"] is False


def test_bundle_relative_paths_only():
    with pytest.raises(ValueError):
        sources.parse_source("/etc/passwd:1")
    assert check_source(BUNDLE, "meridian_case_bundle/case_bundle/README.md:1", "HALCYON")["ok"] is False


def test_crlf_lines_keep_original_numbering():
    lines = sources.raw_lines("card_feed_q4.csv")
    # Zeilen 1–2 sind Kommentare mit LF, danach CRLF – Zählung wie in der Originaldatei
    assert lines[0].startswith("# Firmenkarten")
    assert lines[2].startswith("txn_id,")
    assert not any(ln.endswith("\r") for ln in lines)
    assert sources.verify_quote("card_feed_q4.csv:3", "txn_id,timestamp_utc,cardholder")["ok"]


def test_pdf_page_and_scan_without_text_layer():
    assert sources.verify_quote("forensic_summary_bakalian.pdf:1", "Filesystem examination")["ok"]
    assert not sources.verify_quote("forensic_summary_bakalian.pdf:3", "Filesystem examination")["ok"]
    assert not check_source(BUNDLE, "witness_statement_okada_scan.pdf:1", "anything")["ok"]


def test_xlsx_row_and_photo():
    rows = sources.first_sheet_rows("parking_permits.xlsx")
    assert rows[1][1] == "Kennzeichen"  # Excel-Zeile 2 = Kopfzeile
    assert sources.verify_quote("parking_permits.xlsx:2", "Kennzeichen")["ok"]
    assert sources.verify_quote("evidence_photos/whiteboard_room_2F-3.jpg", "x")["status"] == "image"
    assert check_source(BUNDLE, "evidence_photos/whiteboard_room_2F-3.jpg", "x")["ok"] is False


def test_german_umlauts_utf8():
    lines = sources.raw_lines("garage_barrier_log.csv")
    assert "gemäss" in lines[1]
    assert sources.verify_quote("garage_barrier_log.csv:2", "Zeitangaben gemäss Systemuhr")["ok"]


# ------------------------------------------------------------------ Escaping mit synthetischem Paket

@pytest.fixture
def fake_bundle(tmp_path, monkeypatch):
    (tmp_path / "a.json").write_bytes(b'[\n {\n  "text": "he said \\"hi\\" \\u00e4",\n  "user": "U1"\n }\n]\n')
    (tmp_path / "b.csv").write_bytes('id;name;note\r\n1;"Müller; Hans";"a ""quoted"" word"\r\n'.encode("utf-8"))
    (tmp_path / "c.ics").write_bytes(b"BEGIN:VEVENT\r\nSUMMARY:Very long\r\n  continued\r\nEND:VEVENT\r\n")
    monkeypatch.setattr(SETTINGS, "bundle", tmp_path)
    sources.raw_lines.cache_clear()
    yield tmp_path
    sources.raw_lines.cache_clear()


def test_json_escapes_are_checked_against_raw_line(fake_bundle):
    # Der Export zitiert die Zeile, wie sie in der Datei steht – keine stille Dekodierung.
    assert sources.verify_quote("a.json:3", 'he said \\"hi\\"')["ok"]
    assert not sources.verify_quote("a.json:3", 'he said "hi" ä')["ok"]


def test_csv_quoting_and_semicolons(fake_bundle):
    import csv
    line = sources.raw_lines("b.csv")[1]
    row = next(csv.reader([line], delimiter=";"))
    assert row == ["1", "Müller; Hans", 'a "quoted" word']
    assert sources.verify_quote("b.csv:2", '"Müller; Hans"')["ok"]


def test_ics_continuation_lines_are_separate_raw_lines(fake_bundle):
    lines = sources.raw_lines("c.ics")
    assert lines[1] == "SUMMARY:Very long" and lines[2] == "  continued"
    assert sources.verify_quote("c.ics:2-3", "Very long\n  continued")["ok"]


# ------------------------------------------------------------------ Exportvalidator

def _valid_verdict():
    t = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    names = [s["name"] for s in t["suspects"]]
    ev = {"claim": "posted on a Sunday", "source": "slack_export/general/2025-10-12.json:5",
          "quote": "office is beautifully quiet on a sunday"}
    sus = [{"name": n, "verdict": "unresolved", "reasoning": "Test entry.", "evidence": []} for n in names]
    sus[0]["verdict"] = "culprit"
    sus[0]["evidence"] = [ev]
    sus[1]["verdict"] = "cleared"
    sus[1]["evidence"] = [ev]
    return {"team": "alibi-test", "culprit": names[0], "confidence": 0.4, "suspects": sus}


def test_validator_accepts_valid():
    rep = validate_verdict(_valid_verdict(), BUNDLE, TEMPLATE)
    assert rep["valid"], rep["errors"]


def test_validator_rejects_template_placeholders():
    t = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    rep = validate_verdict(t, BUNDLE, TEMPLATE)
    assert not rep["valid"]
    assert any("verdict" in e for e in rep["errors"])


@pytest.mark.parametrize("mutate,needle", [
    (lambda v: v.__setitem__("confidence", "65%"), "confidence"),
    (lambda v: v.__setitem__("confidence", 1.5), "confidence"),
    (lambda v: v.__setitem__("confidence", float("nan")), "confidence"),
    (lambda v: v["suspects"].pop(), "exactly once"),
    (lambda v: v["suspects"].append(copy.deepcopy(v["suspects"][2])), "exactly once"),
    (lambda v: v.__setitem__("culprit", v["suspects"][3]["name"]), "does not match"),
    (lambda v: v["suspects"][1].__setitem__("evidence", []), "cleared without"),
    (lambda v: v["suspects"][0]["evidence"][0].__setitem__("quote", "office is beautifully quiet on a monday"), "quote_not_found"),
    (lambda v: v["suspects"][0]["evidence"][0].__setitem__("source", "slack_export/general/2025-10-12.json:9999"), "line_out_of_range"),
    (lambda v: v.__setitem__("extra", 1), "Top level"),
    (lambda v: v["suspects"][2].__setitem__("verdict", "culprit | cleared | unresolved"), "verdict"),
])
def test_validator_rejects(mutate, needle):
    v = _valid_verdict()
    mutate(v)
    rep = validate_verdict(v, BUNDLE, TEMPLATE)
    assert not rep["valid"]
    assert any(needle in e for e in rep["errors"]), rep["errors"]
