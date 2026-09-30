"""CLI entry point for bobathon."""

from __future__ import annotations

import argparse
from pathlib import Path

from calendar_parser import CalendarParser
from card_feed_parser import CardFeedParser
from email_parser import EmailParser
from exporter import write_jsonl
from helpdesk_parser import HelpdeskParser
from unified_data import UnifiedData

__version__ = "0.1.0"

# Global accumulator — all parsed records land here.
unified_data = UnifiedData()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bobathon",
        description="Halcyon Systems case data normalisation tool.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--input",
        metavar="FILE",
        type=Path,
        help="Path to an .ics, .mbox, or .md file to import.",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        type=Path,
        help="Path to a .jsonl file to write records to (must end in .jsonl).",
    )
    return parser


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.input is None:
        parser.print_help()
        return

    if args.output is not None and args.output.suffix != ".jsonl":
        parser.error("--output must end in .jsonl")

    if args.input.suffix == ".mbox":
        records = EmailParser().parse(args.input)
        label = "email message(s)"
    elif args.input.suffix == ".md":
        records = HelpdeskParser().parse(args.input)
        label = "helpdesk ticket(s)"
    elif args.input.suffix == ".csv":
        records = CardFeedParser().parse(args.input)
        label = "card transaction(s)"
    else:
        records = CalendarParser().parse(args.input)
        label = "calendar event(s)"

    unified_data.records.extend(records)

    if args.output is not None:
        write_jsonl(records, args.output)
        print(f"Imported {len(records)} {label}. Wrote {args.output}.")
    else:
        print(f"Imported {len(records)} {label}. "
              f"Total records in unified_data: {len(unified_data.records)}.")

if __name__ == "__main__":
    main()