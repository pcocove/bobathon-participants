---
name: guard-triage
description: Use when the user asks Bob to triage security risks, review the risk register, check whether a weakness is still open, or work a Security Guard playbook step (scope, triage, hunt, rootcause, remediate, challenge, report).
---

# Triage security risks

1. `src/guard playbook` — pick the step the user named, or the first one not done; `src/guard step show <ID>`.
2. Read `investigation/notes/security_memory.md` if it exists.
3. For each open item: `src/guard dig <ID>`, then search for a later fix (`src/guard search "<subject>"`).
4. Decide: `src/guard review <ID> accept|reject|amend --note "…"` (re-rate with `--severity`, close with
   `--state addressed` only when a record shows the fix).
5. Add what the scanner missed with `src/guard finding add … ` (quotes are verified).
6. Append conclusions to `investigation/notes/security_memory.md`; `src/guard step done <ID> --summary "…"`;
   `src/guard run --quiet`; report in three lines.
