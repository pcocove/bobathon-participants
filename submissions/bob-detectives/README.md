# Bob Detectives

Two IBM Bob agents on one citation-first framework:

- **Investigator** (`src/investigate`): who did it, how sure, and where every piece of reasoning comes from.
- **Security Guard** (`src/guard`): no suspects, just the data. What is still weak today, which process
  misdesign lets it happen, and what to do about it.

**Tools propose, Bob decides.** The tools read every source exactly as received, sweep for
inconsistencies first (clocks, time bases, degraded records, leak channels) and turn the bundle into
proposals. Bob works a playbook step by step over the local CLI (`bob acp`): he reviews each proposal
with a note, digs deeper where it matters, adds what the tools missed (every quote verified) and drafts
the verdict. A person signs off the judgement calls. The UI links every claim to the cited line in the
original document.

| File | What it is |
|---|---|
| `verdict.json` | our hand-in: all eight suspects, every quote checked against the bundle as received |
| `src/` | the framework: corpus + quote gate, record parsers, sweep, analysis, playbooks, Bob orchestrator, web UI, tests |
| `src/README.md` | full documentation: pipeline, CLI, UI, Bob inside the system |
| `src/METHOD.md` | how we solved it by hand, retraced without case specifics, and how that became the system |
| `.bob/` | Bob custom modes (`investigator`, `securityguard`), their rules and skills |

No run outputs are included; they are generated into `investigation/` and `security/` (git-ignored).

## Run it

From this folder (Python 3, standard library; `pypdf` for PDF text):

```bash
pip install -r src/requirements.txt
src/investigate run            # tools-only baseline: frame, sweep, findings, verdict, context docs (seconds)
src/guard run                  # security scan: risks, root causes, remediations
src/investigate serve --open   # UI for both agents, every claim linked to its source
python3 -m unittest discover -s src/tests
```

The case bundle, `verdict_template.json` and the handout are found in the repository root
automatically (`--bundle PATH` overrides). Only the bundle as received is used, never a rewritten copy.

With IBM Bob installed and logged in (`bob`, then sign in):

```bash
src/investigate agent run      # Bob works the Investigator playbook
src/guard agent run            # Bob works the Security Guard playbook
```

Bob may only run the CLI and write his own notes. Every other command, and any edit to the data,
outputs or state, is refused by the permission policy (`src/investigator/acp.py`).

## Rule 2: declared inputs

The only typed-in case input is the suspect list from `verdict_template.json`. The tests fail if suspect
names, number plates, case dates, ticket IDs or company names from the bundle appear in the code.
