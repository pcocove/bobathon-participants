# ibm-bobathon

IBM/Accenture Bobathon Competition – Halcyon Systems Case 2025-1011

## Purpose

This project normalises heterogeneous case data (calendars, Slack, e-mail, card feed, expenses, garage logs, helpdesk, Jira, diligence log) into a single unified format so that records from different systems can be searched and correlated programmatically.

## Problem Statement

Pull information from different sources: ics files, text files, json files, mail export.
Aggregate information per involved person.

Process for finding suspect:
  1. Define exact timeframe in which the theft could have happened
  2. Find for each person: where they were, with whom (alibi)

## Unified Data Model

All records are normalised into a `DataPoint` (defined in `src/bobathon/domain/unified_data.py`):

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique, non-blank identifier |
| `data_type` | `DataType` | Source system (see below) |
| `persons` | `list[str]` | Involved persons (sender, attendees, …) |
| `content` | `str` | Human-readable summary of the record |
| `start_time` | `datetime \| None` | Start timestamp (timezone-aware recommended) |
| `end_time` | `datetime \| None` | End timestamp; must not precede `start_time` |
| `location` | `str \| None` | Physical or logical location |
| `metadata` | `dict[str, Any]` | Source-specific extra fields |

### DataType values

`calendar` · `slack` · `email` · `credit_card` · `expense` · `garage` · `parking_permit` · `helpdesk` · `jira` · `diligence`

### Validation rules

- `id` and `content` must be non-blank strings (leading/trailing whitespace is stripped).
- Every entry in `persons` must be a non-blank string (stripped).
- `location` is stripped; an all-whitespace value is stored as `None`.
- `end_time` must not be before `start_time`.
- Extra fields are rejected (`extra = "forbid"`).

## Project Structure

```
ibm-bobathon/
├── README.md
├── pyproject.toml
├── .gitignore
│
├── config/
│   └── settings.json          # Runtime configuration
│
├── src/
│   └── bobathon/
│       ├── __init__.py
│       ├── cli.py             # CLI entry point (help + version only)
│       ├── settings.py        # Settings model + loader
│       │
│       ├── domain/
│       │   ├── __init__.py
│       │   └── unified_data.py   # DataType, DataPoint, UnifiedData
│       │
│       ├── processing/
│       │   ├── __init__.py
│       │   └── pipeline.py    # Pipeline protocol (not yet implemented)
│       │
│       ├── parsers/
│       │   ├── __init__.py
│       │   └── base.py        # DataParser protocol (not yet implemented)
│       │
│       └── exporters/
│           ├── __init__.py
│           └── base.py        # DataExporter protocol (not yet implemented)
│
└── output/
    └── .gitkeep
```

## Installation

```bash
pip install -e .
```

Requires Python 3.11 or newer and Pydantic 2.

## CLI

```bash
bobathon --help
bobathon --version
```

The CLI currently only provides `--help` and `--version`. No pipeline execution is available yet.

## Requirements

### Data Structures

The main goal is to bring all separate data points into one unified format, in order to be able to search it more effectively and find correlations

| Item | Description |
|---|---|
| Persons | List of involved persons (sent message, from their calendar) |
| Content | Content of the datapoint (message content, event title, location) |
| Time | Timestamp (message sent time, event time) |

### Functionalities

<<<<<<< HEAD
1. Implement unified data format ✅
2. Parse all data sources into the unified format *(not yet implemented)*
   1. Calendars
   2. Slack messages
   3. E-Mails
   4. Credit card feed
   5. Expense reports
   6. Garage barrier and parking permits (need to process together)
   7. Helpdesk
   8. JIRA
   9. Diligence log (data accesses)
3. Implement queries on the data *(not yet implemented)*

## Garage & Parking Permits

Normalised by `src/garage_parser.py` from `garage_barrier_log.csv` and `parking_permits.xlsx`.

### Records written

| Dataset | Count |
|---|---|
| `parking_permits.jsonl` | 37 |
| `garage.jsonl` | 5,082 |

### Garage resolution summary

| Status | Count | Explanation |
|---|---|---|
| resolved | 5,058 | Plate matched exactly one permit → one person |
| unresolved | 24 | Plate not in permit registry (visitors, partial reads like `SG 482 1?7`, `LU 45 902`) |
| ambiguous | 0 | No plate matched multiple permits |
| conflict | 0 | No event had multiple identifiers resolving to different people |

All timestamps account for a documented 1-hour clock offset in the barrier system (CET instead of CEST, 30 March – 26 October 2025, per FAC-352). A resolved record identifies the **registered permit holder for that vehicle** — not proof of physical presence.

## Not Yet Implemented

- Pipeline execution logic
- Data exporters
- Query / investigation logic
=======
1. Implement unified data format
2. Parse all data sources into the unified format
  1. Calendars
  2. Slack messages
  3. E-Mails
  4. Credit card feed
  5. Expense reports
  6. Garage barrier and parking permits (need to process together)
  7. Helpdesk
  8. JIRA
  9. Diligence log (data accesses)
3. Implement queries on the data
>>>>>>> 7b1173e (Update README)
