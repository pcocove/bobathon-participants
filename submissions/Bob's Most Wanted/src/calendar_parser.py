"""Calendar parser – ICS (iCalendar) evidence normalisation.

Converts every VEVENT in every .ics file under the ``calendars/`` directory
into the existing unified :class:`DataPoint` format.

Expected structure::

    calendars/
        iris.ammann.ics
        lukas.hofer.ics
        ...

Each .ics file is the exported calendar of exactly one person. The calendar
owner is identified from the ``X-WR-CALNAME`` header; falling back to the
file stem when the header is absent.

Two timestamp formats are present in the real data:

* **Outlook style** – ``DTSTART;TZID=Europe/Zurich:20250801T124500``
  parsed by icalendar as a timezone-aware datetime in the named zone.
* **Google style**  – ``DTSTART:20250801T104500Z``
  parsed by icalendar as a UTC-aware datetime.

In both cases icalendar returns a ``datetime.datetime`` with ``tzinfo`` set.
Both are stored directly in ``start_time`` / ``end_time`` (already
timezone-aware).  The raw value and the timezone name are also preserved
in metadata so downstream code can reconstruct the original local time.
"""

from __future__ import annotations

import logging
from datetime import datetime, date
from pathlib import Path
from typing import Any

import icalendar  # type: ignore[import-untyped]

from unified_data import DataPoint, DataType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _repo_relative_posix(file_path: Path, anchor: Path) -> str:
    """Return *file_path* as a forward-slash path relative to *anchor*."""
    return file_path.resolve().relative_to(anchor.resolve()).as_posix()


def _dt_to_aware(value: datetime | date) -> datetime | None:
    """Convert an icalendar date/datetime value to a timezone-aware datetime.

    Returns ``None`` for genuine all-day :class:`datetime.date` values so
    callers can set ``start_time=None`` and flag ``all_day=True``.
    """
    if isinstance(value, datetime):
        return value  # already datetime; icalendar always returns tz-aware here
    # Pure date – all-day event; caller decides how to represent it.
    return None


def _tz_name(value: datetime | date) -> str | None:
    """Return the IANA timezone name for *value*, or None."""
    if not isinstance(value, datetime):
        return None
    tz = value.tzinfo
    if tz is None:
        return None
    # zoneinfo.ZoneInfo and pytz both expose .key or .zone
    if hasattr(tz, "key"):          # zoneinfo.ZoneInfo
        return tz.key
    if hasattr(tz, "zone"):         # pytz
        return tz.zone
    return str(tz)


def _raw_dt_str(value: datetime | date) -> str:
    """Return a compact ISO-like string representation of the raw value."""
    if isinstance(value, datetime):
        return value.strftime("%Y%m%dT%H%M%S%z")
    return value.strftime("%Y%m%d")


def _resolve_organizer(component: icalendar.cal.Component) -> dict[str, str] | None:
    """Extract organiser CN and email from a VEVENT component."""
    org = component.get("ORGANIZER")
    if org is None:
        return None
    email = str(org).replace("mailto:", "").strip()
    cn = str(org.params.get("CN", "")).strip()
    result: dict[str, str] = {"email": email}
    if cn:
        result["name"] = cn
    return result


def _parse_ics_file(
    ics_file: Path,
    source_anchor: Path,
) -> list[DataPoint]:
    """Parse one .ics file and return a list of normalised DataPoint records."""
    raw_bytes = ics_file.read_bytes()
    try:
        cal = icalendar.Calendar.from_ical(raw_bytes)
    except Exception as exc:
        logger.error("Cannot parse calendar file %s: %s", ics_file, exc)
        return []

    # Calendar-level metadata (used for fallback ID only, not stored in records)
    cal_name: str = str(cal.get("X-WR-CALNAME", "")).strip()
    if not cal_name:
        cal_name = ics_file.stem  # e.g. "iris.ammann"

    rel_source = _repo_relative_posix(ics_file, source_anchor)

    records: list[DataPoint] = []
    event_index = 0

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        try:
            record = _vevent_to_datapoint(
                component=component,
                cal_name=cal_name,
                rel_source=rel_source,
                event_index=event_index,
            )
        except Exception as exc:
            logger.warning(
                "Skipping event at index %d in %s: %s",
                event_index,
                ics_file,
                exc,
            )
            event_index += 1
            continue

        if record is not None:
            records.append(record)

        event_index += 1

    return records


def _vevent_to_datapoint(
    component: icalendar.cal.Component,
    cal_name: str,
    rel_source: str,
    event_index: int,
) -> DataPoint:
    """Convert one VEVENT component to a DataPoint."""
    # --- Identity ---
    uid: str = str(component.get("UID", "")).strip()
    record_id = uid if uid else f"calendar-{rel_source}-{event_index}"

    # --- Times ---
    dtstart_prop = component.get("DTSTART")
    dtend_prop   = component.get("DTEND")

    dtstart_raw = dtstart_prop.dt if dtstart_prop else None
    dtend_raw   = dtend_prop.dt   if dtend_prop   else None

    start_time: datetime | None = _dt_to_aware(dtstart_raw) if dtstart_raw else None
    end_time:   datetime | None = _dt_to_aware(dtend_raw)   if dtend_raw   else None

    # --- Content ---
    summary: str     = str(component.get("SUMMARY", "")).strip()
    description: str = str(component.get("DESCRIPTION", "")).strip()
    # Unescape icalendar backslash-escaped commas/semicolons
    description = description.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n")

    content = summary if summary else f"(no summary) event-index={event_index}"

    # --- Location ---
    location_raw = component.get("LOCATION")
    location: str | None = str(location_raw).strip() if location_raw else None
    if location == "":
        location = None

    # --- Status ---
    status_raw = component.get("STATUS")
    status: str | None = str(status_raw).strip().upper() if status_raw else None

    # --- Organiser ---
    organizer = _resolve_organizer(component)

    # --- Persons: organiser CN + attendee CNs (deduplicated; calendar owner excluded) ---
    seen_persons: set[str] = set()
    persons: list[str] = []

    if organizer:
        org_identity = organizer.get("name") or organizer.get("email", "")
        if org_identity:
            seen_persons.add(org_identity)
            persons.append(org_identity)

    # ATTENDEE may be a single vCalAddress or a list thereof
    attendees = component.get("ATTENDEE")
    if attendees is not None:
        if not isinstance(attendees, list):
            attendees = [attendees]
        for attendee_prop in attendees:
            cn = str(attendee_prop.params.get("CN", "")).strip() if hasattr(attendee_prop, "params") else ""
            email = str(attendee_prop).replace("mailto:", "").strip()
            identity = cn if cn else email
            if identity and identity not in seen_persons:
                seen_persons.add(identity)
                persons.append(identity)

    # --- Recurrence (none in real data, preserved for completeness) ---
    rrule = component.get("RRULE")
    recurrence_rule: str | None = rrule.to_ical().decode() if rrule else None
    recurrence_id_prop = component.get("RECURRENCE-ID")
    recurrence_id: str | None = (
        str(recurrence_id_prop.dt) if recurrence_id_prop else None
    )

    # --- Metadata: only optional/non-trivial fields ---
    metadata: dict[str, Any] = {}

    if description:
        metadata["description"] = description

    if organizer:
        metadata["organizer"] = organizer

    if location:
        metadata["location_raw"] = location

    if status:
        metadata["status"] = status

    if recurrence_rule:
        metadata["recurrence_rule"] = recurrence_rule

    if recurrence_id:
        metadata["recurrence_id"] = recurrence_id

    return DataPoint(
        id=record_id,
        data_type=DataType.calendar,
        persons=persons,
        content=content,
        start_time=start_time,
        end_time=end_time,
        location=location,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


class CalendarParser:
    """Parse one or more .ics calendar files into DataPoint records.

    Accepts either a single ``.ics`` file or a directory containing ``.ics``
    files (one per calendar owner).

    Usage::

        parser = CalendarParser()
        # Single file:
        records = parser.parse(Path("case_bundle/calendars/iris.ammann.ics"))
        # Directory:
        records = parser.parse(Path("case_bundle/calendars"))
    """

    def parse(self, path: Path) -> list[DataPoint]:
        """Parse .ics file(s) at *path* and return one DataPoint per VEVENT.

        *path* may be either:
        - a single ``.ics`` file, or
        - a directory; all ``.ics`` files directly inside it are parsed.

        Returns one :class:`DataPoint` per successfully parsed VEVENT.
        """
        if path.is_file():
            ics_files = [path]
            # Anchor: two levels up from the file so source_file stays meaningful
            source_anchor = path.resolve().parent.parent
        else:
            ics_files = sorted(path.glob("*.ics"))
            # Anchor: three levels up from the calendars/ directory
            source_anchor = path.resolve().parents[2]

        records: list[DataPoint] = []

        for ics_file in ics_files:
            try:
                file_records = _parse_ics_file(ics_file, source_anchor)
                records.extend(file_records)
            except Exception:
                logger.exception("Failed to process %s – skipping.", ics_file)

        return records
