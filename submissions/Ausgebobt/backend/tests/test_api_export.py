"""API, export draft, read-only mode and Bob outage – without real Bob calls."""
import json

import pytest
from fastapi.testclient import TestClient

from alibi import api, bob_adapter
from alibi.config import SETTINGS


@pytest.fixture(scope="module")
def client():
    api.bob_status = lambda force=False: {"installed": True, "version": "test", "connected": False, "detail": "Test", "interface": "test"}
    return TestClient(api.app)


def test_status_and_inventory(client):
    s = client.get("/api/status").json()
    assert s["team"] == SETTINGS.team and "ledger" in s
    inv = client.get("/api/inventory").json()
    cov = inv["coverage"]
    assert cov["files_discovered"] == len(inv["files"]) > 0
    # „Alle Daten verarbeitet“ nur, wenn wirklich jede Einheit geprüft ist
    assert cov["all_processed"] == (cov["units_reviewed"] == cov["units_total"] and cov["files_failed"] == 0)


def test_graph_unit_source_search(client):
    g = client.get("/api/graph").json()
    assert g["nodes"] and "clusters" in g
    u = client.get("/api/unit/IV07-L1").json()
    assert u["file"].startswith("interviews/") and u["lines"][0]["n"] >= 1
    src = client.get("/api/source", params={"ref": "slack_export/general/2025-10-12.json:5"}).json()
    assert any(l["in"] and "beautifully quiet" in l["text"] for l in src["lines"])
    assert client.get("/api/source", params={"ref": "../../etc/passwd:1"}).status_code == 400
    s = client.get("/api/search", params={"q": "U0707H"}).json()
    assert any(p["id"] == "kurt.steiner" for p in s["persons"])


def test_export_only_when_valid(client):
    d = client.get("/api/export").json()
    if d.get("draft") is None:
        assert d["report"]["valid"] is False
        assert client.get("/api/export/download").status_code == 409
    else:
        assert d["status"] == "DRAFT"
        assert set(d["draft"]) == {"team", "culprit", "confidence", "suspects"}
        assert len(d["draft"]["suspects"]) == 8
        if not d["report"]["valid"]:
            assert client.get("/api/export/download").status_code == 409


def test_bob_unavailable_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(SETTINGS, "bob_command", ["bob-does-not-exist-xyz"])
    # Testaufträge nicht ins echte Protokoll schreiben
    monkeypatch.setattr(bob_adapter, "BOB_DIR", tmp_path)
    monkeypatch.setattr(bob_adapter, "CALLS_DIR", tmp_path / "calls")
    monkeypatch.setattr(bob_adapter, "PROMPTS_DIR", tmp_path / "prompts")
    bob_adapter._status_cache.clear()
    st = bob_adapter.bob_status(force=True)
    assert st["installed"] is False and st["connected"] is False
    assert "not" in st["detail"]
    rec = bob_adapter.run_bob("test", "Ausfalltest", "prompt-" + str(id(st)), lambda p: [], reuse=False)
    assert rec["status"] == "unavailable"
    bob_adapter._status_cache.clear()


def test_extract_json_from_envelope():
    txt = 'Hier ist das Ergebnis:\n```json\n{"a": 1, "b": [1,2]}\n```\nfertig'
    assert bob_adapter.extract_json(txt) == {"a": 1, "b": [1, 2]}
    with pytest.raises(ValueError):
        bob_adapter.extract_json("kein json")


def test_readonly_share_mode_blocks_writes(client, monkeypatch):
    monkeypatch.setattr(SETTINGS, "readonly", True)
    assert client.get("/api/status").json()["readonly"] is True
    for url in ("/api/analysis/run", "/api/export/write", "/api/ingest", "/api/bob/check", "/api/analysis/cancel"):
        r = client.post(url, json={})
        assert r.status_code == 403, url
    assert client.get("/api/inventory").status_code == 200
