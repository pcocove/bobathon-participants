"""Ingest, person linking, time normalisation, evidence resolution and graph integrity."""
import json
from datetime import datetime

import pytest

from alibi import sources
from alibi.config import SETTINGS, template_names
from alibi.corpus import Corpus
from alibi.ingest import run_ingest
from alibi.store import read_json


@pytest.fixture(scope="module")
def corpus():
    if not (SETTINGS.state_dir / "units.json").exists():
        run_ingest()
    return Corpus()


def test_every_file_in_inventory():
    inv = read_json(SETTINGS.state_dir / "inventory.json")
    on_disk = {p.relative_to(SETTINGS.bundle).as_posix() for p in SETTINGS.bundle.rglob("*") if p.is_file() and not p.name.startswith(".")}
    assert {f["file"] for f in inv["files"]} == on_disk
    assert not [f for f in inv["files"] if f["status"] == "failed"]


def test_all_eight_suspects_registered(corpus):
    names = template_names()
    assert len(names) == 8
    for n in names:
        h = corpus.person_handle(n)
        assert h in corpus.person_by_id and corpus.person_by_id[h]["suspect"]


def test_slack_user_id_mapping(corpus):
    u = corpus.by_id["SL-general-2025-10-12-L2"]
    uid = u["fields"]["user"]
    users = json.loads((SETTINGS.bundle / "slack_export/users.json").read_text(encoding="utf-8"))
    handle = next(x["name"] for x in users if x["id"] == uid)
    assert any(p["person"] == handle and p["basis"] == "direct" for p in u["people"])
    # Personenbezug entsteht aus der ID, nicht aus dem ausgeschriebenen Namen im Text
    assert handle.split(".")[1] not in u["text"].lower()


def test_unit_locations_within_files(corpus):
    for u in corpus.units:
        loc = u["loc"]
        if loc["type"] == "lines":
            n = len(sources.raw_lines(u["file"]))
            assert 1 <= loc["start"] <= loc["end"] <= n, u["id"]
            assert u["raw"].split("\n")[0] == sources.raw_lines(u["file"])[loc["start"] - 1]


def test_unit_ids_unique(corpus):
    ids = [u["id"] for u in corpus.units]
    assert len(ids) == len(set(ids))


def _t(u):
    return u["times"][0]


def test_time_normalisation_no_double_correction(corpus):
    # Slack: Unix-UTC → Europe/Zurich; im Oktober genau +2 h, nicht +4 h
    u = next(x for x in corpus.units if x["doc_type"] == "slack" and x["file"].endswith("2025-10-12.json"))
    t = _t(u)
    utc = datetime.fromisoformat(t["utc"].replace("Z", "+00:00"))
    loc = datetime.fromisoformat(t["local"])
    assert loc.utcoffset().total_seconds() == 7200 and (loc - utc).total_seconds() == 0
    # Kartenfeed: Spalte ist UTC → lokal +2h im Oktober, Winter +1h
    c = next(x for x in corpus.units if x["doc_type"] == "card" and x["fields"].get("timestamp_utc", "").startswith("2025-10-1"))
    tt = _t(c)
    assert tt["utc"] == c["fields"]["timestamp_utc"]
    assert datetime.fromisoformat(tt["local"]).utcoffset().total_seconds() == 7200
    # Garagenlog: lokale Systemuhr, NICHT korrigiert
    g = next(x for x in corpus.units if x["doc_type"] == "garage" and x["times"])
    tg = _t(g)
    assert tg.get("assumed_zone") is True
    assert tg["local"][11:19] == g["fields"]["Uhrzeit"]


def test_ics_utc_and_tzid_equivalent(corpus):
    evs = [u for u in corpus.units if u["doc_type"] == "calendar"]
    z = next(u for u in evs if any("iCalendar UTC" in t["basis"] for t in u["times"]))
    tz = next(u for u in evs if any("TZID" in t["basis"] for t in u["times"]))
    for u in (z, tz):
        loc = datetime.fromisoformat(u["times"][0]["local"])
        assert loc.tzinfo is not None


def test_resolve_cleans_display_prefix_and_rejects_fabrication(corpus):
    u = next(x for x in corpus.units if x["doc_type"] == "garage" and x["loc"]["start"] > 10)
    n = u["loc"]["start"]
    line = sources.raw_lines(u["file"])[n - 1]
    r = corpus.resolve({"unit": u["id"], "quote": f"L{n}: {line} ⇒ someone"})
    assert r["ok"] and r["source"] == f"{u['file']}:{n}" and r["quote"] == line
    fake = corpus.resolve({"unit": u["id"], "quote": line.replace(";", ",") + "X"})
    assert not fake["ok"]


def test_ellipsis_keeps_only_exact_fragment(corpus):
    u = corpus.by_id["IV07-L1"]
    lines = sources.raw_lines(u["file"])
    a, b = lines[1][:30], lines[2][:25]
    r = corpus.resolve({"unit": "IV07-L1", "quote": f"{a} ... {b}xyz"})
    assert r["ok"] and r["match"] == "fragment" and r["quote"] in lines[1]


def test_unverified_claims_do_not_become_graph_relations():
    g = read_json(SETTINGS.state_dir / "graph.json")
    if not g:
        pytest.skip("Graph noch nicht gebaut")
    ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["s"] in ids and e["t"] in ids
        if e["k"] == "rel":
            assert e["src"] and e["q"]
            assert sources.verify_quote(e["src"], e["q"])["ok"]


def test_search_expands_aliases_and_plates(corpus):
    # Slack-ID und Kennzeichen werden auf dieselbe Person erweitert – nicht nur der ausgeschriebene Name
    uid_hits = corpus.search("U0707H", limit=50)
    assert uid_hits and all("kurt.steiner" in corpus._search_text[u] for u in uid_hits)
    plate = next(a["value"] for a in corpus.person_by_id["kurt.steiner"]["aliases"] if a["kind"] == "plate")
    hits = corpus.search(plate, limit=20)
    assert any(corpus.by_id[h]["doc_type"] == "garage" for h in hits)


def test_search_ignores_terms_without_hits(corpus):
    # Deutsche Suchwörter ohne Treffer in englischen Akten blockieren die Suche nicht
    assert corpus.search("kurt.steiner Stadtclub Quittung Wochenendbeleg", limit=5)
