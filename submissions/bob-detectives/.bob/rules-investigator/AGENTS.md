# Investigator mode — working rules

**Tools propose, you decide.** The pipeline turns the case bundle into *proposals* (findings
F-xxx, inconsistencies I-xx, challenges R-xx). In agent mode none of them counts until you
review it. You also add what the tools missed, and you write the verdict.

## The playbook

`src/investigate playbook` lists the steps and what is still open in each:

1. **frame** — understand the incident, the operation window, the people, what was withheld.
2. **sweep** — decide every inconsistency before arguing anything.
3. **suspect:<handle>** × 8 — suspicion → paperwork → judgement, for each person.
4. **crosscheck** — compare: who was on site, who knew what *and when*, which suspicions mislead.
5. **challenge** — try to break the leading hypothesis.
6. **verdict** — draft the verdict for all eight, propose a confidence.

`src/investigate step show <ID>` gives the goal, the instructions and the open items.
`src/investigate step done <ID> --summary "…"` closes it (it refuses while items are open).

## Commands

| Command | Use |
|---|---|
| `src/investigate files [<part>]` | what is in the data (file groups, sizes); `files interviews` lists that group's files — use it instead of `ls` |
| `src/investigate proposals --suspect "<name>" [--pending]` | the tools' proposals and your decisions |
| `src/investigate issues --kind sweep\|adversarial` | inconsistencies / challenges |
| `src/investigate dig <F-xxx\|I-xx\|R-xx\|name\|path:line>` | context pack: cited lines in context, what the person did around then, where the identifiers appear elsewhere, questions worth pursuing |
| `src/investigate review <ID> accept\|reject\|amend\|escalate --note "…"` | your decision; `amend --class C --weight W`; counter-evidence with `--source path:line --quote "…"` (verified) |
| `src/investigate finding add --suspect "<name>" --constraint … --class … --title … --claim … --source path:line --quote "…"` | new evidence (verified; rejected if the quote is not there) |
| `src/investigate search "<regex>" --in <prefix>` / `show <path:line> -C 5` / `timeline --suspect "<name>"` | read and search the bundle |
| `src/investigate time <epoch\|ISO…Z> …` | convert raw chat epochs / UTC stamps to the case's local time (no `python3 -c`) |
| `src/investigate verdict draft --suspect "<name>" --verdict … --reasoning "…" --cite F-xxx` | your verdict per suspect |
| `src/investigate confidence propose <value> --why "…"` | your confidence; a person signs it off |
| `src/investigate note "…"` | a reasoning note in the journal |
| `src/investigate run --quiet` then `status` | recompute after your decisions |

## Rules

- **Chat is only a lead.** If you cannot cite `path:line` with an exact quote, you do not have it.
- **Every decision has a note** a person can check in under a minute.
- **One line per quote**, copied exactly (or one PDF page / xlsx row / photo). No joining, fixing or translating.
- **Order of events decides knowledge.** Before calling knowledge "only the thief could have", list every
  route that existed *before* the person spoke: public records about this event, their own earlier
  records, leaks (who could overhear the investigator).
- **Times**: the card feed is UTC, chat is epoch, calendars differ by exporter, the garage clock was
  corrected in the sweep. `timeline` and `dig` show corrected local time and the raw value.
- **Escalate** judgement calls to a person (`review I-xx escalate`); don't decide them silently.
- Never edit the bundle, `investigation/output/` or `investigation/state/`. Your notes go in
  `investigation/notes/case_memory.md`.

## Search syntax

`src/investigate search` takes a Python regex, case-insensitive: use `a|b` for alternatives (`a\|b` also works). `--in` takes any part of a path, comma-separated (`--in jira,helpdesk`). There is no `ls` or `cat` for the data — use `files`, `search`, `show`.

## Notes

Your working memory across steps: read it with `src/investigate memory show`, add to it with `src/investigate memory add --section <step-id> "what you concluded, with path:line"`. That is the only way to write it — shell writes (`cat >`, heredocs, `echo >>`) are blocked. `src/investigate note "…"` adds a line to the journal.
