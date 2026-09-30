"""Tests: quotes verified, traps tried, repeat runs identical, nothing typed in.

Run from the repo root:  python3 -m unittest discover -s src/tests -v
They need the case bundle (auto-detected); without it they are skipped.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from investigator import pipeline  # noqa: E402
from investigator.corpus import Corpus  # noqa: E402
from investigator.verdict import verify_file  # noqa: E402

REPO = SRC.parent
DATA = pipeline.find_data_root(REPO)

try:
    _PATHS = pipeline.make_paths(repo=str(REPO), workdir=tempfile.mkdtemp(prefix="inv-test-"))
except SystemExit:
    _PATHS = None


@unittest.skipIf(_PATHS is None, "case bundle not found")
class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = _PATHS
        cls.inv = pipeline.run(cls.paths, team="test", log=lambda m: None)
        cls.verdict = json.loads((cls.paths.output / "verdict.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.paths.workdir, ignore_errors=True)

    # --- the scorer's checks -------------------------------------------------
    def test_every_verdict_quote_is_at_its_source(self):
        rep = verify_file(Corpus(self.paths.bundle), self.verdict)
        bad = [r for r in rep["rows"] if r["status"] != "verified"]
        self.assertEqual(bad, [], f"quotes not found: {bad[:3]}")
        self.assertGreater(rep["total"], 8)

    def test_all_suspects_judged_with_evidence(self):
        names = [s["name"] for s in json.loads((DATA / "verdict_template.json").read_text())["suspects"]]
        self.assertEqual(sorted(s["name"] for s in self.verdict["suspects"]), sorted(names))
        for s in self.verdict["suspects"]:
            self.assertIn(s["verdict"], ("culprit", "cleared", "unresolved"))
            if s["verdict"] != "unresolved":
                self.assertTrue(s["evidence"], f"{s['name']} judged without evidence")

    def test_confidence_is_honest(self):
        c = self.verdict["confidence"]
        self.assertTrue(0.05 <= c <= 0.95, c)
        culprits = [s for s in self.verdict["suspects"] if s["verdict"] == "culprit"]
        self.assertEqual(len(culprits), 1)
        self.assertEqual(culprits[0]["name"], self.verdict["culprit"])

    # --- traps ----------------------------------------------------------------
    def test_misleading_suspects_are_explained_not_accused(self):
        res = self.inv.results["argue"]
        for p in res["profiles"]:
            if p["echo"] == "explained":
                self.assertNotEqual(p["verdict"], "culprit", p["name"])
        # every explained echo carries its route as evidence
        for f in self.inv.store.findings:
            if f.explains:
                self.assertTrue(any(e.usable or e.status == "ocr" for e in f.evidence), f.title)

    def test_unexplained_echo_predates_every_leak(self):
        for f in self.inv.store.findings:
            if f.constraint == "echo" and f.cls == "INCRIMINATES":
                p = self.inv.person(f.suspect)
                spoke = min(iv.started for iv in p.interviews if iv.started)
                for lk in self.inv.leaks:
                    if any(a["person"] == p.key for a in lk.audience):
                        self.assertGreater(lk.t, spoke)

    def test_answer_survives_leaving_out_any_single_analysis(self):
        rows = self.inv.results["robustness"]
        self.assertTrue(rows)
        self.assertTrue(all(r["same"] for r in rows), [r for r in rows if not r["same"]])

    def test_sweep_runs_before_analysis_and_fixes_are_listed(self):
        stages = [s["stage"] for s in self.inv.stage_log]
        self.assertLess(stages.index("sweep"), stages.index("analyse"))
        for i in self.inv.store.issues:
            if i.kind == "sweep" and i.resolution == "fixed":
                self.assertTrue(i.fix, i.title)

    def test_agent_findings_with_fake_quotes_are_rejected(self):
        res = pipeline.add_agent_finding(self.paths, {
            "suspect": self.verdict["suspects"][0]["name"], "constraint": "lead", "cls": "EXONERATES",
            "title": "invented", "claim": "invented",
            "evidence": [{"source": "investigator_notebook.md:1", "quote": "this sentence is not in the notebook"}]})
        self.assertFalse(res["accepted"])

    # --- reproducibility -----------------------------------------------------
    def test_repeat_run_gives_identical_verdict(self):
        again = pipeline.run(self.paths, team="test", log=lambda m: None)
        v2 = json.loads((self.paths.output / "verdict.json").read_text(encoding="utf-8"))
        self.assertEqual(self.verdict, v2)
        self.assertEqual(self.inv.results["argue"]["confidence"], again.results["argue"]["confidence"])


@unittest.skipIf(_PATHS is None, "case bundle not found")
class RepairTests(unittest.TestCase):
    def test_repair_fixes_shifted_and_rewritten_citations_without_inventing_text(self):
        from investigator.repair import repair_verdict
        c = Corpus(_PATHS.bundle)
        doc = next(d for p, d in c.docs.items() if p.endswith(".csv") and len(d.lines) > 50)
        n = next(i for i, l in enumerate(doc.lines, 1) if i > 10 and "," in l and not l.startswith("#"))
        line = doc.lines[n - 1]
        key = line.split(",")[0]
        rewritten = key + ",REWRITTEN-VALUE," + ",".join(line.split(",")[2:])
        v = {"suspects": [{"name": "x", "verdict": "cleared", "reasoning": "", "evidence": [
            {"claim": "shifted", "source": f"{doc.path}:{n + 3}", "quote": line},
            {"claim": "rewritten", "source": f"{doc.path}:{n}", "quote": rewritten},
            {"claim": "invented", "source": f"{doc.path}:{n}", "quote": "nothing like this exists anywhere"}]}]}
        new, log = repair_verdict(c, v)
        ev = new["suspects"][0]["evidence"]
        self.assertEqual(ev[0]["source"], f"{doc.path}:{n}")
        self.assertEqual(ev[1]["quote"], line.strip())
        self.assertEqual(ev[2]["quote"], "nothing like this exists anywhere")  # left for a human
        self.assertEqual([x["action"] for x in log], ["line-fixed", "record-requoted", "needs-human"])
        self.assertEqual(new["suspects"][0]["evidence"][0]["claim"], "shifted")  # claims untouched

    def test_repo_verdict_files_verify(self):
        from investigator.verdict import verify_file
        c = Corpus(_PATHS.bundle)
        for f in [REPO / "verdict.json", REPO / "verdict_investigator.json"]:
            if f.exists():
                rep = verify_file(c, json.loads(f.read_text(encoding="utf-8")))
                self.assertTrue(rep["all_verified"], f"{f.name}: {rep['counts']}")


class AcpPolicyTests(unittest.TestCase):
    """What Bob may do inside the environment."""

    def setUp(self):
        from investigator.acp import BobSession
        self.s = BobSession(REPO, Path(tempfile.mkdtemp()) / "log.jsonl")

    def allowed(self, kind, **raw):
        return self.s.policy({"kind": kind, "rawInput": raw, "locations": [{"path": raw["path"]}] if "path" in raw else []})[0]

    def test_cli_commands_allowed(self):
        self.assertTrue(self.allowed("execute", command='src/investigate proposals --suspect "X"'))
        self.assertTrue(self.allowed("execute", command="src/investigate search 'a|b' --in slack_export/ | head -20"))
        self.assertTrue(self.allowed("execute", command=f"cd {REPO} && src/investigate status"))
        self.assertTrue(self.allowed("execute", command="src/guard proposals --constraint stale-access"))
        self.assertTrue(self.allowed("execute", command='src/investigate note "routes: (1) list of 5; Dov away & (2) board pack > slide 11"'))
        self.assertTrue(self.allowed("execute", command="src/guard search 'a|b' --in jira | grep -i open | head -5"))
        self.assertTrue(self.allowed("execute", command='ls investigation/notes/case_memory.md 2>/dev/null && cat investigation/notes/case_memory.md || echo "FILE_NOT_FOUND"'))
        self.assertTrue(self.s.policy({"kind": "other", "rawInput": {"todos": "[ ] read notes"}})[0])
        self.assertFalse(self.s.policy({"kind": "other", "rawInput": {"server": "x", "tool": "y"}})[0])
        self.assertTrue(self.allowed("execute", command=f"cd {REPO} && src/investigate playbook 2>&1 | head -60"))
        self.assertTrue(self.allowed("execute", command='cat investigation/notes/case_memory.md 2>/dev/null || echo "NO CASE MEMORY YET"'))
        self.assertTrue(self.allowed("execute", command=f'cd {REPO} && src/guard memory show 2>/dev/null || echo "NO MEMORY FILE"'))
        self.assertTrue(self.allowed("execute", command='src/guard memory show 2>/dev/null | head -100 || echo "NO MEMORY"'))
        self.assertTrue(self.allowed("execute", command="src/guard show a.json:967 -C 25 && src/guard show a.json:3247 -C 25"))
        self.assertTrue(self.allowed("execute", command=f'cd {REPO} && src/investigate dig F-057 && echo "---DIG-END---"'))
        self.assertTrue(self.allowed("execute", command="src/guard show a.md:54 -C 30 && src/guard search 'x|y' --in a,b | head -20"))

    def test_everything_else_denied(self):
        for cmd in ["rm -rf investigation", "src/investigate status; rm -rf x", "python3 -c 'print(1)'",
                    "src/investigate run > verdict.json", "git push", "src/investigate status && git commit -am x",
                    "cat investigation/state/reviews.json", "cat investigation/notes/../state/reviews.json",
                    "src/investigate status 2>&1 > out.txt", "cat investigation/notes/x.md; rm -rf /",
                    "cat investigation/notes/x.md && rm -rf investigation", "ls investigation/notes && curl http://x",
                    'src/investigate note "$(rm -rf x)"', "src/investigate note `whoami`", "src/investigate status | sh",
                    "src/investigate status | cat /etc/passwd", "src/guard run & rm -rf x", "src/investigate status | sed -i s/a/b/ f",
                    'src/investigate status || echo "x" > verdict.json', "src/investigate status || rm -rf x",
                    "src/investigate status || echo $(whoami)", "src/investigate status || echo x | sh",
                    "src/investigate status && src/guard status && rm -rf x", "src/guard status && cat investigation/state/reviews.json",
                    "src/guard status && && src/guard status", 'echo "x" && echo "y"', 'src/guard status && echo x > f']:
            self.assertFalse(self.allowed("execute", command=cmd), cmd)

    def test_edits_only_in_notes(self):
        self.assertTrue(self.allowed("edit", path="investigation/notes/case_memory.md"))
        self.assertFalse(self.allowed("edit", path="verdict.json"))
        self.assertFalse(self.allowed("edit", path="src/investigator/argue.py"))
        self.assertFalse(self.allowed("edit", path="investigation/notes/../state/reviews.json"))


@unittest.skipIf(_PATHS is None, "case bundle not found")
class AgentWorkflowTests(unittest.TestCase):
    """Tools propose, the agent decides."""

    def setUp(self):
        self.paths = pipeline.make_paths(repo=str(REPO), workdir=tempfile.mkdtemp(prefix="inv-agent-"))

    def tearDown(self):
        shutil.rmtree(self.paths.workdir, ignore_errors=True)

    def test_untouched_agent_mode_falls_back_to_labelled_baseline(self):
        inv = pipeline.run(self.paths, log=lambda m: None)
        self.assertIn("not reviewed", inv.results["argue"]["basis"])
        self.assertEqual(inv.results["argue"]["culprit"], inv.results["baseline"]["culprit"])
        self.assertTrue((self.paths.output / "verdict_baseline.json").exists())

    def test_only_reviewed_findings_count_and_rejections_withdraw(self):
        from investigator import playbook
        from investigator.workspace import Workspace
        inv = pipeline.run(self.paths, log=lambda m: None)
        culprit = inv.results["baseline"]["culprit"]
        reds = [f for f in inv.store.findings if f.suspect == culprit and f.cls == "INCRIMINATES"]
        ws = Workspace(self.paths.state)
        ws.review(reds[0].key, "accept", "checked the source", by="test")
        ws.review(reds[1].key, "reject", "test rejection", by="test")
        inv2 = pipeline.run(self.paths, log=lambda m: None)
        counted = [f for f in inv2.store.findings if f.suspect == culprit and f.counts]
        self.assertEqual([f.key for f in counted], [reds[0].key])
        self.assertEqual(next(f for f in inv2.store.findings if f.key == reds[1].key).status, "withdrawn")
        self.assertIn("agent-reviewed", inv2.results["argue"]["basis"])
        # IDs are stable across runs
        self.assertEqual({f.key: f.id for f in inv.store.findings if f.key in {r.key for r in reds}},
                         {f.key: f.id for f in inv2.store.findings if f.key in {r.key for r in reds}})
        # the suspect's playbook step lists the rest as open
        st = json.loads((self.paths.output / "investigation.json").read_text())
        step = playbook.find(st, f"suspect:{culprit}")
        prog = playbook.progress(step, st, Workspace(self.paths.state))
        self.assertFalse(prog["complete"])
        self.assertFalse(any(reds[0].id in m for m in prog["missing"]))

    def test_agent_verdict_draft_is_used_with_its_reasoning(self):
        from investigator.workspace import Workspace
        inv = pipeline.run(self.paths, log=lambda m: None)
        name = inv.case.suspects[0].name
        Workspace(self.paths.state).draft_verdict(name, "unresolved", "test reasoning from the agent", [], by="test")
        pipeline.run(self.paths, log=lambda m: None)
        v = json.loads((self.paths.output / "verdict.json").read_text())
        s = next(x for x in v["suspects"] if x["name"] == name)
        self.assertEqual((s["verdict"], s["reasoning"]), ("unresolved", "test reasoning from the agent"))


@unittest.skipIf(_PATHS is None, "case bundle not found")
class SecurityGuardTests(unittest.TestCase):
    """The proactive agent: same framework, no suspects."""

    @classmethod
    def setUpClass(cls):
        from investigator import guard
        cls.base = Path(tempfile.mkdtemp(prefix="pair-"))      # investigation workdir; the Guard pairs as <base>/security
        cls.paths = pipeline.make_paths(repo=str(REPO), workdir=str(cls.base / "security"))
        cls.inv = guard.run(cls.paths, log=lambda m: None)
        cls.state = json.loads((cls.paths.output / "investigation.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def risks(self):
        return [f for f in self.inv.store.findings if f.meta.get("kind") == "risk" and f.status != "withdrawn"]

    def test_runs_without_suspects(self):
        self.assertEqual(self.inv.case.suspects, [])
        self.assertTrue(self.risks())

    def test_every_risk_is_cited_and_rated(self):
        from investigator import security_lexicon as SL
        for f in self.risks():
            self.assertTrue(f.evidence, f.title)
            self.assertTrue(all(e.usable or e.status == "ocr" for e in f.evidence), f.title)
            self.assertIn(f.meta["severity"], SL.SEVERITY)
            self.assertIn(f.meta["state"], ("open", "check", "addressed"))
            self.assertTrue(f.id.startswith("S-"))

    def test_root_causes_and_remediations_cover_the_open_risks(self):
        rcs = [i for i in self.inv.store.issues if i.kind == "rootcause"]
        rems = [i for i in self.inv.store.issues if i.kind == "remediation"]
        self.assertTrue(rcs)
        self.assertEqual({r.category for r in rems}, {r.category for r in rcs})
        covered = {k for rc in rcs for k in rc.affects}
        crit = [f for f in self.risks() if f.meta["severity"] == "critical" and f.meta["state"] == "open"]
        self.assertTrue(crit)
        self.assertTrue(all(f.key in covered for f in crit), "every open critical risk traces to a root cause")
        self.assertTrue(any(t.topic == "remediation" for t in self.inv.tasks.tasks), "critical plans need approval")

    def test_agent_can_rerate_a_risk(self):
        from investigator import guard
        from investigator.workspace import Workspace
        f = self.risks()[0]
        Workspace(self.paths.state).review(f.key, "amend", "test re-rating", by="test", severity="low", state="addressed")
        inv2 = guard.run(self.paths, log=lambda m: None)
        g = next(x for x in inv2.store.findings if x.key == f.key)
        self.assertEqual((g.meta["severity"], g.meta["state"]), ("low", "addressed"))

    def test_guard_playbook_has_a_triage_step_per_category(self):
        from investigator import guard_playbook
        from investigator.workspace import Workspace
        steps = guard_playbook.steps_for(self.state)
        cats = {f.meta["category"] for f in self.risks() if f.stage in ("sweep", "analyse")}
        self.assertEqual({s.id for s in steps if s.id.startswith("triage:")}, {f"triage:{c}" for c in cats})
        prog = guard_playbook.progress(guard_playbook.find(self.state, "remediate"), self.state, Workspace(self.paths.state))
        self.assertFalse(prog["complete"])

    def test_investigator_reports_remaining_flaws_with_the_guards_ids(self):
        inv = pipeline.run(pipeline.make_paths(repo=str(REPO), workdir=str(self.base)), log=lambda m: None)
        sec = inv.results["security"]
        self.assertTrue(sec["risks"] and sec["rootcauses"] and sec["remediations"])
        self.assertTrue((inv.paths.context_dir / "10_security_remaining.md").exists())
        guard_ids = {f.key: f.id for f in self.inv.store.findings}
        shared = [r for r in sec["risks"] if r["key"] in guard_ids]
        self.assertTrue(shared)
        self.assertTrue(all(guard_ids[r["key"]] == r["id"] for r in shared))

    def test_no_case_facts_in_security_code(self):
        code = "\n".join((SRC / "investigator" / n).read_text(encoding="utf-8") for n in
                         ("security.py", "security_lexicon.py", "guard.py", "guard_playbook.py", "report_guard.py"))
        text = "\n".join("\n".join(d.lines) for d in Corpus(self.paths.bundle).docs.values() if d.kind == "text")
        ticket_ids = set(re.findall(r"\b[A-Z]{2,6}-\d{2,5}\b", text))                 # ticket / request identifiers
        orgs = {m.split("-")[0] for m in re.findall(r"@([a-z0-9-]+)\.[a-z]{2,}", text.lower())}   # company names from mail domains
        self.assertTrue(ticket_ids and orgs)
        for token in sorted(ticket_ids | orgs):
            self.assertIsNone(re.search(rf"\b{re.escape(token)}\b", code, re.I), token)
        names = [s["name"] for s in json.loads((DATA / "verdict_template.json").read_text())["suspects"]]
        for n in names:
            for w in n.split():
                self.assertIsNone(re.search(rf"\b{re.escape(w)}\b", code, re.I), w)


class ConcurrencyTests(unittest.TestCase):
    def test_parallel_writers_lose_nothing(self):
        """Bob's CLI, pipeline refreshes, the UI and the other agent write the workspace at once."""
        import subprocess
        d = tempfile.mkdtemp()
        code = ("import sys; sys.path.insert(0, %r)\n"
                "from pathlib import Path\nfrom investigator.workspace import Workspace\n"
                "w = Workspace(Path(sys.argv[1])); n = int(sys.argv[2])\n"
                "for i in range(15):\n"
                "    w.review(f'k{n}-{i}', 'accept', 'x', by=f'p{n}')\n"
                "    w.assign_all([('S', f'key{n}-{i}', 3), ('S', 'shared', 3)])\n") % str(SRC)
        ps = [subprocess.Popen([sys.executable, "-c", code, d, str(n)]) for n in range(5)]
        for p in ps:
            self.assertEqual(p.wait(), 0)
        reviews = json.loads((Path(d) / "reviews.json").read_text())
        ids = json.loads((Path(d) / "ids.json").read_text())["S"]
        self.assertEqual(len(reviews), 75)
        self.assertEqual(len(ids), 76)
        self.assertEqual(len(set(ids.values())), len(ids))
        shutil.rmtree(d, ignore_errors=True)


class NothingTypedInTests(unittest.TestCase):
    """Rule 2: case facts must come from the bundle, not from the code."""

    def test_no_suspect_names_or_identifiers_in_code(self):
        tmpl = DATA / "verdict_template.json"
        if not tmpl.exists():
            self.skipTest("no template")
        names = [s["name"] for s in json.loads(tmpl.read_text())["suspects"]]
        tokens = {w.lower() for n in names for w in n.split() if len(w) > 3}
        code = "\n".join(p.read_text(encoding="utf-8") for p in (SRC / "investigator").rglob("*.py"))
        code += (SRC / "investigator" / "web" / "app.js").read_text(encoding="utf-8")
        found = sorted(t for t in tokens if re.search(rf"\b{re.escape(t)}\b", code, re.I))
        self.assertEqual(found, [], f"suspect names typed into code: {found}")

    def test_no_plates_cards_or_timestamps_typed_in(self):
        code = "\n".join(p.read_text(encoding="utf-8") for p in (SRC / "investigator").rglob("*.py"))
        self.assertIsNone(re.search(r"\b[A-Z]{2} \d{1,3} \d{3}\b", code), "number plate in code")
        self.assertIsNone(re.search(r"\b\d{2}\.\d{2}\.2025\b|2025-1[01]-\d{2}", code), "case date in code")


class CorpusTests(unittest.TestCase):
    def test_normalised_copy_is_refused(self):
        norm = next((d for d in sorted(DATA.glob("*normalised*")) if d.is_dir()), None)
        if norm is None:
            self.skipTest("no normalised copy")
        with self.assertRaises(SystemExit):
            pipeline.make_paths(bundle=str(norm), repo=str(REPO), workdir=tempfile.mkdtemp())

    @unittest.skipIf(_PATHS is None, "case bundle not found")
    def test_verify_statuses(self):
        c = Corpus(_PATHS.bundle)
        doc = next(d for d in c.docs.values() if d.kind == "text" and len(d.lines) > 20)
        line = next(i for i, l in enumerate(doc.lines, 1) if len(l.strip()) > 20)
        q = doc.lines[line - 1].strip()[:20]
        self.assertEqual(c.verify(f"{doc.path}:{line}", q)["status"], "verified")
        self.assertEqual(c.verify(f"{doc.path}:{line}", "zz not here zz")["status"], "not-found")
        other = next(i for i, l in enumerate(doc.lines, 1) if i > line + 2 and len(l.strip()) > 20 and q not in l)
        r = c.verify(f"{doc.path}:{other}", q)
        self.assertIn(r["status"], ("wrong-line", "not-found"))


if __name__ == "__main__":
    unittest.main()
