---
name: work-playbook-step
description: Use when the user asks Bob to work, continue or finish an investigation playbook step (frame, sweep, suspect:<handle>, crosscheck, challenge, verdict), or to "review the proposals" for a suspect.
---

# Work a playbook step

1. Run `src/investigate playbook` and pick the step the user named, or the first one that is not done.
2. Run `src/investigate step show <ID>` and read the goal, instructions and open items.
3. Read `investigation/notes/case_memory.md` if it exists.
4. For every open item: `src/investigate dig <ID>`, check the sources, then record your decision with
   `src/investigate review <ID> accept|reject|amend|escalate --note "…"`.
5. Go deeper where it matters: search other files and formats for the record that confirms or explains
   each suspicion; add it with `src/investigate finding add … ` (quotes are verified).
6. Append what you concluded to `investigation/notes/case_memory.md`.
7. `src/investigate step done <ID> --summary "…"`, then `src/investigate run --quiet` and report in three
   lines: decisions, additions, what remains doubtful.
