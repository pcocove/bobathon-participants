"""Repair the citations of any verdict.json against the bundle as received.

What it fixes automatically (and logs):
  wrong line        the exact quote is in the same file on another line → nearest such line
  out of range      line number past the end of the file → search the file for the quote
  rewritten copy    the quote came from a transformed copy (e.g. timestamps converted): the
                    record is found by its key (first field of a CSV row, a ticket/txn id) and
                    the quote becomes the line exactly as received
  decorated quote   markdown/quote marks added or dropped: the longest exact span of the quote
                    that exists on one line becomes the quote
What it never does: invent text, change claims, reasoning or verdicts. Anything it cannot
resolve is left in place and reported as needing a person.
"""

from __future__ import annotations

import copy
import re

from .corpus import Corpus


def _words_spans(quote: str, min_words: int = 6):
    words = quote.split()
    for n in range(len(words), min_words - 1, -1):
        for i in range(0, len(words) - n + 1):
            yield " ".join(words[i:i + n])


def repair_item(corpus: Corpus, source: str, quote: str) -> dict:
    r = corpus.verify(source, quote)
    out = {"source": source, "quote": quote, "status_before": r["status"], "action": "kept", "status": r["status"]}
    if r["status"] in ("verified", "whitespace", "ocr"):
        return out
    path = re.sub(r":\d+(-\d+)?$", "", source)
    m = re.search(r":(\d+)", source)
    cited = int(m.group(1)) if m else 0
    doc = corpus.get(path)
    if doc is None or doc.kind != "text":
        out["action"] = "needs-human"
        out["why"] = "source file not found or not a text file"
        return out

    def found(line: int, q: str, action: str, why: str) -> dict:
        new = f"{path}:{line}"
        v = corpus.verify(new, q)
        out.update(source=new, quote=q, action=action, why=why, status=v["status"])
        return out

    # 1. exact quote elsewhere in the file (wrong line / out of range)
    hits = [i for i, ln in enumerate(doc.lines, 1) if quote in ln]
    if hits:
        i = min(hits, key=lambda h: abs(h - cited))
        return found(i, quote, "line-fixed", f"quote is on line {i}, not {cited}")
    # 2. a record from a rewritten copy: find the same record by its key
    key = re.match(r"^([A-Z]{2,}[-_]?\d{3,})[,;|]", quote.strip())
    if key:
        rows = [i for i, ln in enumerate(doc.lines, 1) if ln.startswith(key.group(1))]
        if len(rows) == 1:
            i = rows[0]
            return found(i, doc.lines[i - 1].strip(), "record-requoted",
                         f"record {key.group(1)} quoted as received (the old quote came from a rewritten copy)")
    # 3. the longest exact span of the quote that sits on a single line
    for span in _words_spans(quote):
        lines = [i for i, ln in enumerate(doc.lines, 1) if span in ln]
        if len(lines) >= 1:
            i = min(lines, key=lambda h: abs(h - cited))
            return found(i, span, "span-requoted", f"longest exact span of the quote found on line {i}")
    out["action"] = "needs-human"
    out["why"] = "no exact span of the quote exists in the file"
    return out


def repair_verdict(corpus: Corpus, verdict: dict) -> tuple[dict, list[dict]]:
    new = copy.deepcopy(verdict)
    log = []
    for s in new.get("suspects", []):
        for e in s.get("evidence", []):
            res = repair_item(corpus, e.get("source", ""), e.get("quote", ""))
            if res["action"] != "kept":
                log.append({"suspect": s.get("name"), "claim": e.get("claim", "")[:80],
                            "from": {"source": e.get("source"), "quote": e.get("quote")},
                            "to": {"source": res["source"], "quote": res["quote"]},
                            "action": res["action"], "why": res.get("why", ""), "status": res["status"]})
                if res["action"] != "needs-human":
                    e["source"], e["quote"] = res["source"], res["quote"]
    return new, log
