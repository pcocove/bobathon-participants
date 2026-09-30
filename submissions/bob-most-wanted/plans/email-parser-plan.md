# Email Parser Plan

## Top-Level Overview

**Goal**: Implement `src/email_parser.py` — a concrete parser that reads `.mbox` files (RFC 4155 mbox format) and returns a `list[DataPoint]` conforming to the `DataParser` protocol defined in `src/parser_base.py`. Wire the parser into `src/cli.py` so that passing an `.mbox` file via `--input` automatically routes to `EmailParser`.

**Scope**:
- New file `src/email_parser.py`.
- Update `src/cli.py` to dispatch to `EmailParser` when the input file suffix is `.mbox`.
- No pipeline wiring beyond the CLI, no exporter work — those are separate concerns.

**Approach**:
- Use Python's standard library `mailbox` module to iterate over messages in an mbox file.
- Map each message to one `DataPoint` with `data_type = DataType.email`.
- Validate the mapping against the sample file `email_export.mbox` to confirm all fields are populated correctly.
- Write a unit test file `tests/test_email_parser.py` using `email_export.mbox` as a fixture.

---

## Sub-Task 1 — Confirm dependency situation

**Intent**: The `mailbox` module is part of the Python standard library — no new third-party package is required. Confirm no `pyproject.toml` changes are needed.

**Expected Outcomes**:
- `pyproject.toml` is unchanged (no new dependency needed).
- It is documented that `mailbox` (stdlib) is the chosen parsing approach.

**Todo List**:
1. Open `pyproject.toml` and confirm `mailbox` is stdlib (no action needed).
2. No file changes required for this sub-task — proceed directly to Sub-Task 2.

**Relevant Context**:
- `pyproject.toml` — current deps: `pydantic>=2.0`, `icalendar>=5.0`, Python `>=3.11`.
- Python `mailbox.mbox` iterates mbox files message by message, returning `mailbox.mboxMessage` objects.

**Status**: [x] done

---

## Sub-Task 2 — Implement `EmailParser`

**Intent**: Create the concrete parser class that satisfies the `DataParser` protocol. Each message in the mbox file becomes one `DataPoint`.

**Expected Outcomes**:
- `src/email_parser.py` exists and is importable.
- `EmailParser().parse(path)` returns a non-empty `list[DataPoint]` for `email_export.mbox`.
- Every `DataPoint` has correct field values per the mapping table below.

**mbox → DataPoint field mapping**:

| mbox header/field | DataPoint field | Notes |
|---|---|---|
| `Message-ID` | `id` | Strip surrounding angle-brackets and whitespace |
| `Subject` + body | `content` | Subject and plain-text body concatenated with a newline separator |
| `Date` | `start_time` | Parse to UTC-aware datetime |
| `Date` | `end_time` | Set equal to `start_time` (emails have no duration) |
| `From` + `To` + `Cc` | `persons` | Display name if present, else email address; deduplicated, blank entries filtered |
| `X-Attachment` | `metadata["attachments"]` | List of filenames from the custom header; omit key if header absent |

**Todo List**:
1. Create `src/email_parser.py`.
2. Import `mailbox`, `email.utils`, `email.header`, `datetime`, `timezone` from stdlib, and `DataPoint`, `DataType` from `unified_data`.
3. Define `class EmailParser` (no explicit base class — Protocol is satisfied structurally).
4. Implement `parse(self, path: Path) -> list[DataPoint]`:
   a. Open the file with `mailbox.mbox(path, factory=None, create=False)`.
   b. Iterate over messages; for each, call a private `_parse_message` helper.
   c. Return the collected list.
5. Implement `_parse_message(self, msg) -> DataPoint`:
   a. Extract `id` from `Message-ID` header — strip `<` and `>` characters and whitespace.
   b. Extract `subject` from `Subject` header using `email.header.decode_header` to handle encoded words.
   c. Extract `body` as the plain-text payload; if the message is `multipart`, walk parts and take the first `text/plain` part.
   d. Set `content = subject + "\n\n" + body.strip()`.
   e. Parse `Date` header with `email.utils.parsedate_to_datetime`; convert to UTC-aware datetime. Assign to both `start_time` and `end_time`.
   f. Collect `persons` by parsing `From`, `To`, and `Cc` headers with `email.utils.getaddresses`; for each `(name, addr)` pair, use `name.strip()` if non-empty, else `addr.strip()`; filter blanks and deduplicate while preserving order.
   g. If `X-Attachment` header is present, store its value(s) as `metadata["attachments"]` (a list of strings).
   h. If `Date` header is missing or unparseable, set `start_time = end_time = None`.
6. Return the `DataPoint`.

**Relevant Context**:
- `src/parser_base.py` — `DataParser` Protocol; `parse` signature is `(self, path: Path) -> list[DataPoint]`.
- `src/unified_data.py` — `DataPoint` validators: `id` and `content` must be non-blank strings; `_validate_persons` rejects blank name entries; `end_time >= start_time`.
- `src/calendar_parser.py` — reference implementation pattern to follow closely.
- `email_export.mbox` — two messages; first has `To` only, second has `To`, `Cc`, and `X-Attachment`. Neither has a display name in the headers (email addresses only), so `persons` will be email addresses for this sample.

**Status**: [x] done

---

## Sub-Task 3 — Wire CLI integration

**Intent**: Extend `src/cli.py` so that when `--input` receives an `.mbox` file, it dispatches to `EmailParser` instead of `CalendarParser`. The CLI should auto-detect the file type by suffix.

**Expected Outcomes**:
- Running `bobathon --input email_export.mbox` imports email records and prints a count.
- Running `bobathon --input andrin.caduff.ics` still imports calendar records unchanged.
- The `--input` help text is updated to mention both `.ics` and `.mbox` formats.

**Todo List**:
1. Open `src/cli.py`.
2. Add `from email_parser import EmailParser` alongside the existing `CalendarParser` import.
3. In `main()`, replace the unconditional `CalendarParser().parse(args.input)` call with a dispatch block:
   - If `args.input.suffix == ".mbox"` → use `EmailParser`; print `"email message(s)"`.
   - Else (`.ics`) → use `CalendarParser`; print `"calendar event(s)"`.
4. Update the `--input` argument `help` string to say "Path to an .ics or .mbox file to import."

**Relevant Context**:
- `src/cli.py` — current implementation always uses `CalendarParser`; the dispatch addition is minimal.
- No changes to argument names, the `UnifiedData` accumulator, or the print format beyond the record-type label.

**Status**: [x] done

---

## Sub-Task 4 — Write unit tests

**Intent**: Verify the parser produces correct output against the real sample file, and that edge cases (missing optional fields) are handled.

**Expected Outcomes**:
- `tests/test_email_parser.py` exists and passes with `pytest`.
- Tests cover: correct record count, field values for known messages, `data_type` is always `DataType.email`, and `X-Attachment` metadata.

**Todo List**:
1. Create `tests/test_email_parser.py`.
2. Write a test that calls `EmailParser().parse(Path("email_export.mbox"))` and asserts:
   - The returned list has 2 items (matching the sample file's message count).
   - Every record has `data_type == DataType.email`.
   - First message: `id` is `20250000.5914@halcyon-systems.ch`, `content` starts with `Q1 board pack: sections due Fri`, `persons` includes `renata.vogel@halcyon-systems.ch`.
   - Second message: `metadata["attachments"]` contains `Halcyon_Board_Q1_2025_final.pdf`.
   - All `start_time` values are UTC-aware; `end_time == start_time` for every record.
3. Write a test that parses a minimal in-memory mbox string (using `tmp_path`) with a message that omits `Cc` and `X-Attachment` — assert the parser does not raise and returns `metadata` without an `attachments` key.
4. Write a test that parses a message with no `Date` header — assert `start_time is None` and `end_time is None`.

**Relevant Context**:
- `email_export.mbox` is at the workspace root; use `Path(__file__).parents[1] / "email_export.mbox"` to locate it from the tests directory.
- `tests/__init__.py` already exists.
- Follow the patterns established in `tests/test_calendar_parser.py`.

**Status**: [x] done

---

## Sub-Task 5 — CLI integration test

**Intent**: Verify the CLI correctly dispatches to `EmailParser` for `.mbox` files and `CalendarParser` for `.ics` files.

**Expected Outcomes**:
- A test in `tests/test_cli.py` (or a new section in an existing file) asserts that calling `main()` with an `.mbox` path produces email `DataPoint` records and that the `.ics` path still produces calendar records.

**Todo List**:
1. Create `tests/test_cli.py`.
2. Write a test that patches `sys.argv` with `["bobathon", "--input", str(path_to_mbox)]` and calls `main()` — assert no exception is raised (smoke test; output validated via the parser tests).
3. Write a corresponding smoke test for the `.ics` path to confirm the dispatch does not break the existing flow.

**Relevant Context**:
- `src/cli.py` — `main()` reads `sys.argv` via `argparse`.
- Use `monkeypatch.setattr` (pytest) to override `sys.argv`.
- The global `unified_data` accumulator in `cli.py` persists across calls in the same process — reset it between tests if needed by reassigning `cli.unified_data = UnifiedData()`.

**Status**: [x] done

---

## Implementation Notes (for Agent mode)

- Process sub-tasks **in order**: dependency check → implementation → CLI wiring → parser tests → CLI tests.
- After completing each sub-task, mark its Status as `[x] done` in this file before proceeding.
- The `DataParser` Protocol uses structural subtyping — `EmailParser` does **not** need to explicitly inherit from or import `DataParser`; it only needs to implement the `parse` method with the correct signature.
- `mailbox.mbox` opens in read mode by default; pass `create=False` to avoid creating the file if it doesn't exist.
- `email.utils.parsedate_to_datetime` raises `TypeError` if the `Date` header is missing or malformed — catch it and set `start_time = end_time = None`.
- The `X-Attachment` header is non-standard. `mailbox.mboxMessage` exposes it via `msg["X-Attachment"]` — it returns a string (not a list), so wrap it in a list.
- `content` must be non-blank. Concatenate subject and body with `"\n\n"` as separator. If both `Subject` and body are empty, skip the message or raise a descriptive error — but the sample file guarantees both are present.
- CLI dispatch uses `args.input.suffix` — `.mbox` routes to `EmailParser`, everything else falls through to `CalendarParser` (existing behaviour unchanged).
