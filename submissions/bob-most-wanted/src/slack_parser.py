"""Slack export parser – parse and persist.

Converts a Slack workspace export directory into a list of DataPoint records.

Expected export layout::

    <slack_export_dir>/
        users.json
        channels.json
        <channel_name>/
            YYYY-MM-DD.json   # list of message objects
            ...

Each message object must have at least::

    {
        "type": "message",
        "user": "<user_id>",
        "text": "<message text>",
        "ts":   "<unix_timestamp_string>"
    }

Messages with a ``subtype`` field (e.g. ``channel_join``) are skipped, as are
records without a ``user`` field (bot messages, etc.).
"""

from __future__ import annotations

import json
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

_UserIndex = dict[str, str]   # user_id  -> real_name
_ChannelIndex = dict[str, str]  # channel_name -> channel_id  (unused in IDs, for metadata)


def _load_user_index(slack_dir: Path) -> _UserIndex:
    """Return a mapping of Slack user-id → real_name from users.json."""
    users_file = slack_dir / "users.json"
    with users_file.open(encoding="utf-8") as fh:
        raw: list[dict[str, Any]] = json.load(fh)
    index: _UserIndex = {}
    for entry in raw:
        uid = entry.get("id", "").strip()
        name = entry.get("real_name", entry.get("name", "")).strip()
        if uid and name:
            index[uid] = name
    return index


def _load_channel_index(slack_dir: Path) -> _ChannelIndex:
    """Return a mapping of channel_name → channel_id from channels.json."""
    channels_file = slack_dir / "channels.json"
    with channels_file.open(encoding="utf-8") as fh:
        raw: list[dict[str, Any]] = json.load(fh)
    index: _ChannelIndex = {}
    for entry in raw:
        cid = entry.get("id", "").strip()
        name = entry.get("name", "").strip()
        if cid and name:
            index[name] = cid
    return index


def _ts_to_datetime(ts_str: str) -> datetime:
    """Convert a Slack timestamp string (Unix seconds with decimals) to UTC datetime."""
    return datetime.fromtimestamp(float(ts_str), tz=timezone.utc)


def _repo_relative_posix(file_path: Path, anchor: Path) -> str:
    """Return *file_path* as a forward-slash path relative to *anchor*.

    *anchor* should be the ``bobathon-participants`` directory so that the
    result starts with ``meridian_case_bundle/...`` and is free of any
    machine-specific prefix or ``..`` segments.
    """
    return file_path.resolve().relative_to(anchor.resolve()).as_posix()


def _parse_channel_file(
    json_file: Path,
    channel_name: str,
    channel_id: str,
    user_index: _UserIndex,
    source_anchor: Path,
) -> list[DataPoint]:
    """Parse one YYYY-MM-DD.json file from a channel directory."""
    with json_file.open(encoding="utf-8") as fh:
        messages: list[dict[str, Any]] = json.load(fh)

    rel_source = _repo_relative_posix(json_file, source_anchor)

    records: list[DataPoint] = []
    for message_index, msg in enumerate(messages):
        # Only process top-level user messages; skip subtypes and system events.
        if msg.get("type") != "message":
            continue
        if "subtype" in msg:
            continue

        user_id: str = msg.get("user", "").strip()
        if not user_id:
            continue  # bot or webhook message without a user

        text: str = msg.get("text", "").strip()
        if not text:
            continue  # empty message – nothing to normalise

        ts_raw: str = msg.get("ts", "").strip()
        if not ts_raw:
            logger.warning("Slack message in %s missing ts, skipping.", json_file)
            continue

        real_name = user_index.get(user_id, user_id)
        msg_time = _ts_to_datetime(ts_raw)

        # Deterministic, stable ID: no two messages share the same ts within a workspace.
        record_id = f"slack-{channel_name}-{ts_raw}"

        records.append(
            DataPoint(
                id=record_id,
                data_type=DataType.slack,
                persons=[real_name],
                content=text,
                start_time=msg_time,
                metadata={
                    "channel": channel_name,
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "ts": ts_raw,
                    "source_file": rel_source,
                    "message_index": message_index,
                },
            )
        )

    return records


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


class SlackParser:
    """Parse a Slack workspace export directory into DataPoint records.

    Usage::

        parser = SlackParser()
        records = parser.parse(Path("case_bundle/slack_export"))
    """

    def parse(self, path: Path) -> list[DataPoint]:
        """Parse all channel message files found under *path*.

        *path* must be the root of the Slack export (i.e. the directory that
        contains ``users.json``, ``channels.json``, and one sub-directory per
        channel).

        ``source_file`` in each record's metadata is stored relative to the
        parent of the ``bobathon-participants`` directory (i.e. the directory
        that sits one level above the Slack export's top-level case folder),
        so the path starts with ``meridian_case_bundle/...`` and is stable
        across machines.

        Returns one :class:`DataPoint` per non-empty, non-system message.
        """
        user_index = _load_user_index(path)
        channel_index = _load_channel_index(path)

        # Anchor for repo-relative source paths:
        # path is  .../bobathon-participants/meridian_case_bundle/.../slack_export
        # anchor   .../bobathon-participants
        # result   meridian_case_bundle/.../slack_export/<channel>/YYYY-MM-DD.json
        source_anchor = path.resolve().parents[2]  # three levels up from slack_export/

        records: list[DataPoint] = []

        for channel_dir in sorted(path.iterdir()):
            if not channel_dir.is_dir():
                continue
            channel_name = channel_dir.name
            channel_id = channel_index.get(channel_name, "")

            for json_file in sorted(channel_dir.glob("*.json")):
                try:
                    file_records = _parse_channel_file(
                        json_file, channel_name, channel_id, user_index, source_anchor
                    )
                    records.extend(file_records)
                except Exception:
                    logger.exception("Failed to parse %s – skipping.", json_file)

        return records


# ---------------------------------------------------------------------------
# CLI convenience entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Parse Slack export and write unified_data/slack.jsonl")
    ap.add_argument("slack_dir", type=Path, help="Root of the Slack export directory")
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("unified_data/slack.jsonl"),
        help="Destination JSONL file (default: unified_data/slack.jsonl)",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = SlackParser()
    records = parser.parse(args.slack_dir)
    records.sort(key=lambda r: (r.metadata.get("channel", ""), r.metadata.get("ts", "")))
    write_jsonl(records, args.output)
    print(f"Wrote {len(records)} records to {args.output.resolve()}")
