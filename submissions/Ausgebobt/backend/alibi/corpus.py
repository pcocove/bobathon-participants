"""Shared access to units, people and labels; rendering for Bob; search; evidence resolution."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from functools import cached_property

from . import sources
from .config import SETTINGS, template_names
from .ingest import DOC_TYPES, People
from .store import read_json

ST = SETTINGS.state_dir
AN = ST / "analysis"

REL_RANK = {"hoch": 3, "mittel": 2, "niedrig": 1}
STOP = set("""der die das und oder ein eine einer eines den dem des zu im in am an auf aus mit von für ist war wer wie was wann wo
the a an and or of to in on at for is was who how what when where with from by that this it as be are were not""".split())


class Corpus:
    def __init__(self):
        self.units: list[dict] = read_json(ST / "units.json", [])
        self.persons: list[dict] = read_json(ST / "persons.json", [])
        self.by_id = {u["id"]: u for u in self.units}
        self.person_by_id = {p["id"]: p for p in self.persons}
        self.labels: dict = read_json(AN / "labels.json", {})
        self.vision: dict = read_json(AN / "vision.json", {})
        self.suspect_names = template_names()
        self.suspects = [People.handle_from_name(n) for n in self.suspect_names]
        self._file_index: dict[str, list] = {}
        for u in self.units:
            if u["loc"]["type"] == "lines":
                self._file_index.setdefault(u["file"], []).append((u["loc"]["start"], u["loc"]["end"], u["id"]))

    # ------------------------------------------------------------------ Personen
    def person_handle(self, ref: str) -> str | None:
        """Kennung, Name oder Alias → Kennung."""
        if not ref:
            return None
        r = ref.strip()
        if r.startswith("person:"):
            r = r[7:]
        low = r.lower()
        if low in self.person_by_id:
            return low
        for p in self.persons:
            if p["name"].lower() == low:
                return p["id"]
            for a in p["aliases"]:
                if a["value"].lower() == low:
                    return p["id"]
        h = People.handle_from_name(r)
        return h if h in self.person_by_id else None

    def people_table(self) -> str:
        rows = []
        for p in self.persons:
            al = [a["value"] for a in p["aliases"] if a["kind"] in ("slack_id", "email", "plate")]
            tag = " [under review]" if p["suspect"] else ""
            title = f" – {p['titles'][0]['value']}" if p.get("titles") else ""
            rows.append(f"{p['id']} – {p['name']}{title}{tag}" + (f" – {', '.join(al)}" if al else ""))
        return "\n".join(rows)

    def unit_people(self, u: dict) -> list[str]:
        out = []
        for x in u["people"]:
            if x.get("person") and x["person"] not in out:
                out.append(x["person"])
        lab = self.labels.get(u["id"])
        if lab:
            for x in lab.get("persons", []):
                if x.get("id") and x["id"] not in out:
                    out.append(x["id"])
        return out

    # ------------------------------------------------------------------ Zeit
    @staticmethod
    def unit_time(u: dict) -> str | None:
        for t in u.get("times") or []:
            if t and t.get("local"):
                return t["local"]
        return None

    @staticmethod
    def parse_local(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            d = datetime.fromisoformat(s[:19] if "T" in s else s[:10])
            return d.replace(tzinfo=None)
        except ValueError:
            return None

    def in_window(self, u: dict, start: datetime, end: datetime) -> bool:
        for t in u.get("times") or []:
            d = self.parse_local(t.get("local"))
            if d is None:
                continue
            if t.get("precision") == "date":
                if start.date() <= d.date() <= end.date():
                    return True
            elif start <= d <= end:
                return True
        return False

    # ------------------------------------------------------------------ Rendering
    def render(self, u: dict, with_lines: bool = True, max_lines: int = 60) -> str:
        dt = DOC_TYPES.get(u["doc_type"], u["doc_type"])
        head = f"### [{u['id']}] {dt} · {u['file']}"
        if u["loc"]["type"] == "page":
            head += f" · page {u['loc']['page']}"
        if u["loc"]["type"] == "row":
            head += f" · Excel row {u['loc']['row']} (sheet {u['loc'].get('sheet')})"
        if u["title"] and u["doc_type"] not in ("garage", "card", "expense", "diligence"):
            head += f" · {u['title'][:90]}"
        parts = [head]
        if u["times"]:
            t = u["times"][0]
            parts.append(f"Time: {t['original']} → {t['local']} ({t['basis']})")
        ppl = []
        for x in u["people"][:10]:
            if x.get("person"):
                ppl.append(f"{x['person']}[{x.get('role') or x.get('basis')}; {x.get('via')}]" if x.get("basis") in ("vehicle", "vehicle_uncertain", "name_part") else f"{x['person']}[{x.get('role') or x.get('basis')}]")
            elif x.get("list"):
                ppl.append(f"{x['list']}[{x.get('role')}]")
        if ppl:
            parts.append("People: " + ", ".join(ppl))
        if not with_lines:
            return "\n".join(parts)
        loc = u["loc"]
        if loc["type"] == "lines":
            lines = sources.raw_lines(u["file"])
            a, b = loc["start"], loc["end"]
            nums = list(range(a, b + 1))
            if u["doc_type"] == "slack":
                nums = [loc.get("focus", a)]
            elif u["doc_type"] == "calendar":
                nums = [n for n in nums if re.match(r"^(SUMMARY|DTSTART|DTEND|DESCRIPTION|LOCATION|ORGANIZER)", lines[n - 1])]
            elif u["doc_type"] == "jira":
                nums = [n for n in nums if lines[n - 1].strip() not in ("{", "}", "},", "[", "]", "],", '"fields": {', '"comments": [')]
            if len(nums) > max_lines:
                nums = nums[:max_lines]
                parts.extend(f"L{n}: {lines[n - 1]}" for n in nums)
                parts.append(f"… (truncated, unit continues to L{b})")
            else:
                parts.extend(f"L{n}: {lines[n - 1]}" for n in nums)
        elif loc["type"] == "page":
            if u["doc_type"] == "scan":
                parts.extend(self._vision_lines(u))
            else:
                parts.append(u["raw"])
        elif loc["type"] == "row":
            parts.append(f"R{loc['row']}: {u['raw']}")
        elif loc["type"] == "file":
            parts.extend(self._vision_lines(u))
        return "\n".join(parts)

    def _vision_lines(self, u: dict) -> list[str]:
        v = self.vision.get(u["id"])
        if not v:
            return ["(Bildinhalt noch nicht ausgewertet)"]
        out = ["BOB VISION TRANSCRIPT (uncertain, not exactly verifiable):"]
        out.extend(f"T{i}: {ln}" for i, ln in enumerate(v.get("transcript_lines", []), start=1))
        if v.get("description"):
            out.append(f"Image description (Bob): {v['description']}")
        return out

    def render_label(self, uid: str) -> str:
        u = self.by_id[uid]
        lab = self.labels.get(uid, {})
        t = self.unit_time(u) or (lab.get("time") or {}).get("local") or "—"
        ppl = ",".join(self.unit_people(u)[:6])
        return f"[{uid}] ({t}) {lab.get('summary', u['title'])} | {','.join(lab.get('tags', []))} | {ppl}"

    # ------------------------------------------------------------------ Suche
    @cached_property
    def _search_text(self) -> dict[str, str]:
        out = {}
        for u in self.units:
            extra = " ".join(self.unit_people(u))
            vis = self.vision.get(u["id"], {})
            vt = " ".join(vis.get("transcript_lines", [])) + " " + vis.get("description", "")
            plates = " ".join(re.sub(r"[^A-Z0-9]", "", str(v).upper()) for k, v in (u.get("fields") or {}).items()
                              if isinstance(v, str) and k and k.lower() in ("kennzeichen",))
            out[u["id"]] = f"{u['title']}\n{u['text']}\n{vt}\n{extra}\n{plates}".lower()
        return out

    def _expand(self, term: str) -> list[str]:
        h = self.person_handle(term)
        if h and len(term) >= 3:
            p = self.person_by_id[h]
            vals = {h, p["name"].lower()}
            vals.update(a["value"].lower() for a in p["aliases"])
            return sorted(vals)
        nt = re.sub(r"[^A-Za-z0-9]", "", term).upper()
        if re.match(r"^[A-Z]{2}\d{3,6}$", nt):
            return [term.lower(), nt.lower()]
        return [term.lower()]

    def search(self, query: str, limit: int = 12, exclude: set | None = None) -> list[str]:
        """Full-text search with alias expansion and IDF weighting (rare terms count more)."""
        phrases = re.findall(r'"([^"]+)"', query)
        rest = re.sub(r'"[^"]+"', " ", query)
        terms = phrases + [t for t in re.findall(r"[\wäöüÄÖÜß@.\-/:]+", rest) if t.lower() not in STOP and (len(t) >= 3 or t.isdigit())]
        groups = []
        for t in terms:
            t = t.strip(".,:;")
            if t:
                g = self._expand(t)
                if g not in groups:
                    groups.append(g)
        if not groups:
            return []
        docs = self._search_text
        n = len(docs)
        hits_per_group = []
        for g in groups:
            hits_per_group.append({uid for uid, txt in docs.items() if any(v in txt for v in g)})
        weights = [math.log((n + 1) / (1 + len(h))) for h in hits_per_group]
        # terms without any hit (e.g. German words against English files) do not count toward the threshold
        total = sum(w for w, h in zip(weights, hits_per_group) if h) or 1.0
        score: dict[str, float] = {}
        for w, h in zip(weights, hits_per_group):
            for uid in h:
                score[uid] = score.get(uid, 0.0) + w
        need = 0.18 * total  # weich: lange KI-Suchanfragen mischen viele Begriffe; Rangfolge entscheidet
        scored = []
        for uid, sc in score.items():
            if exclude and uid in exclude:
                continue
            if sc >= need:
                lab = self.labels.get(uid, {})
                scored.append((sc, REL_RANK.get(lab.get("relevance"), 0), uid))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        return [uid for _, _, uid in scored[:limit]]

    # ------------------------------------------------------------------ evidence resolution
    def unit_for_line(self, path: str, line: int) -> str | None:
        for a, b, uid in self._file_index.get(path, []):
            if a <= line <= b:
                return uid
        return None

    def resolve(self, ev: dict) -> dict:
        key = ((ev or {}).get("unit"), (ev or {}).get("quote"))
        if not hasattr(self, "_rcache"):
            self._rcache = {}
        if key not in self._rcache:
            self._rcache[key] = self._resolve(ev)
        base = self._rcache[key]
        extra = {k: v for k, v in (ev or {}).items() if k not in ("unit", "quote")}
        return {**base, **extra} if extra else dict(base)

    def _resolve(self, ev: dict) -> dict:
        """Bob evidence {unit, quote} → exact location in the original + check status.

        Two separate checks: (1) is the quote verbatim at the location?
        (2) the interpretation (claim) remains an AI statement, shown separately as
        basis/status – a found quote does not prove it.
        """
        uid = (ev or {}).get("unit") or ""
        quote = (ev or {}).get("quote") or ""
        out = {k: v for k, v in (ev or {}).items() if k not in ("unit", "quote")}
        out.update({"unit": uid, "quote_given": quote, "source": None, "quote": None, "ok": False,
                    "exportable": False, "status": "not_found", "detail": ""})
        u = self.by_id.get(uid)
        if not quote.strip():
            out.update(status="empty", detail="No quote given.")
            return out
        # remove display artefacts ALIBI itself added (line prefix, mapping arrow, local-time hint)
        cleaned = re.sub(r"^\s*[LRT]\d+:\s*", "", quote)
        cleaned = re.sub(r"\s+⇒\s.*$", "", cleaned)
        cleaned = re.sub(r"\s*\(=[^)]*(?:Ortszeit|local time)\)\s*$", "", cleaned)
        if cleaned != quote:
            quote = cleaned
            out["cleanup"] = "Display prefix/hint added by ALIBI removed from the quote."
        res = self._resolve_quote(out, uid, u, quote)
        if not res["ok"] and res["status"] not in ("image",) and re.search(r"\.\.\.|…", quote):
            frags = sorted((f.strip() for f in re.split(r"\s*(?:\.\.\.|…)\s*", quote)), key=len, reverse=True)
            for fr in frags:
                if len(fr) < 18:
                    break
                r2 = self._resolve_quote(dict(out), uid, u, fr)
                if r2["ok"]:
                    r2["match"] = "fragment"
                    r2["detail"] = "Bob's quote contained an ellipsis; only the exactly found part is kept."
                    return r2
        return res

    def _resolve_quote(self, out: dict, uid: str, u: dict | None, quote: str) -> dict:
        if not u:
            # unknown unit ID: accept only via a unique full-text match
            hit = self._global_locate(quote)
            if hit:
                out.update(hit, detail="Unknown unit ID; location determined by a unique full-text match.")
                return self._finish(out)
            out.update(status="unknown_unit", detail=f"Unit {uid!r} does not exist.")
            return out
        loc = u["loc"]
        hit = None
        if loc["type"] == "lines":
            hit = sources.locate_in_lines(u["file"], loc["start"], loc["end"], quote)
            if not hit:
                lines = sources.raw_lines(u["file"])
                hit = sources.locate_in_lines(u["file"], 1, len(lines), quote)
                if hit and sum(1 for ln in lines if hit["quote"] in ln) != 1:
                    hit = None  # not unique – do not move to another unit
                if hit and "-" not in hit["source"].rsplit(":", 1)[1]:
                    ln = int(hit["source"].rsplit(":", 1)[1])
                    hit["unit"] = self.unit_for_line(u["file"], ln) or uid
                    hit["detail"] = "Quote is in the same file but a different unit; location corrected."
        elif loc["type"] == "page" and u["doc_type"] == "pdf":
            hit = sources.locate_in_pdf(u["file"], loc["page"], quote)
        elif loc["type"] == "row" and loc.get("citable"):
            hit = sources.locate_in_xlsx(u["file"], loc["row"], quote)
        elif loc["type"] in ("file", "page"):
            v = self.vision.get(uid, {})
            tl = " ".join(v.get("transcript_lines", []))
            src = u["file"] if loc["type"] == "file" else f"{u['file']}:{loc['page']}"
            out.update(source=src, quote=quote, status="image",
                       detail=("Quote is in the Bob Vision transcript – but cannot be verified exactly by machine."
                               if quote.strip() and quote.strip() in tl else "Image source; quote not found in the transcript."))
            return out
        if not hit:
            g = self._global_locate(quote)
            if g:
                out.update(g, detail="Quote not in the given unit; unique location in the bundle used instead.")
                return self._finish(out)
            out.update(detail="Quote not found in the unit.")
            return out
        out.update(source=hit["source"], quote=hit["quote"], match=hit["match"])
        if hit.get("unit"):
            out["unit"] = hit["unit"]
        if hit.get("detail"):
            out["detail"] = hit["detail"]
        return self._finish(out)

    def _finish(self, out: dict) -> dict:
        chk = sources.verify_quote(out["source"], out["quote"])
        out["ok"] = chk["ok"]
        out["status"] = chk["status"] if chk["ok"] else chk["status"]
        if not out.get("detail"):
            out["detail"] = chk["detail"]
        spec = out["source"].rsplit(":", 1)[1] if ":" in out["source"] else ""
        out["exportable"] = bool(chk["ok"] and "-" not in spec and out.get("match") != "multiline")
        if out.get("match") == "normalized":
            out["detail"] = (out.get("detail") or "") + " Bob's quote differed only in whitespace/quote marks; exact original text used."
        return out

    def _global_locate(self, quote: str) -> dict | None:
        q = quote.strip()
        if len(q) < 25:
            return None
        hits = []
        for path in {u["file"] for u in self.units if u["loc"]["type"] == "lines"}:
            for i, ln in enumerate(sources.raw_lines(path), start=1):
                if q in ln:
                    hits.append((path, i))
                    if len(hits) > 1:
                        return None
        if len(hits) == 1:
            path, i = hits[0]
            return {"source": f"{path}:{i}", "quote": q, "match": "exact", "unit": self.unit_for_line(path, i)}
        return None


def window_from_frame(frame: dict | None, pad_hours: int = 36):
    if not frame:
        return None
    inc = frame.get("incident") or {}
    s = Corpus.parse_local(inc.get("window_start_local"))
    e = Corpus.parse_local(inc.get("window_end_local"))
    if not s or not e or e < s:
        return None
    return s - timedelta(hours=pad_hours), e + timedelta(hours=pad_hours)
