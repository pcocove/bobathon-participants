"""Corporate card feed parser – card_feed_q4.csv normalisation and JSONL export.

Source data
-----------

**Corporate card feed** (``card_feed_q4.csv``)
    Comma-separated issuer export from Halcyon Systems AG.
    Two comment lines precede the header::

        # Firmenkarten-Transaktionen / corporate card feed · Halcyon Systems AG · issuer export 27.11.2025
        # timestamp_utc = authorisation time at the terminal, UTC. Cardholder = employee handle.
        txn_id,timestamp_utc,cardholder,card_last4,merchant,merchant_city,mcc,amount_chf

    Columns:

    =============  ============================================================
    txn_id         Transaction ID, e.g. ``TX880000``
    timestamp_utc  Authorisation timestamp, ISO-8601 UTC (e.g. ``2025-08-01T06:00:00Z``)
    cardholder     Employee handle, e.g. ``dessie.moran``
    card_last4     Last four digits of the card number (4-digit string)
    merchant       Merchant name
    merchant_city  Merchant city
    mcc            Merchant Category Code (ISO 18245, integer)
    amount_chf     Transaction amount in Swiss francs (decimal)
    =============  ============================================================

All timestamps in the file are already UTC; no clock-offset correction is required.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from exporter import write_jsonl
from unified_data import DataPoint, DataType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _repo_relative_posix(file_path: Path, anchor: Path) -> str:
    """Return *file_path* as a forward-slash path relative to *anchor*."""
    return file_path.resolve().relative_to(anchor.resolve()).as_posix()


def _parse_timestamp(raw: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp string into a timezone-aware datetime.

    Accepts the ``Z`` suffix as used in the card feed (e.g.
    ``2025-08-01T06:00:00Z``).
    """
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _parse_card_row(
    row: dict[str, str],
    record_index: int,
    rel_source: str,
) -> DataPoint:
    """Convert one CSV row dict to a card-feed DataPoint."""
    txn_id       = row["txn_id"].strip()
    timestamp_raw = row["timestamp_utc"].strip()
    cardholder   = row["cardholder"].strip()
    card_last4   = row["card_last4"].strip()
    merchant     = row["merchant"].strip()
    merchant_city = row["merchant_city"].strip()
    mcc_raw      = row["mcc"].strip()
    amount_raw   = row["amount_chf"].strip()

    # Timestamp (already UTC)
    start_time = _parse_timestamp(timestamp_raw)

    # Numeric fields
    mcc: int | str
    try:
        mcc = int(mcc_raw)
    except ValueError:
        mcc = mcc_raw

    amount: float | str
    try:
        amount = float(amount_raw)
    except ValueError:
        amount = amount_raw

    # Persons: the cardholder handle
    persons = [cardholder] if cardholder else []

    # Human-readable content
    content = (
        f"Card transaction {txn_id}: {cardholder} spent CHF {amount_raw} "
        f"at {merchant} ({merchant_city}) – MCC {mcc_raw}"
    )

    # Record ID: use the issuer-assigned transaction ID directly
    record_id = f"card-{txn_id}" if txn_id else f"card-row-{record_index}"

    metadata: dict[str, Any] = {
        "txn_id": txn_id,
        "timestamp_raw": timestamp_raw,
        "cardholder": cardholder,
        "card_last4": card_last4,
        "merchant": merchant,
        "merchant_city": merchant_city,
        "mcc": mcc,
        "amount_chf": amount,
        "source_file": rel_source,
        "record_index": record_index,
    }

    return DataPoint(
        id=record_id,
        data_type=DataType.credit_card,
        persons=persons,
        content=content,
        start_time=start_time,
        end_time=None,
        location=merchant_city if merchant_city else None,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


class CardFeedParser:
    """Parse the corporate card feed CSV into DataPoint records.

    Usage::

        parser = CardFeedParser()
        records = parser.parse(Path("case_bundle/card_feed_q4.csv"))
    """

    def parse(self, path: Path) -> list[DataPoint]:
        """Parse *path* and return one DataPoint per transaction row.

        Comment lines (starting with ``#``) and the header are handled
        automatically.  Rows that cannot be parsed are skipped with a warning.
        """
        source_anchor = path.resolve().parents[2]  # bobathon-participants/
        rel_source = _repo_relative_posix(path, source_anchor)

        raw_text = path.read_text(encoding="utf-8", errors="replace")

        # Strip comment lines before handing to csv.DictReader
        data_lines = [
            line
            for line in raw_text.splitlines()
            if line.strip() and not line.startswith("#")
        ]

        reader = csv.DictReader(io.StringIO("\n".join(data_lines)))

        records: list[DataPoint] = []
        for record_index, row in enumerate(reader):
            try:
                records.append(_parse_card_row(row, record_index, rel_source))
            except Exception:
                logger.exception(
                    "Failed to parse card feed row %d – skipping: %r",
                    record_index,
                    dict(row),
                )

        return records


# ---------------------------------------------------------------------------
# CLI convenience entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse corporate card feed CSV and write unified_data/card_feed.jsonl"
    )
    ap.add_argument("csv_file", type=Path, help="Path to card_feed_q4.csv")
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("unified_data/card_feed.jsonl"),
        help="Destination JSONL file (default: unified_data/card_feed.jsonl)",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = CardFeedParser()
    records = parser.parse(args.csv_file)
    records.sort(key=lambda r: r.start_time or "")
    write_jsonl(records, args.output)
    print(f"Wrote {len(records)} records to {args.output.resolve()}")
