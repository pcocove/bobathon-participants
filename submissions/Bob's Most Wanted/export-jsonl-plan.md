# Plan: JSONL Export for Calendar, Email, and Helpdesk

## Top-Level Overview

**Goal**: Add JSONL export capability for calendar, email, and helpdesk data, mirroring what already exists for slack and garage.

**Approach**:
1. Extract the reusable `write_jsonl()` function from `slack_parser.py` into a new `src/exporter.py` module, replacing `src/exporter_base.py`.
2. Update `slack_parser.py` to import `write_jsonl` from the new location.
3. Extend `cli.py` with an `--output` flag so that `bobathon --input FILE --output FILE.jsonl` writes records to JSONL.
4. Add tests covering the new `--output` flag behaviour.

**Non-goals**: No changes to the parsers themselves. No changes to the `DataPoint` schema.

---

## Sub-Tasks

---

### Sub-Task 1 — Create `src/exporter.py` and remove `src/exporter_base.py`

**Intent**  
Consolidate the shared JSONL persistence utility into one place. `exporter_base.py` currently only defines an unused `DataExporter` protocol. This sub-task replaces that file with `exporter.py`, which contains both the protocol and the concrete `write_jsonl()` function.

**Expected Outcomes**
- `src/exporter.py` exists and exports `write_jsonl(records, destination)` and the `DataExporter` protocol.
- `src/exporter_base.py` is deleted.
- `src/slack_parser.py` imports `write_jsonl` from `exporter` instead of defining it locally — the local definition is removed.
- All existing tests still pass.

**Todo List**
1. Create `src/exporter.py` containing:
   - The `DataExporter` protocol (moved verbatim from `exporter_base.py`).
   - The `write_jsonl()` function (moved verbatim from `slack_parser.py`).
2. Delete `src/exporter_base.py`.
3. In `src/slack_parser.py`: remove the local `write_jsonl()` definition and add `from exporter import write_jsonl`.

**Relevant Context**
- `write_jsonl()` is at [`src/slack_parser.py:160-175`](src/slack_parser.py:160)
- `DataExporter` protocol is at [`src/exporter_base.py:11`](src/exporter_base.py:11)

**Status**: [x] done

---

### Sub-Task 2 — Add `--output` flag to `cli.py`

**Intent**  
Allow `bobathon --input FILE --output FILE.jsonl` to write parsed records to a JSONL file. This is the primary user-facing feature and follows the same pattern as the `slack_parser.py` `__main__` block.

**Expected Outcomes**
- `cli.py` accepts an optional `--output PATH` argument.
- When `--output` is provided, `write_jsonl(records, output_path)` is called after parsing.
- The printed summary changes to also report the output path when writing: e.g., `"Imported 5 helpdesk ticket(s). Wrote unified_data/helpdesk.jsonl."`.
- When `--output` is omitted, behaviour is unchanged (records go into `unified_data` accumulator only, same summary as before).

**Todo List**
1. Add `--output` argument to `_build_parser()` in `cli.py` (optional, type `Path`, default `None`).
2. Import `write_jsonl` from `exporter` in `cli.py`.
3. After parsing, if `args.output` is set, call `write_jsonl(records, args.output)` and include the output path in the printed summary.

**Relevant Context**
- `cli.py` main function: [`src/cli.py:38-59`](src/cli.py:38)
- Pattern to follow: `slack_parser.py` `__main__` block at [`src/slack_parser.py:235-253`](src/slack_parser.py:235)
- `write_jsonl` will be importable from `exporter` after Sub-Task 1 is complete.

**Status**: [x] done

---

### Sub-Task 3 — Add tests for `--output` flag in `test_cli.py`

**Intent**  
Verify that the new `--output` flag correctly writes JSONL for each of the three data types (calendar, email, helpdesk) and that records round-trip through `write_jsonl` correctly.

**Expected Outcomes**
- Three new test functions in `tests/test_cli.py`, one per data type.
- Each test: writes a temp input file, invokes `cli.main()` with both `--input` and `--output`, asserts the output file exists, reads it back, parses each line as JSON, and checks `data_type` and `id` fields.
- All existing tests continue to pass.

**Todo List**
1. Add `test_mbox_writes_jsonl(tmp_path, monkeypatch)`:
   - Write `_MINIMAL_MBOX` to a temp `.mbox` file.
   - Invoke `cli.main()` with `--input <mbox> --output <tmp_path/out.jsonl>`.
   - Assert output file exists, contains 1 line, `data_type == "email"`.
2. Add `test_ics_writes_jsonl(tmp_path, monkeypatch)`:
   - Write `_MINIMAL_ICS` to a temp `.ics` file.
   - Invoke `cli.main()` with `--input <ics> --output <tmp_path/out.jsonl>`.
   - Assert output file exists, contains 1 line, `data_type == "calendar"`.
3. Add `test_md_writes_jsonl(tmp_path, monkeypatch)`:
   - Write `_MINIMAL_MD` to a temp `.md` file.
   - Invoke `cli.main()` with `--input <md> --output <tmp_path/out.jsonl>`.
   - Assert output file exists, contains 1 line, `data_type == "helpdesk"`.
4. Add `test_no_output_flag_does_not_write_file(tmp_path, monkeypatch)`:
   - Invoke `cli.main()` with only `--input` (no `--output`).
   - Assert no JSONL file was written to `tmp_path`.

**Relevant Context**
- Existing minimal fixtures `_MINIMAL_MBOX`, `_MINIMAL_ICS`, `_MINIMAL_MD` are already defined in [`tests/test_cli.py`](tests/test_cli.py:15)
- Pattern: read output lines with `json.loads(line)` and check `["data_type"]` field

**Status**: [x] done
