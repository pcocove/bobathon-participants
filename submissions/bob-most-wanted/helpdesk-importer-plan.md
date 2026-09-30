# Helpdesk Importer Plan

## Overview

Add a `HelpdeskParser` that reads the IT Helpdesk / Facilities ticket export format
(`.md` files matching `helpdest-export.md`) and produces `DataPoint` records, following
exactly the same pattern as the existing `EmailParser` and `CalendarParser`.

The export file contains sections separated by `### ` headings.  Each section is one
ticket.  Two ticket series appear: `HD-NNNN` (IT Helpdesk) and `FAC-NNN` (Facilities).
Both are parsed identically.

**DataPoint mapping:**

| DataPoint field | Source |
|---|---|
| `id` | Ticket ID from the heading (e.g. `HD-3000`, `FAC-341`) |
| `data_type` | `DataType.helpdesk` |
| `content` | Title + `\n\n` + everything below the header metadata line (body, resolution, comments) |
| `start_time` | "Opened" date/time on the metadata line, converted to UTC |
| `end_time` | `None` |
| `persons` | Requester username + all commenter usernames from the `*Comments:*` block, deduplicated |
| `metadata` | `{}` (empty — status is not stored) |

---

## Sub-Task 1 — Implement `HelpdeskParser`

**Intent:** Create `src/helpdesk_parser.py` satisfying the `DataParser` protocol.

**Expected Outcomes:**
- `HelpdeskParser().parse(path)` reads a `.md` export and returns one `DataPoint` per ticket.
- All `DataPoint` fields are populated as per the mapping table above.
- Persons list is deduplicated; requester always first.
- `start_time` is UTC-aware; `end_time` is `None`.

**Todo List:**
1. Create `src/helpdesk_parser.py`.
2. Implement `parse(path: Path) -> list[DataPoint]`: read the file, split on `### ` boundaries,
   skip any leading content before the first heading, call `_parse_ticket` per section.
3. Implement `_parse_ticket(block: str) -> DataPoint`:
   - Extract ticket ID and title from the heading line (`### HD-3000 · Laptop fan noise`).
   - Extract requester username and opened datetime from the metadata line
     (`Requester: tobias.krall · Opened: 2025-08-08 10:43 · Status: Closed`).
   - Everything after the metadata line is the body (strip leading blank lines).
   - Build `content = title + "\n\n" + body` (body may be empty string for tickets with only a resolution line that is part of the metadata line, or non-empty for rich tickets).
   - Actually: the metadata line ends at `Status: …`.  Any text on subsequent lines (resolution, body paragraphs, comments block) is the body.
4. Implement `_parse_opened(value: str) -> datetime | None`: parse `"2025-08-08 10:43"` as
   naive UTC datetime → return UTC-aware `datetime`.
5. Implement `_collect_persons(requester: str, body: str) -> list[str]`: start with requester,
   then scan the `*Comments:*` block for `[timestamp] username:` entries; deduplicate.

**Relevant Context:**
- Protocol: `src/parser_base.py` — `DataParser.parse(path) -> list[DataPoint]`
- Model: `src/unified_data.py` — `DataPoint`, `DataType.helpdesk`
- Pattern reference: `src/email_parser.py`
- Export sample: `helpdest-export.md`

**Status:** `[ ] pending`

---

## Sub-Task 2 — Write tests for `HelpdeskParser`

**Intent:** Add `tests/test_helpdesk_parser.py` following the same two-class structure as
`tests/test_email_parser.py`: one class against the real fixture, one for edge cases.

**Expected Outcomes:**
- Tests cover record count, data type, id mapping, content, start_time UTC, persons (requester + commenters, deduplication), end_time is None.
- Edge-case tests cover: ticket with no body, missing opened date, ticket whose persons list contains only the requester (no comments block).
- All tests pass with `pytest`.

**Todo List:**
1. Create `tests/test_helpdesk_parser.py`.
2. Class `TestHelpdeskParserWithSampleFile` (fixture = `helpdest-export.md`):
   - `test_record_count` — expect 5 records (HD-3000, HD-3001, HD-3002, FAC-341, FAC-330).
   - `test_all_records_are_helpdesk_type`
   - `test_hd3000_id` — `"HD-3000"`
   - `test_hd3000_content_starts_with_title` — starts with `"Laptop fan noise"`
   - `test_hd3000_start_time_utc` — datetime, tzinfo == UTC
   - `test_hd3000_end_time_is_none`
   - `test_hd3000_persons_includes_requester` — `"tobias.krall"` in persons
   - `test_fac330_persons_includes_commenter` — `"june.okada"` in persons
   - `test_fac330_persons_deduplication` — `"june.okada"` appears only once
   - `test_fac330_content_includes_comments_block`
3. Class `TestHelpdeskParserEdgeCases` (uses `tmp_path`):
   - Minimal ticket (no body, no comments) — parses without error, persons = [requester].
   - Ticket with missing `Opened` field — `start_time is None`.

**Relevant Context:**
- Pattern reference: `tests/test_email_parser.py`
- Fixture: `helpdest-export.md` (project root)

**Status:** `[ ] pending`

---

## Sub-Task 3 — Wire `HelpdeskParser` into the CLI

**Intent:** Update `src/cli.py` so that `.md` files are dispatched to `HelpdeskParser`,
mirroring how `.mbox` files dispatch to `EmailParser`.

**Expected Outcomes:**
- Running `bobathon --input helpdest-export.md` imports 5 helpdesk record(s) and prints a
  matching count message.
- The `--input` help text is updated to mention `.md`.
- Existing `.mbox` and `.ics` dispatch is unchanged.

**Todo List:**
1. Import `HelpdeskParser` in `src/cli.py`.
2. Add an `elif args.input.suffix == ".md":` branch before the `else` fallback that calls
   `HelpdeskParser().parse(args.input)` with `label = "helpdesk ticket(s)"`.
3. Update the `--input` help string to include `.md`.

**Relevant Context:**
- `src/cli.py` lines 46–55 — existing dispatch block
- `tests/test_cli.py` — smoke tests for CLI dispatch (add a smoke test for `.md` if the
  existing pattern includes one per parser)

**Status:** `[ ] pending`
