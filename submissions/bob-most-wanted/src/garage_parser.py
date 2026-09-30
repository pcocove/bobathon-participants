"""Garage barrier log and parking permit parsers.

Source data
-----------

**Parking permits** (``parking_permits.xlsx``)
    Excel workbook from Parkhaus Stickerei AG. Sheet "Bewilligungen" contains
    one permit per row with columns:

    =============  ============================================================
    Bewilligung    permit ID, e.g. ``PB-2400``
    Kennzeichen    license plate, e.g. ``SG 482 117``
    Inhaber/in     registered holder name
    Firma          company
    Fahrzeug       vehicle description
    Farbe          vehicle colour
    Ebene          assigned floor level (integer)
    gültig bis     validity end date string
    =============  ============================================================

**Garage barrier log** (``garage_barrier_log.csv``)
    Semicolon-separated export from the barrier recognition system.
    Two comment lines precede the header::

        # Parkhaus Stickerei AG · Schrankenanlage · Export Kennzeichenerkennung
        # Zeitangaben gemäss Systemuhr der Anlage. Erkennung = Konfidenz in %.
        Datum;Uhrzeit;Kennzeichen;Richtung;Spur;Erkennung

    Columns:

    ===========  ===============================================================
    Datum        Date, DD.MM.YYYY
    Uhrzeit      Time, HH:MM:SS — see clock-offset note below
    Kennzeichen  License plate as recognised by the camera
    Richtung     Direction: ``Einfahrt`` (entry) or ``Ausfahrt`` (exit)
    Spur         Lane/barrier: ``E1`` (entry lane) or ``A1`` (exit lane)
    Erkennung    **Plate-recognition confidence in percent** (0–100). Verified
                 from the comment line "Erkennung = Konfidenz der
                 Kennzeichenerkennung in %".
    ===========  ===============================================================

Clock offset
~~~~~~~~~~~~
FAC-352 (helpdesk) documents that the barrier system clock was left on winter
time (CET = UTC+1) after the 30 March 2025 clock change and was not corrected
until 26 October 2025 (the next clock change).  The offset check was confirmed
by dessie.moran on 27 October 2025.

Affected period: 30.03.2025 00:00 local clock time → 26.10.2025 (inclusive).
During this window the system reported CET (UTC+1) while the actual wall-clock
time in St. Gallen was CEST (UTC+2).  A correction of +1 hour is applied when
converting these timestamps.

The raw time string and the applied timezone/correction are both preserved in
metadata so the correction can be verified or reversed.

Entity resolution
~~~~~~~~~~~~~~~~~
The only reliable lookup key linking garage events to persons is the license
plate.  The parking permit data maps one plate to exactly one registered holder
in this dataset (no ambiguous or conflicting cases were observed).  The
resolution method is therefore ``license_plate_to_parking_permit``.

Unrecognised plates (e.g. visitors, partial reads such as ``SG 482 1?7``) are
kept as ``unresolved`` records with ``persons=[]``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import openpyxl  # type: ignore[import-untyped]

from unified_data import DataPoint, DataType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Europe/Zurich offset during normal time (CET = UTC+1) and summer time (CEST = UTC+2)
_CET = timezone(timedelta(hours=1), "CET")
_CEST = timezone(timedelta(hours=2), "CEST")

# The barrier clock stayed on CET after the 30 March spring-forward and was
# corrected at the 26 October autumn clock change.
# Records with a system timestamp inside this window that appear to be CET
# are actually 1 hour off: we add 1 hour to obtain the correct local wall time.
_CLOCK_OFFSET_START = datetime(2025, 3, 30, 0, 0, tzinfo=_CET)
_CLOCK_OFFSET_END   = datetime(2025, 10, 26, 3, 0, tzinfo=_CET)   # inclusive: clocks change here

_DIRECTION_MAP = {
    "einfahrt": "entry",
    "ausfahrt": "exit",
}

# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------


def _repo_relative_posix(file_path: Path, anchor: Path) -> str:
    """Return *file_path* as a forward-slash path relative to *anchor*."""
    return file_path.resolve().relative_to(anchor.resolve()).as_posix()


def _normalize_plate(plate: str) -> str:
    """Return an uppercased, whitespace-collapsed plate string for lookup.

    Preserves letter/digit content; removes separators for comparison only.
    Example: ``'sg 528 171'`` → ``'SG528171'``.
    """
    return re.sub(r"[\s\-\./]+", "", plate.strip().upper())


# ---------------------------------------------------------------------------
# Part 1 – Parking permit parser
# ---------------------------------------------------------------------------

# A permit record as extracted from the spreadsheet (dict keyed by field name)
_PermitRecord = dict[str, Any]


def _load_permits_raw(xlsx_path: Path) -> list[_PermitRecord]:
    """Load all permit rows from the Excel workbook as plain dicts."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Bewilligungen"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Row 0 is the title banner; row 1 is the header
    headers = rows[1]
    permits: list[_PermitRecord] = []
    for row in rows[2:]:
        if not any(row):
            continue  # skip empty rows
        record: _PermitRecord = {}
        for header, value in zip(headers, row):
            if header is not None:
                record[str(header).strip()] = value
        permits.append(record)
    return permits


def _permit_to_datapoint(
    record: _PermitRecord,
    record_index: int,
    rel_source: str,
) -> DataPoint:
    """Convert one permit row dict to a DataPoint."""
    permit_id: str  = str(record.get("Bewilligung", "")).strip()
    plate_raw: str  = str(record.get("Kennzeichen", "")).strip()
    holder: str     = str(record.get("Inhaber/in", "")).strip()
    company: str    = str(record.get("Firma", "")).strip()
    vehicle: str    = str(record.get("Fahrzeug", "")).strip()
    colour: str     = str(record.get("Farbe", "")).strip()
    level           = record.get("Ebene")
    valid_until: str = str(record.get("g\u00fcltig bis", record.get("gultig bis", ""))).strip()

    plate_norm = _normalize_plate(plate_raw) if plate_raw else ""

    record_id = f"parking-permit-{permit_id}" if permit_id else f"parking-permit-row-{record_index}"

    persons = [holder] if holder else []

    content_parts = [f"Parking permit {permit_id}"]
    if holder:
        content_parts.append(f"Holder: {holder}")
    if company:
        content_parts.append(f"Company: {company}")
    if vehicle:
        content_parts.append(f"Vehicle: {vehicle} ({colour})")
    if plate_raw:
        content_parts.append(f"Plate: {plate_raw}")
    content = " · ".join(content_parts)

    metadata: dict[str, Any] = {
        "permit_id": permit_id,
        "license_plate_raw": plate_raw,
        "license_plate_normalized": plate_norm,
        "holder": holder,
        "company": company,
        "vehicle": vehicle,
        "colour": colour,
        "valid_until": valid_until,
        "source_file": rel_source,
        "record_index": record_index,
    }
    if level is not None:
        metadata["level"] = level

    return DataPoint(
        id=record_id,
        data_type=DataType.parking_permit,
        persons=persons,
        content=content,
        start_time=None,
        end_time=None,
        location=None,
        metadata=metadata,
    )


class ParkingPermitParser:
    """Parse the parking permits Excel workbook into DataPoint records.

    Usage::

        parser = ParkingPermitParser()
        records = parser.parse(Path("case_bundle/parking_permits.xlsx"))
    """

    def parse(self, path: Path) -> list[DataPoint]:
        """Parse *path* and return one DataPoint per permit record."""
        source_anchor = path.resolve().parents[2]  # bobathon-participants/
        rel_source = _repo_relative_posix(path, source_anchor)

        raw_permits = _load_permits_raw(path)
        records: list[DataPoint] = []
        for idx, permit in enumerate(raw_permits):
            try:
                records.append(_permit_to_datapoint(permit, idx, rel_source))
            except Exception:
                logger.exception("Failed to parse permit at row %d – skipping.", idx)
        return records

    def build_plate_index(self, path: Path) -> dict[str, _PermitRecord]:
        """Build a normalized-plate → permit-record mapping for lookup.

        The mapping is keyed by :func:`_normalize_plate` of the plate string.
        If two permits share the same normalized plate the second wins (logged
        as a warning), but in this dataset plates are unique.
        """
        raw_permits = _load_permits_raw(path)
        index: dict[str, _PermitRecord] = {}
        for permit in raw_permits:
            plate_raw = str(permit.get("Kennzeichen", "")).strip()
            if not plate_raw:
                continue
            norm = _normalize_plate(plate_raw)
            if norm in index:
                existing = index[norm].get("Bewilligung", "?")
                new      = permit.get("Bewilligung", "?")
                logger.warning(
                    "Duplicate normalized plate %r: permit %s vs %s – keeping %s.",
                    norm, existing, new, new,
                )
            index[norm] = permit
        return index


# ---------------------------------------------------------------------------
# Part 2 – Garage barrier parser
# ---------------------------------------------------------------------------


def _parse_barrier_timestamp(
    date_str: str,
    time_str: str,
) -> tuple[datetime, str, bool]:
    """Parse a barrier-log date+time into a timezone-aware UTC datetime.

    Returns ``(utc_dt, timezone_note, clock_was_offset)`` where:

    * ``utc_dt``          — UTC-normalised datetime
    * ``timezone_note``   — human-readable note about the applied timezone
    * ``clock_was_offset`` — True if the +1 h correction was applied
    """
    # Parse naive datetime first
    naive = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M:%S")

    # The system clock was stuck at CET (UTC+1) after 30 March 2025.
    # Treat the raw value as CET and check whether the correction applies.
    naive_as_cet = naive.replace(tzinfo=_CET)

    if _CLOCK_OFFSET_START <= naive_as_cet < _CLOCK_OFFSET_END:
        # Clock was 1 h behind CEST.  The actual wall-clock time was 1 h later,
        # i.e. UTC is naive+1h (CET) = naive+0h relative to UTC+1 → add 1h.
        utc_dt = (naive + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        note = "System clock was on CET (UTC+1) during CEST period; +1 h correction applied (FAC-352)"
        corrected = True
    else:
        # Clock was correct CET / UTC+1.
        utc_dt = naive.replace(tzinfo=_CET).astimezone(timezone.utc)
        note = "Europe/Zurich CET (UTC+1)"
        corrected = False

    return utc_dt, note, corrected


def _resolve_person(
    plate_norm: str,
    plate_index: dict[str, _PermitRecord],
) -> tuple[list[str], dict[str, Any]]:
    """Look up a normalized plate in the permit index.

    Returns ``(persons, resolution_metadata)`` suitable for inclusion in a
    garage DataPoint.
    """
    if not plate_norm:
        return [], {
            "identity_resolution": "unresolved",
            "resolution_note": "empty or unreadable plate",
        }

    match = plate_index.get(plate_norm)
    if match is None:
        return [], {
            "identity_resolution": "unresolved",
            "resolution_note": "plate not found in parking permit registry",
        }

    holder: str = str(match.get("Inhaber/in", "")).strip()
    permit_id: str = str(match.get("Bewilligung", "")).strip()

    if not holder:
        return [], {
            "identity_resolution": "unresolved",
            "resolution_note": "permit found but no holder name",
            "matched_permit_id": permit_id,
        }

    return [holder], {
        "identity_resolution": "resolved",
        "resolution_method": "license_plate_to_parking_permit",
        "resolved_person": holder,
        "matched_permit_id": permit_id,
    }


def _parse_garage_row(
    parts: list[str],
    record_index: int,
    rel_source: str,
    plate_index: dict[str, _PermitRecord],
) -> DataPoint:
    """Convert one CSV row (already split) to a garage DataPoint."""
    date_str   = parts[0].strip()
    time_str   = parts[1].strip()
    plate_raw  = parts[2].strip()
    direction  = parts[3].strip()
    barrier    = parts[4].strip()
    confidence = parts[5].strip()

    # Normalize plate for lookup
    plate_norm = _normalize_plate(plate_raw) if plate_raw else ""

    # Timestamp
    utc_dt, tz_note, clock_corrected = _parse_barrier_timestamp(date_str, time_str)

    # Normalize direction
    direction_norm = _DIRECTION_MAP.get(direction.lower(), direction.lower())

    # Person resolution
    persons, resolution_meta = _resolve_person(plate_norm, plate_index)

    # Content
    if direction_norm == "entry":
        action = "Garage entry recorded"
    elif direction_norm == "exit":
        action = "Garage exit recorded"
    else:
        action = f"Garage event ({direction})"
    content = f"{action} for vehicle {plate_raw} at barrier {barrier}."

    # Deterministic ID: date + time + normalized plate + barrier
    # Use raw date/time strings to avoid any clock-correction ambiguity in the ID.
    id_parts = f"{date_str}-{time_str}-{plate_norm or 'UNKNOWN'}-{barrier}"
    record_id = f"garage-{id_parts.replace(':', '').replace('.', '')}"

    metadata: dict[str, Any] = {
        # Original values
        "date_raw": date_str,
        "time_raw": time_str,
        "license_plate_raw": plate_raw,
        "license_plate_normalized": plate_norm,
        "event_type_raw": direction,
        "event_type_normalized": direction_norm,
        "barrier": barrier,
        "recognition_confidence_pct": int(confidence) if confidence.isdigit() else confidence,
        # Timezone / clock-offset metadata
        "timezone_source": tz_note,
        "clock_offset_corrected": clock_corrected,
        # Provenance
        "source_file": rel_source,
        "record_index": record_index,
    }
    metadata.update(resolution_meta)

    return DataPoint(
        id=record_id,
        data_type=DataType.garage,
        persons=persons,
        content=content,
        start_time=utc_dt,
        end_time=None,
        location=barrier,
        metadata=metadata,
    )


class GarageParser:
    """Parse the garage barrier log CSV into DataPoint records.

    Usage::

        permit_parser = ParkingPermitParser()
        plate_index   = permit_parser.build_plate_index(permit_path)

        garage_parser = GarageParser(plate_index)
        records       = garage_parser.parse(Path("case_bundle/garage_barrier_log.csv"))
    """

    def __init__(self, plate_index: dict[str, _PermitRecord]) -> None:
        self._plate_index = plate_index

    def parse(self, path: Path) -> list[DataPoint]:
        """Parse *path* (the barrier CSV) and return one DataPoint per row."""
        source_anchor = path.resolve().parents[2]  # bobathon-participants/
        rel_source = _repo_relative_posix(path, source_anchor)

        raw_text = path.read_text(encoding="utf-8", errors="replace")
        lines = raw_text.splitlines()

        # Skip comment lines (start with #) and the header line
        data_lines = [
            (original_idx, line)
            for original_idx, line in enumerate(lines)
            if line.strip() and not line.startswith("#") and not line.startswith("Datum")
        ]

        records: list[DataPoint] = []
        for record_index, (original_line_idx, line) in enumerate(data_lines):
            parts = line.split(";")
            if len(parts) != 6:
                logger.warning(
                    "Row %d (file line %d) has %d fields, expected 6 – skipping: %r",
                    record_index, original_line_idx, len(parts), line,
                )
                continue
            try:
                records.append(
                    _parse_garage_row(parts, record_index, rel_source, self._plate_index)
                )
            except Exception:
                logger.exception(
                    "Failed to parse garage row %d (file line %d) – skipping.",
                    record_index, original_line_idx,
                )

        return records
