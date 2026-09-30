"""Bob Investigator — an automated, citation-first investigator for case bundles.

The pipeline retraces the manual method generically:

  1. ingest       read every source exactly as received (line numbers untouched)
  2. context      derive the case frame (suspects, windows, site, withheld facts)
  3. sweep        inconsistency sweep: hints in the sources + observed contradictions,
                  fixed or turned into tasks BEFORE any argument is built
  4. analyse      presence, statements vs paperwork, knowledge routes, links
  5. argue        classify every finding per suspect, apply the constraints
  6. adversarial  try to break the case; downgrade overstatements
  7. tasks        mechanical work for the agent, judgement calls for the human
  8. verdict      verdict.json with verified quotes + a verification report
"""

__version__ = "0.1.0"
