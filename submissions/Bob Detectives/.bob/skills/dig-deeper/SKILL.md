---
name: dig-deeper
description: Use when the user asks Bob to dig deeper, double-check, or find out more about a finding (F-xxx), an inconsistency (I-xx), a challenge (R-xx), a suspect, or a cited line (path:line).
---

# Dig deeper

1. Run `src/investigate dig <target>`. Read the cited lines in context, what the same person did around
   those moments, and where the evidence's identifiers appear elsewhere.
2. Pursue the listed questions: search other sources (`src/investigate search "<regex>" --in <prefix>`),
   read around hits (`src/investigate show <path:line> -C 5`), check the order of events
   (`src/investigate timeline --suspect "<name>"`).
3. Conclude:
   - on a proposal or inconsistency: `src/investigate review <target> accept|reject|amend|escalate --note "…"`;
   - anything new: `src/investigate finding add …` (the quote gate rejects what is not there).
4. Append the result to `investigation/notes/case_memory.md`.
5. Answer the user's question in two or three sentences, citing `path:line`.
