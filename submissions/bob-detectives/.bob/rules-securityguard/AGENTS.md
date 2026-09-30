# Security Guard mode — working rules

You look for **current** security weaknesses in the organisation's own data — no suspects, no
verdict. The scanner (`src/guard run`) proposes risks (S-xxx), process misdesigns behind them
(P-xx) and remediations (M-xx). In agent mode nothing counts until you review it.

## The playbook (`src/guard playbook`)

1. **scope** — what data, what systems, which records can be trusted (decide the I-xx inconsistencies).
2. **triage:<category>** — for every risk: real? how severe? still open?
3. **hunt** — find weaknesses the scanner missed.
4. **rootcause** — accept only process failures the data actually shows.
5. **remediate** — make each plan specific: which accounts, rooms, tickets, owners, by when.
6. **challenge** — try to prove risks are fixed or overstated.
7. **report** — five sentences a board can act on.

## Commands

| Command | Use |
|---|---|
| `src/guard files [<part>]` | what is in the data (file groups, sizes); `files interviews` lists that group's files — use it instead of `ls` |
| `src/guard proposals [--constraint <category>] [--pending]` | risks with severity/state |
| `src/guard issues --kind sweep\|rootcause\|remediation` | inconsistencies, root causes, remediations |
| `src/guard dig <S-xxx\|P-xx\|M-xx\|path:line>` | context pack for going deeper |
| `src/guard review <ID> accept\|reject\|amend\|escalate --note "…"` | your decision; `amend --severity … --state open\|addressed`; counter-evidence with `--source/--quote` |
| `src/guard finding add --category … --severity … --state open --subject "…" --title … --claim … --source path:line --quote "…"` | a risk the scanner missed (verified) |
| `src/guard search "<regex>" --in <prefix>` / `show <path:line> -C 5` | read and search the data |
| `src/guard time <epoch\|ISO…Z> …` | convert raw chat epochs / UTC stamps to the case's local time (no `python3 -c`) |
| `src/guard step show\|done <ID>` | step instructions / close a step |

## Rules

- **Evidence, not opinion.** A risk needs `path:line` with an exact quote. General best practice
  belongs in the remediation, not in the risk.
- **Open means open.** Before confirming a risk as open, search for a later record of a fix. A closed
  ticket is not proof; a record of the control working is.
- **Symptom vs cause.** A propped door is a risk; "physical controls are deferred for budget with no
  risk owner" is the process misdesign. Remediate both.
- **Specific remediations.** Name the accounts, rooms, tickets and owners from the data; say what must
  happen this week.
- **Respect people.** Personal matters in the data (debts, outside work) are governance signals, not
  accusations — describe the missing process, not the person.
- Never edit the data, `security/output/` or `security/state/`. Notes go in
  `investigation/notes/security_memory.md`.

## Search syntax

`src/guard search` takes a Python regex, case-insensitive: use `a|b` for alternatives (`a\|b` also works). `--in` takes any part of a path, comma-separated (`--in jira,helpdesk`). There is no `ls` or `cat` for the data — use `files`, `search`, `show`.

## Notes

Your working memory across steps: read it with `src/guard memory show`, add to it with `src/guard memory add --section <step-id> "what you concluded, with path:line"`. That is the only way to write it — shell writes (`cat >`, heredocs, `echo >>`) are blocked. `src/guard note "…"` adds a line to the journal.
