---
name: work-agent-task
description: Use when the user asks Bob to work, pick up or finish an investigation agent task (IDs like A-01), or to "find the paperwork" for a suspect or claim in the case bundle.
---

# Work an investigation agent task

1. Run `src/investigate tasks --kind agent` and pick the task the user named, or the open task
   with the lowest priority number.
2. Run `src/investigate task show <ID>` and read `why`, `question` and `read`.
3. Open each pointer with `src/investigate show <source> -C 5`.
4. Search outward with `src/investigate search "<regex>"`, narrowing with `--in <prefix>`
   (for example `slack_export/`, `interviews/`, `jira_export.json`, `email_export.mbox`).
   Check the order of events with `src/investigate timeline --suspect "<name>"`.
5. For every line that confirms or explains the point, add it with
   `src/investigate finding add … --by bob`. If it prints REJECTED, fix the citation — the quote
   is not at that line.
6. Run `src/investigate run --quiet` and summarise in three lines: what you added (with
   citations), whether the verdict or confidence changed, and what remains for a human.
