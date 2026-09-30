"""Evidence network: all units, people and Bob-detected entities with meaningful edges.

Deterministic layout (no random forces): people in the centre, file groups
(file/channel/calendar) on an outer ring, units per group as a spiral – relevant
units inside. Positions stay stable when filtering because the frontend only
changes visibility and highlighting.

Kanten:
- person link (unit → person): from IDs, aliases, plates, cardholder, calendar; the basis is kept
  (direct, mentioned, name_part, vehicle, cardholder, calendar …).
- Bob relations (typed): only with an exactly found quote; the evidence unit is kept.
- mention of an entity by a unit (Bob label).
"""
from __future__ import annotations

import hashlib
import math
import re

from .corpus import AN, REL_RANK, Corpus
from .i18n import MAP_FILE, tr
from .ingest import DOC_TYPES
from .store import read_json, write_json

GOLDEN = math.pi * (3 - math.sqrt(5))
FILE_ORDER = ["interview", "notebook", "pdf", "scan", "photo", "email", "jira", "helpdesk", "meeting", "diligence",
              "expense", "slack", "calendar", "card", "garage", "permit", "meta"]


def _h(s: str) -> float:
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def ent_key(etype: str, name: str) -> str:
    etype = (etype or "other").lower().strip()
    n = re.sub(r"\s+", " ", (name or "").strip())
    if etype in ("kennzeichen", "fahrzeug", "plate", "vehicle") and re.search(r"\d", n):
        n = re.sub(r"[^A-Z0-9]", "", n.upper())
    return f"{etype}:{n.lower()}"


def tag_of(lab: dict | None) -> str:
    if not lab:
        return "none"
    t = set(lab.get("tags") or [])
    if "belastend" in t:
        return "belastend"
    if t & {"entlastend", "alternative_erklaerung"}:
        return "entlastend"
    if t & {"offene_frage", "widerspruch", "uhrabweichung"}:
        return "offen"
    return "neutral"


def build_graph() -> dict:
    c = Corpus()
    reviewed = read_json(AN / "reviewed.json", {})
    nodes, edges = [], []
    # ---------------------------------------------------------------- Gruppen
    order = {k: i for i, k in enumerate(FILE_ORDER)}
    groups: dict[str, list[dict]] = {}
    for u in c.units:
        groups.setdefault(u["cluster"], []).append(u)
    gkeys = sorted(groups, key=lambda g: (order.get(groups[g][0]["doc_type"], 99), g))
    spacing = 11.0
    radii = {g: spacing * math.sqrt(len(groups[g])) + 26 for g in gkeys}
    gap = 70
    circ = sum(2 * radii[g] + gap for g in gkeys)
    R = max(1500, circ / (2 * math.pi))
    ang = -math.pi / 2
    clusters = []
    pos = {}
    for g in gkeys:
        r = radii[g]
        ang += (r + gap / 2) / R
        cx, cy = R * math.cos(ang), R * math.sin(ang)
        ang += (r + gap / 2) / R
        us = sorted(groups[g], key=lambda u: (-REL_RANK.get((c.labels.get(u["id"]) or {}).get("relevance"), 0),
                                              c.unit_time(u) or "", u["id"]))
        for k, u in enumerate(us):
            rr = spacing * math.sqrt(k + 0.5)
            a = k * GOLDEN
            x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
            lab = c.labels.get(u["id"])
            rel = REL_RANK.get((lab or {}).get("relevance"), 0)
            nodes.append({"id": "u:" + u["id"], "k": "unit", "l": u["title"][:70], "x": round(x, 1), "y": round(y, 1),
                          "d": u["doc_type"], "g": g, "r": rel, "t": tag_of(lab), "rv": 1 if u["id"] in reviewed else 0,
                          "tm": (c.unit_time(u) or "")[:16], "st": u["status"]})
            pos["u:" + u["id"]] = (x, y)
        clusters.append({"id": g, "label": g, "x": round(cx, 1), "y": round(cy, 1), "r": round(r, 1), "n": len(groups[g]),
                         "d": groups[g][0]["doc_type"], "dl": DOC_TYPES.get(groups[g][0]["doc_type"], "")})
    # ---------------------------------------------------------------- Personen
    sus = [p for p in c.persons if p["suspect"]]
    others = sorted([p for p in c.persons if not p["suspect"]], key=lambda p: -p.get("unit_count", 0))
    for i, p in enumerate(sus):
        a = -math.pi / 2 + 2 * math.pi * i / max(1, len(sus))
        pos["p:" + p["id"]] = (0.17 * R * math.cos(a), 0.17 * R * math.sin(a))
    for i, p in enumerate(others):
        a = -math.pi / 2 + math.pi / max(1, len(others)) + 2 * math.pi * i / max(1, len(others))
        r = (0.29 + (i % 2) * 0.035) * R
        pos["p:" + p["id"]] = (r * math.cos(a), r * math.sin(a))
    for p in c.persons:
        x, y = pos["p:" + p["id"]]
        nodes.append({"id": "p:" + p["id"], "k": "person", "l": p["name"], "x": round(x, 1), "y": round(y, 1),
                      "s": 1 if p["suspect"] else 0, "n": p.get("unit_count", 0), "org": p.get("kind") == "organisation"})
    # ---------------------------------------------------------------- Personenbezug
    basis_map = {}  # basis codes are passed through (direct, mentioned, name_part, vehicle, vehicle_uncertain, cardholder, calendar)
    for u in c.units:
        seen = set()
        for x in u["people"]:
            h = x.get("person")
            if not h or h in seen or ("p:" + h) not in pos:
                continue
            seen.add(h)
            edges.append({"s": "u:" + u["id"], "t": "p:" + h, "k": "bezug", "b": basis_map.get(x.get("basis"), x.get("basis") or "direct"),
                          "ro": (x.get("role") or "")[:24]})
        lab = c.labels.get(u["id"])
        for pp in (lab or {}).get("persons") or []:
            h = pp.get("id")
            if h and h not in seen and ("p:" + h) in pos:
                seen.add(h)
                edges.append({"s": "u:" + u["id"], "t": "p:" + h, "k": "bezug", "b": "bob", "ro": (pp.get("role") or "")[:24]})
    # ---------------------------------------------------------------- entities + Bob relations
    ents: dict[str, dict] = {}
    ent_links: dict[str, list] = {}

    def ent(etype, name):
        k = ent_key(etype, name)
        if k not in ents:
            ents[k] = {"id": "e:" + k, "k": "entity", "l": tr(name or "")[:60], "et": (etype or "other").lower()}
            ent_links[k] = []
        return k

    def ref(r: str, fallback_unit: str):
        if not isinstance(r, str) or not r:
            return None
        if r.startswith("person:"):
            h = c.person_handle(r[7:])
            return "p:" + h if h else None
        if r.startswith("entity:"):
            parts = r[7:].split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                k = ent(parts[0], parts[1])
                ent_links[k].append(fallback_unit)
                return "e:" + k
            return None
        if r.startswith("unit:"):
            uid = r[5:]
            return "u:" + uid if uid in c.by_id else None
        h = c.person_handle(r)
        return "p:" + h if h else None

    rel_count = 0
    for uid, lab in c.labels.items():
        for e in lab.get("entities") or []:
            k = ent(e.get("type"), e.get("name"))
            ent_links[k].append(uid)
            edges.append({"s": "u:" + uid, "t": "e:" + k, "k": "nennt"})
        for i, cl in enumerate(lab.get("claims") or []):
            rel, ev = cl.get("relation"), cl.get("evidence") or {}
            if not rel or not ev.get("ok"):
                continue
            s, t = ref(rel.get("from"), uid), ref(rel.get("to"), uid)
            if not s or not t or s == t:
                continue
            rel_count += 1
            edges.append({"s": s, "t": t, "k": "rel", "rt": rel.get("type"), "u": ev.get("unit") or uid, "src": ev.get("source"),
                          "q": (ev.get("quote") or "")[:220], "b": cl.get("basis"), "tx": tr(cl.get("text") or "")[:200],
                          "id": f"r:{uid}:{i}"})
    for k, e in ents.items():
        links = [pos["u:" + u] for u in ent_links[k] if "u:" + u in pos]
        if links:
            mx = sum(p[0] for p in links) / len(links)
            my = sum(p[1] for p in links) / len(links)
        else:
            a = _h(k) * 2 * math.pi
            mx, my = math.cos(a), math.sin(a)
        # own ring between people and file groups, towards the linked files
        ang_e = math.atan2(my, mx) + (_h(k + "j") - 0.5) * 0.06
        rad_e = (0.44 + 0.16 * _h(k + "f")) * R
        e["x"], e["y"] = round(rad_e * math.cos(ang_e), 1), round(rad_e * math.sin(ang_e), 1)
        e["n"] = len(ent_links[k])
        nodes.append(e)
    ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["s"] in ids and e["t"] in ids]
    g = {"nodes": nodes, "edges": edges, "clusters": clusters,
         "stats": {"nodes": len(nodes), "edges": len(edges), "relations": rel_count, "entities": len(ents),
                   "labeled": len(c.labels), "reviewed": len(reviewed)},
         "doc_types": DOC_TYPES}
    write_json(AN.parent / "graph.json", g, indent=None)
    return g


def graph_cached() -> dict:
    """Rebuild when labels/units are newer than the graph."""
    gp = AN.parent / "graph.json"
    deps = [AN.parent / "units.json", AN / "labels.json", AN / "reviewed.json", MAP_FILE]
    if gp.exists() and all(not d.exists() or d.stat().st_mtime <= gp.stat().st_mtime for d in deps):
        return read_json(gp)
    return build_graph()
