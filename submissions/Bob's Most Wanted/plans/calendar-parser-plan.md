# Calendar Parser Plan

## Top-Level Overview

**Goal**: Implement `src/calendar_parser.py` — a concrete parser that reads `.ics` files (RFC 5545 iCalendar format) and returns a `list[DataPoint]` conforming to the `DataParser` protocol defined in `src/parser_base.py`.

**Scope**:
- New file `src/calendar_parser.py` only.
- No changes to existing files unless a missing import or dependency forces a minor fix.
- No pipeline wiring, CLI changes, or exporter work — those are separate concerns.

**Approach**:
- Use the Python standard library `icalendar` package (or fall back to manual RFC 5545 parsing if the package is unavailable) to read VEVENT blocks.
- Map each VEVENT to one `DataPoint` with `data_type = DataType.calendar`.
- Validate the mapping against the sample file `andrin.caduff.ics` to confirm all fields are populated correctly.
- Write a unit test file `tests/test_calendar_parser.py` using `andrin.caduff.ics` as a fixture.

---

## Sub-Task 1 — Confirm the `icalendar` dependency

**Intent**: The standard library has no iCalendar parser. We need a reliable third-party parser. `icalendar` is the canonical Python package for RFC 5545. Check whether it is already declared in `pyproject.toml`; if not, add it.

**Expected Outcomes**:
- `pyproject.toml` lists `icalendar>=5.0` (or equivalent) in `[project.dependencies]`.
- Running `pip install -e .` from the workspace installs the package.

**Todo List**:
1. Open `pyproject.toml` and check `[project.dependencies]`.
2. If `icalendar` is absent, add `"icalendar>=5.0"` to the dependencies list.
3. No other file changes are needed for this sub-task.

**Relevant Context**:
- `pyproject.toml` — current deps: `pydantic>=2.0`, Python `>=3.11`.
- The sample file uses standard VEVENT/VCALENDAR blocks, fully compatible with `icalendar`.

**Status**: [x] done

---

## Sub-Task 2 — Implement `CalendarParser`

**Intent**: Create the concrete parser class that satisfies the `DataParser` protocol. Each VEVENT in the `.ics` file becomes one `DataPoint`.

**Expected Outcomes**:
- `src/calendar_parser.py` exists and is importable.
- `CalendarParser().parse(path)` returns a non-empty `list[DataPoint]` for `andrin.caduff.ics`.
- Every `DataPoint` has correct field values per the mapping table below.

**ICS → DataPoint field mapping**:

| ICS property | DataPoint field | Notes |
|---|---|---|
| `UID` | `id` | Use as-is |
| `SUMMARY` | `content` | Event title/description |
| `DTSTART` | `start_time` | Convert to UTC-aware datetime |
| `DTEND` | `end_time` | Convert to UTC-aware datetime |
| `LOCATION` | `location` | Optional; `None` when absent |
| `ORGANIZER` (CN param) | `persons` | Organizer display name always included if present |
| `ATTENDEE` (CN param, if any) | `persons` | Append each attendee's display name — captures everyone involved |
| `DESCRIPTION` | `metadata["description"]` | Store raw text if present |
| _(derived)_ | `data_type` | Always `DataType.calendar` |

**Todo List**:
1. Create `src/calendar_parser.py`.
2. Import `Calendar` from `icalendar`, `Path` from `pathlib`, and `DataPoint`, `DataType` from `unified_data`.
3. Define `class CalendarParser` (no explicit base class needed — the Protocol is satisfied structurally).
4. Implement `parse(self, path: Path) -> list[DataPoint]`:
   a. Open and read the file bytes, parse with `Calendar.from_ical(...)`.
   b. Iterate over components, filter to `VEVENT` type.
   c. For each VEVENT, build a `DataPoint` using the mapping above.
   d. Handle missing optional fields (LOCATION, DESCRIPTION, ATTENDEE) gracefully — use `None` or empty list as appropriate.
   e. Ensure all `datetime` values are UTC-aware (call `.dt` on the icalendar vDatetime and normalize timezone).
5. Return the collected list.

**Relevant Context**:
- `src/parser_base.py` — `DataParser` Protocol; `parse` signature is `(self, path: Path) -> list[DataPoint]`.
- `src/unified_data.py` — `DataPoint` fields and validators; notably `id` and `content` must be non-blank strings, `end_time >= start_time`.
- `andrin.caduff.ics` — all events have UID, SUMMARY, DTSTART (UTC), DTEND (UTC), ORGANIZER with CN. No ATTENDEE or LOCATION observed in the sample.
- The `_validate_persons` validator rejects blank name entries, so filter any empty CN values.

**Status**: [x] done

---

## Sub-Task 3 — Write unit tests

**Intent**: Verify the parser produces correct output against the real sample file, and that edge cases (missing optional fields) are handled.

**Expected Outcomes**:
- `tests/test_calendar_parser.py` exists and passes with `pytest`.
- Tests cover: correct record count, field values for a known event, and `data_type` is always `DataType.calendar`.

**Todo List**:
1. Create `tests/` directory if it does not exist; add an empty `tests/__init__.py`.
2. Create `tests/test_calendar_parser.py`.
3. Write a test that calls `CalendarParser().parse(Path("andrin.caduff.ics"))` and asserts:
   - The returned list has 101 items (matching the sample file's VEVENT count).
   - Every record has `data_type == DataType.calendar`.
   - A spot-check on a known event: correct `id`, `content`, `start_time`, `end_time`, and `persons`.
4. Write a test that parses a minimal in-memory ICS string (using `tmp_path`) with a VEVENT that omits LOCATION and DESCRIPTION — assert the parser does not raise and returns `location=None` with empty `metadata`.

**Relevant Context**:
- `andrin.caduff.ics` is at the workspace root; use `Path(__file__).parents[1] / "andrin.caduff.ics"` to locate it from the tests directory.
- No existing test infrastructure — `pytest` is the standard choice; add it to `[project.optional-dependencies]` under a `dev` group if not present.

**Status**: [x] done

---

## Implementation Notes (for Agent mode)

- Process sub-tasks **in order**: dependency → implementation → tests.
- After completing each sub-task, mark its Status as `[x] done` in this file before proceeding.
- The `DataParser` Protocol uses structural subtyping — `CalendarParser` does **not** need to explicitly inherit from or import `DataParser`; it only needs to implement the `parse` method with the correct signature.
- All `datetime` fields in `DataPoint` are `datetime | None`; always produce UTC-aware datetimes (use `dt.astimezone(timezone.utc)` or `vDatetime.dt` which returns an aware datetime when TZID or Z suffix is present).
