"""Command line: python -m alibi.cli <command>

  ingest                 rebuild inventory and units
  status                 Bob connection and usage
  packages               show labeling packages (no Bob)
  run [stages…] [--force] run pipeline stages (vision label frame persons synthesis crosscheck prevention export);
                         without stage names only missing stages run
  label-one P01          run a single labeling package (measurement)
  export [--write]       build the export draft; with --write write submissions/<team>/verdict.json
  snapshot NAME          copy the current analysis to state/runs/NAME (repeat-run comparison)
  compare A B            compare two stored runs (verdicts, confidences, leading hypothesis)
  reresolve              re-check all stored evidence against the original files (no Bob calls)
  translate              let Bob translate stored German analysis text to English (cached)
"""
from __future__ import annotations

import sys

from .pipeline import Progress


class CliProgress(Progress):
    def stage(self, key, label, total):
        print(f"\n== {label} ({total})", flush=True)

    def step(self, n=1, msg=None):
        if msg:
            print("  ·", msg, flush=True)

    def log(self, msg):
        print("  ", msg, flush=True)


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "ingest":
        from .ingest import run_ingest
        inv = run_ingest()
        print(inv["unit_count"], "units")
    elif cmd == "status":
        from .bob_adapter import bob_status, ledger_summary
        print(bob_status(force=True))
        print(ledger_summary())
    elif cmd == "packages":
        from .corpus import Corpus
        from .pipeline import build_packages
        pk = build_packages(Corpus())
        for p in pk:
            print(p["id"], len(p["units"]), len(p["text"]))
        print(len(pk), "packages,", sum(len(p["text"]) for p in pk), "characters")
    elif cmd == "label-one":
        from .bob_adapter import run_bob
        from .corpus import Corpus
        from .pipeline import build_packages, fill, tpl, _v_label
        from . import sources
        c = Corpus()
        pk = {p["id"]: p for p in build_packages(c)}[rest[0]]
        prompt = fill(tpl("02_label_package.md"), PACKAGE=f"{pk['id']}", RULES=tpl("00_common_rules.md"),
                      CASE_README="\n".join(sources.raw_lines("README.md")), PEOPLE=c.people_table(), MAX_UNITS=40, UNITS=pk["text"])
        rec = run_bob("label", f"Label {pk['id']} (measurement)", prompt, _v_label(c, set(pk["units"])))
        print(rec["status"], rec.get("spend"), [t.get("elapsed_s") for t in rec["turns"]], rec.get("validation"), rec.get("error"))
        print("reported:", len((rec.get("parsed") or {}).get("units") or []))
    elif cmd == "run":
        from .pipeline import run_pipeline
        force = "--force" in rest
        stages = [x for x in rest if not x.startswith("--")] or None
        run_pipeline(CliProgress(), stages, force=force)
    elif cmd == "export":
        from .export import build_draft, write_final
        if "--write" in rest:
            r = write_final()
            print("written" if r["written"] else "NOT written", r.get("path", ""), r["report"]["errors"][:10])
        else:
            d = build_draft()
            print(d["report"]["valid"], d["report"]["errors"][:10], d["notes"][:10])
    elif cmd == "reresolve":
        from .maintenance import reresolve
        print(reresolve())
    elif cmd == "translate":
        from .maintenance import translate
        print(translate(force="--force" in rest))
    elif cmd == "snapshot":
        import shutil
        from .corpus import AN
        dst = AN.parent / "runs" / rest[0]
        dst.mkdir(parents=True, exist_ok=True)
        for name in ("frame.json", "synthesis.json", "crosscheck.json", "final.json", "prevention.json", "verdict_draft.json", "meta.json"):
            if (AN / name).exists():
                shutil.copy2(AN / name, dst / name)
        if (AN / "persons").exists():
            shutil.copytree(AN / "persons", dst / "persons", dirs_exist_ok=True)
        print("saved:", dst)
    elif cmd == "compare":
        import json
        from .corpus import AN, Corpus
        c = Corpus()
        runs = [AN.parent / "runs" / r for r in rest[:2]]
        def load(r, name):
            p = r / name
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        fa, fb = load(runs[0], "final.json"), load(runs[1], "final.json")
        print(f"{'Person':22} {'Run A':28} {'Run B':28}")
        for h in c.suspects:
            pa = load(runs[0], f"persons/{h}.json").get("result") or {}
            pb = load(runs[1], f"persons/{h}.json").get("result") or {}
            va = next((p.get("verdict") for p in fa.get("persons", []) if p.get("id") == h), None)
            vb = next((p.get("verdict") for p in fb.get("persons", []) if p.get("id") == h), None)
            print(f"{c.person_by_id[h]['name']:22} {str(pa.get('conclusion'))+' '+str(pa.get('exoneration_confidence'))+' '+str(va):28} "
                  f"{str(pb.get('conclusion'))+' '+str(pb.get('exoneration_confidence'))+' '+str(vb):28}")
        print("Leading:", fa.get("leading"), "|", fb.get("leading"))
        print("Verdict confidence:", fa.get("verdict_confidence"), "|", fb.get("verdict_confidence"))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
