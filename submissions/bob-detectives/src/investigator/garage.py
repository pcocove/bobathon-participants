"""Barrier-log helpers: where a number plate was at a given moment."""

from __future__ import annotations

from datetime import datetime

from .lexicon import GARAGE_ENTRY, GARAGE_EXIT
from .records import Event


def is_entry(e: Event) -> bool:
    return e.attrs.get("direction", "") in GARAGE_ENTRY


def is_exit(e: Event) -> bool:
    return e.attrs.get("direction", "") in GARAGE_EXIT


def plate_events(inv, plate: str, include_resolved: bool = True) -> list[Event]:
    out = []
    for e in inv.rec.by_kind("garage"):
        p = inv.resolved_plate(e) if include_resolved else e.attrs.get("plate")
        if p == plate:
            out.append(e)
    return sorted(out, key=lambda e: e.t)


def state_at(inv, plate: str, t: datetime, include_resolved: bool = True) -> tuple[str, Event | None]:
    """'inside' | 'outside' | 'unknown', plus the last event before t."""
    last = None
    for e in plate_events(inv, plate, include_resolved):
        if e.t <= t:
            last = e
        else:
            break
    if last is None:
        return "unknown", None
    return ("inside" if is_entry(last) else "outside"), last


def next_event(inv, plate: str, t: datetime, include_resolved: bool = True) -> Event | None:
    for e in plate_events(inv, plate, include_resolved):
        if e.t > t:
            return e
    return None


def history(inv, plate: str) -> dict:
    """Habits of a plate: typical entry/exit times and overnight stays."""
    evs = [e for e in plate_events(inv, plate, include_resolved=False) if not e.attrs.get("degraded")]
    entries = [e for e in evs if is_entry(e)]
    exits = [e for e in evs if is_exit(e)]
    overnight = 0
    for a, b in zip(evs, evs[1:]):
        if is_entry(a) and is_exit(b) and b.t.date() != a.t.date():
            overnight += 1

    def mins(e):
        return e.t.hour * 60 + e.t.minute

    def hm(m):
        return f"{m // 60:02d}:{m % 60:02d}"
    res = {"events": len(evs), "days": len({e.t.date() for e in entries}), "overnight_stays": overnight}
    if entries:
        em = sorted(mins(e) for e in entries)
        res.update(entry_earliest=hm(em[0]), entry_latest=hm(em[-1]), entry_median=hm(em[len(em) // 2]))
    if exits:
        xm = sorted(mins(e) for e in exits)
        res.update(exit_earliest=hm(xm[0]), exit_latest=hm(xm[-1]), exit_median=hm(xm[len(xm) // 2]))
    return res
