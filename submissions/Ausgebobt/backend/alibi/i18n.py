"""English display layer for stored analysis text.

The stored Bob outputs of the first runs were written in German. Instead of re-running
the analysis (which would change results and cost credits), Bob translated the free-text
fields once (stage "translate", cached under state/bob/). This module applies that
translation map when data is served. Verbatim quotes, sources, IDs and enum codes are
never translated; the German originals stay untouched in state/analysis/.
"""
from __future__ import annotations

from typing import Callable, Iterator

from .config import SETTINGS
from .store import read_json

MAP_FILE = SETTINGS.state_dir / "analysis" / "translations_en.json"

# free-text keys written by Bob (or by ALIBI around Bob's text)
TEXT_KEYS = {
    "summary", "summary_de", "text", "reasoning_de", "confidence_reason", "why", "argument", "reason",
    "explanation", "suspicion", "what", "how", "when_note", "title", "weakness", "attack_step", "control",
    "effect", "limits", "priority_reason", "window_note", "how_known_legitimately", "note", "weights_basis",
    "description", "meaning", "wissen", "zugang", "zeit", "claim_de", "role", "revised_by_crosscheck",
    "claim", "check_text",
}
LIST_KEYS = {"open_questions", "uncertainties", "merge_notes"}
# keys inside resolved evidence that may be translated; everything else there is verbatim/technical
EVIDENCE_TEXT_KEYS = {"claim_de", "text"}
ENUM_BASIS = {"direkt", "abgeleitet", "moeglich", "ungeprueft"}
SKIP_KEYS = {"quote", "quote_given", "source", "unit", "detail", "status", "query", "search_terms", "transcript_lines",
             "id", "person", "who", "leading", "verdict", "conclusion", "category", "priority", "kind", "type", "match",
             "claim_en", "reasoning_en", "summary_en", "check", "provenance", "cleanup", "call", "package", "results"}


def _is_evidence(d: dict) -> bool:
    return "unit" in d and ("quote_given" in d or "quote" in d)


def walk_text(obj, fn: Callable[[str], str], key: str | None = None, entity_names: bool = False):
    """Returns a copy of obj with fn applied to every translatable free-text string."""
    if isinstance(obj, dict):
        ev = _is_evidence(obj)
        out = {}
        for k, v in obj.items():
            if isinstance(v, str):
                if ev:
                    out[k] = fn(v) if k in EVIDENCE_TEXT_KEYS else v
                elif (k in TEXT_KEYS or (k == "basis" and v not in ENUM_BASIS) or (entity_names and k == "name")
                      or (key == "time_sources" and k == "source")):
                    out[k] = fn(v)
                else:
                    out[k] = v
            elif k in LIST_KEYS and isinstance(v, list):
                out[k] = [fn(x) if isinstance(x, str) else walk_text(x, fn, k, entity_names) for x in v]
            elif k in SKIP_KEYS:
                out[k] = v
            else:
                out[k] = walk_text(v, fn, k, entity_names=(k == "entities") or entity_names and k != "persons")
        return out
    if isinstance(obj, list):
        return [walk_text(x, fn, key, entity_names) for x in obj]
    return obj


def collect(obj, entity_names: bool = False) -> Iterator[str]:
    found: list[str] = []
    walk_text(obj, lambda s: (found.append(s), s)[1], entity_names=entity_names)
    return iter(found)


_cache: dict = {}


def tmap() -> dict[str, str]:
    try:
        stamp = MAP_FILE.stat().st_mtime
    except FileNotFoundError:
        return {}
    if _cache.get("stamp") != stamp:
        _cache["map"] = (read_json(MAP_FILE, {}) or {}).get("map", {})
        _cache["stamp"] = stamp
    return _cache["map"]


def tr(s: str) -> str:
    return tmap().get(s, s)


def tr_tree(obj, entity_names: bool = False):
    m = tmap()
    if not m:
        return obj
    return walk_text(obj, lambda s: m.get(s, s), entity_names=entity_names)
