---
theme: nord
canvasWidth: 800
layout: center
class: text-center
---


## 🕵️ Bob's Most Wanted


*IBM/Accenture Bobathon 2026 — Halcyon Systems Case 2026-1011*

<style>
h2 {
  font-size: 3.5em;
  line-height: 1.1;
}
</style>

---

## Problem

**A theft occurred at Halcyon Systems. Who did it?**

Evidence is scattered across completely heterogeneous sources:

<style>
table {
  font-size: 1em !important;
  line-height: 1.2 !important;
  margin: 0.3em 0 !important;
}
th, td {
  padding: 0.3em 0.5em !important;
  line-height: 1.2 !important;
}
</style>

| Source | Format |
|---|---|
| Employee calendars | `.ics` files |
| Slack workspace | JSON export |
| Corporate e-mail | `.mbox` export |
| Credit card feed | CSV |
| Garage barrier log | CSV (5 000+ events) |
| Parking permits | Excel |
| Helpdesk tickets | Markdown |

---

## Investigation process

1. Define the exact timeframe in which the theft could have happened
2. Build a timeline per person — where were they, and who were they with?
3. Identify the suspect — who had the opportunity, no alibi, and suspicious activity?

<style>
ol {
  font-size: 1.4em;
  line-height: 1.5;
}
</style>


---

## Design

**Core idea:** normalise everything into one queryable format, then let Bob ask the right questions.

```
Raw sources  →  Parsers  →  Unified DataPoints (JSONL)  →  MCP Server  →  Bob
```

**Unified `DataPoint` model** — every record from every source maps to the same schema:


---

## Design - Data Structure


| Field | Description |
|---|---|
| `id` | Unique identifier |
| `data_type` | Source system (`calendar`, `slack`, `email`, `credit_card`, `garage`, …) |
| `persons` | Involved people (sender, attendees, permit holder, …) |
| `content` | Human-readable summary of the record |
| `start_time` / `end_time` | UTC-aware timestamps |
| `location` | Physical or logical location |
| `metadata` | Source-specific extra fields (merchant, amount, license plate, …) |

<style>
table {
  font-size: 1em !important;
  line-height: 1.2 !important;
  margin: 0.3em 0 !important;
}
th, td {
  padding: 0.3em 0.5em !important;
  line-height: 1.2 !important;
}
</style>



---

## Develop

**Parsers implemented** — one per data source, all conforming to the `DataParser` protocol:

```python
class DataParser(Protocol):
    def parse(self, path: Path) -> list[DataPoint]: ...
```

The `Pipeline` protocol ties parsers together — runs all sources under an input directory and returns a single `UnifiedData` container.


--- 

## Develop

Validated with **Pydantic v2** — blank IDs rejected, time range enforced, extra fields forbidden.

**MCP Server** exposes seven query tools over the JSONL output:
- `query_unified_data` — cross-source search by person, keyword, or date
- `query_garage` · `query_parking_permits` · `query_calendar` · `query_slack`
- `fuzzy_search_persons` — fuzzy name/e-mail lookup across all sources
- `fuzzy_search_content` — fuzzy keyword search across all record fields

---

## Test

**Unit tests** written for each parser — test files used as context alongside the data model to generate accurate, grounded assertions.

**Strategy:** real fixture files for integration-style assertions + minimal in-memory content for edge cases (missing fields, blank values, malformed input).

Tests are **CI-ready** — can be integrated into a pipeline via `pytest` with no additional configuration.

---

## Deploy

- MCP server (`mcp_server/server.py`) built with **FastMCP**, runs locally via stdio transport
- Registered in Bob's MCP config (`.bob/mcp.json`) so Bob can call all seven query tools directly
- JSONL output files written to `unified_data/` — lightweight, line-delimited, easy to stream
- No external infrastructure required: `uv run` or `pip install -e .` and go

---

## Demo

Bob received the full case description and solved the investigation end-to-end using the MCP server.

Targeted natural-language questions drove the analysis:

- *"Where was [person] on the day of the theft?"* → cross-referenced calendar + garage data
- *"Who else was in the building at the same time?"* → garage barrier log filtered by timeframe
- *"Did [person] make any unusual purchases around that date?"* → credit card feed by person + date

**Verdict: Renata.**

Bob identified Renata as the prime suspect — the data showed no alibi during the theft window, presence in the building confirmed via garage log, and corroborating signals across multiple sources.

<style>
ul {
  font-size: 0.8em;
  line-height: 1.2;
}
li {
  margin: 0 !important;
  padding: 0 !important;
}
</style>

---

## Questions