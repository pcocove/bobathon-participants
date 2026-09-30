"""JSONL exporter — shared persistence utilities and exporter protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from unified_data import DataPoint, UnifiedData


class DataExporter(Protocol):
    """Interface that every concrete exporter must satisfy."""

    def export(self, data: UnifiedData, destination: Path) -> None:
        """Write *data* to *destination* in the exporter's format."""
        ...


def write_jsonl(records: list[DataPoint], destination: Path) -> None:
    """Write *records* to *destination* as JSONL (one JSON object per line).

    Uses :meth:`DataPoint.model_dump_json` for serialisation, which produces
    compact, valid JSON with ISO-8601 datetimes.  The file is always
    overwritten so that re-runs never create duplicates.  *destination*'s
    parent directory is created automatically if it does not exist.

    Records are written in the order supplied; callers that need a
    deterministic order should sort before calling this function.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.model_dump_json())
            fh.write("\n")
