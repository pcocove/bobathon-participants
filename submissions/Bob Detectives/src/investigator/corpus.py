"""The case bundle as a line-addressable corpus.

Sources are read exactly as received. Nothing is rewritten: line numbers, bytes and
timestamps stay as the scorer (and a human checker) will see them. Normalised times
live in the record layer (records.py), never in the files.

Citation syntax (from the handout):
  text files   path:line  or  path:start-end
  PDFs         file.pdf:page
  spreadsheet  file.xlsx:row      (Excel row number)
  photos       path/to/photo.jpg  (whole file)
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .util import norm_space, stable_key

TEXT_EXT = {".md", ".txt", ".json", ".csv", ".mbox", ".ics", ".html", ".htm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


@dataclass
class Doc:
    path: str                      # bundle-relative, posix
    kind: str                      # text | pdf | xlsx | image | binary
    lines: list[str] = field(default_factory=list)          # text: raw lines
    pages: dict[int, str] = field(default_factory=dict)     # pdf: page -> text
    page_ocr: dict[int, bool] = field(default_factory=dict)  # pdf page came from OCR
    rows: dict[int, list[str]] = field(default_factory=dict)  # xlsx: excel row -> cells
    ocr_text: str = ""            # image OCR
    notes: list[str] = field(default_factory=list)

    @property
    def is_ocr(self) -> bool:
        return self.kind == "image" or any(self.page_ocr.values())

    def unit_lines(self) -> list[tuple[str, str]]:
        """(citation, text) pairs for searching, at the finest citable unit."""
        out: list[tuple[str, str]] = []
        if self.kind == "text":
            for i, ln in enumerate(self.lines, 1):
                out.append((f"{self.path}:{i}", ln))
        elif self.kind == "pdf":
            for p, txt in self.pages.items():
                for ln in txt.splitlines():
                    if ln.strip():
                        out.append((f"{self.path}:{p}", ln))
        elif self.kind == "xlsx":
            for r, cells in self.rows.items():
                out.append((f"{self.path}:{r}", " · ".join(c for c in cells if c)))
        elif self.kind == "image":
            for ln in self.ocr_text.splitlines():
                if ln.strip():
                    out.append((self.path, ln))
        return out

    def word_count(self) -> int:
        return sum(len(t.split()) for _, t in self.unit_lines())


class Corpus:
    def __init__(self, root: Path, cache_dir: Path | None = None, ocr: bool = True):
        self.root = Path(root)
        self.cache_dir = cache_dir
        self.ocr_enabled = ocr and shutil.which("tesseract") is not None
        self.docs: dict[str, Doc] = {}
        self.warnings: list[str] = []
        self._load()

    # ------------------------------------------------------------------ loading
    def _load(self) -> None:
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or p.name.startswith("."):
                continue
            rel = p.relative_to(self.root).as_posix()
            ext = p.suffix.lower()
            if ext in TEXT_EXT:
                raw = p.read_bytes().decode("utf-8", errors="replace")
                # split on \n only; keep \r if present so quotes stay exact
                lines = raw.split("\n")
                if lines and lines[-1] == "":
                    lines = lines[:-1]
                self.docs[rel] = Doc(rel, "text", lines=lines)
            elif ext == ".pdf":
                self.docs[rel] = self._load_pdf(p, rel)
            elif ext == ".xlsx":
                self.docs[rel] = self._load_xlsx(p, rel)
            elif ext in IMAGE_EXT:
                d = Doc(rel, "image")
                d.ocr_text = self._ocr_file(p)
                if not d.ocr_text:
                    d.notes.append("no OCR text (tesseract missing or unreadable)")
                self.docs[rel] = d
            else:
                self.docs[rel] = Doc(rel, "binary")

    def _cache(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir / f"{key}.txt"

    def _ocr_bytes(self, data: bytes, suffix: str) -> str:
        key = stable_key("ocr", len(data), data[:4096], data[-4096:])
        c = self._cache(key)
        if c and c.exists():
            return c.read_text(encoding="utf-8")
        if not self.ocr_enabled:
            return ""
        tmp_dir = self.cache_dir or Path("/tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / f"ocr_in_{key}{suffix}"
        tmp.write_bytes(data)
        try:
            res = subprocess.run(
                ["tesseract", str(tmp), "-", "--psm", "6"],
                capture_output=True, text=True, timeout=120,
            )
            text = res.stdout
        except Exception as exc:  # pragma: no cover - environment dependent
            self.warnings.append(f"OCR failed: {exc}")
            text = ""
        finally:
            tmp.unlink(missing_ok=True)
        if c:
            c.write_text(text, encoding="utf-8")
        return text

    def _ocr_file(self, p: Path) -> str:
        return self._ocr_bytes(p.read_bytes(), p.suffix.lower())

    def _load_pdf(self, p: Path, rel: str) -> Doc:
        d = Doc(rel, "pdf")
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            d.notes.append("pypdf not installed: PDF text unavailable")
            self.warnings.append(f"{rel}: install pypdf to read PDFs")
            return d
        reader = PdfReader(str(p))
        for i, page in enumerate(reader.pages, 1):
            txt = (page.extract_text() or "").strip()
            if txt:
                d.pages[i] = txt
                d.page_ocr[i] = False
                continue
            # image-only page: pull the embedded JPEG and OCR it
            ocr = ""
            try:
                xobjs = page["/Resources"]["/XObject"]
                for _, ref in xobjs.items():
                    obj = ref.get_object()
                    if obj.get("/Subtype") == "/Image" and obj.get("/Filter") in ("/DCTDecode", ["/DCTDecode"]):
                        ocr += self._ocr_bytes(obj._data, ".jpg")
            except Exception as exc:
                d.notes.append(f"page {i}: could not extract image ({exc})")
            d.pages[i] = ocr
            d.page_ocr[i] = True
            if not ocr:
                d.notes.append(f"page {i}: image-only, no OCR text")
        return d

    def _load_xlsx(self, p: Path, rel: str) -> Doc:
        d = Doc(rel, "xlsx")
        z = zipfile.ZipFile(p)
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss = z.read("xl/sharedStrings.xml").decode("utf-8")
            for si in re.findall(r"<si>(.*?)</si>", ss, re.S):
                shared.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
        sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        for si, name in enumerate(sheets):
            xml = z.read(name).decode("utf-8")
            for rnum, body in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', xml, re.S):
                cells: list[str] = []
                for attrs, inner in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", body, re.S):
                    col = re.search(r'r="([A-Z]+)\d+"', attrs)
                    idx = _col_index(col.group(1)) if col else len(cells)
                    while len(cells) < idx:
                        cells.append("")
                    typ = re.search(r't="(\w+)"', attrs)
                    if typ and typ.group(1) == "s":
                        v = re.search(r"<v>(.*?)</v>", inner or "")
                        val = shared[int(v.group(1))] if v else ""
                    elif typ and typ.group(1) == "inlineStr":
                        val = html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", inner or "", re.S)))
                    else:
                        v = re.search(r"<v>(.*?)</v>", inner or "")
                        val = html.unescape(v.group(1)) if v else ""
                    cells.append(val)
                if si == 0:
                    d.rows[int(rnum)] = cells
                else:
                    d.notes.append(" ".join(c for c in cells if c))
        return d

    # --------------------------------------------------------------- accessors
    def get(self, path: str) -> Doc | None:
        return self.docs.get(path)

    def text_docs(self, prefix: str = "") -> list[Doc]:
        return [d for p, d in self.docs.items() if d.kind == "text" and p.startswith(prefix)]

    def line(self, path: str, n: int) -> str:
        d = self.docs[path]
        return d.lines[n - 1]

    def resolve(self, source: str) -> tuple[Doc | None, int | None, int | None]:
        """Split a citation into (doc, start, end)."""
        if source in self.docs:
            return self.docs[source], None, None
        m = re.match(r"^(.*?):(\d+)(?:-(\d+))?$", source)
        if not m:
            return None, None, None
        d = self.docs.get(m.group(1))
        a = int(m.group(2))
        b = int(m.group(3)) if m.group(3) else a
        return d, a, b

    def segment(self, source: str) -> tuple[str, str]:
        """Return (kind, text) for the cited unit."""
        d, a, b = self.resolve(source)
        if d is None:
            if re.match(r"^(.*?):(\d+)", source) and source.split(":")[0] in self.docs:
                return "out-of-range", ""
            return "missing", ""
        if d.kind == "text":
            if a is None:
                return "text", "\n".join(d.lines)
            if a < 1 or b > len(d.lines) or b < a:
                return "out-of-range", ""
            return "text", "\n".join(d.lines[a - 1:b])
        if d.kind == "pdf":
            if a is None or a not in d.pages:
                return "out-of-range", ""
            return ("pdf-ocr" if d.page_ocr.get(a) else "pdf"), d.pages[a]
        if d.kind == "xlsx":
            if a is None or a not in d.rows:
                return "out-of-range", ""
            return "xlsx", "\n".join(d.rows[a])
        if d.kind == "image":
            return "image-ocr", d.ocr_text
        return "binary", ""

    # ------------------------------------------------------------ verification
    def verify(self, source: str, quote: str) -> dict:
        """Check that `quote` is really at `source`. This is the gate for every claim."""
        kind, text = self.segment(source)
        res = {"source": source, "quote": quote, "kind": kind}
        if kind in ("missing", "out-of-range", "binary"):
            res.update(status="bad-source", detail=f"source not citable ({kind})")
            return res
        if not quote:
            res.update(status="no-quote", detail="empty quote")
            return res
        if quote in text:
            if kind in ("pdf-ocr", "image-ocr"):
                res.update(status="ocr", detail="found in OCR text; confirm against the image")
            else:
                res.update(status="verified", detail="exact match")
            return res
        if kind == "xlsx" and any(quote == c for c in text.split("\n")):
            res.update(status="verified", detail="exact cell match")
            return res
        if norm_space(quote) in norm_space(text):
            status = "ocr" if kind in ("pdf-ocr", "image-ocr") else "whitespace"
            res.update(status=status, detail="matches after whitespace normalisation (line break inside quote)")
            return res
        # nearby? helps humans fix off-by-n line numbers (nearest occurrence wins)
        d, a, _ = self.resolve(source)
        if d is not None and d.kind == "text":
            hits = [i for i, ln in enumerate(d.lines, 1) if quote in ln]
            if hits:
                i = min(hits, key=lambda h: abs(h - (a or 0)))
                res.update(status="wrong-line", detail=f"quote found at line {i}", suggestion=f"{d.path}:{i}")
                return res
        res.update(status="not-found", detail="quote not present at the cited location")
        return res

    # ------------------------------------------------------------------ search
    def search(self, pattern: str, regex: bool = True, path_prefix: str = "",
               limit: int = 200, flags: int = re.IGNORECASE) -> list[dict]:
        if regex:
            pattern = pattern.replace("\\|", "|")   # grep habit: a\|b means a or b
        rx = re.compile(pattern if regex else re.escape(pattern), flags)
        hits = []
        wanted = [w.strip().lower() for w in path_prefix.split(",") if w.strip()]
        for p, d in self.docs.items():
            # --in matches the start of a path or any part of it ("card_feed", "interviews/", "jira")
            if wanted and not any(p.lower().startswith(w) or w in p.lower() for w in wanted):
                continue
            for cite, txt in d.unit_lines():
                if rx.search(txt):
                    hits.append({"source": cite, "text": txt, "ocr": d.is_ocr})
                    if len(hits) >= limit:
                        return hits
        return hits

    def inventory(self) -> list[dict]:
        out = []
        for p, d in self.docs.items():
            out.append({
                "path": p, "kind": d.kind, "words": d.word_count(),
                "lines": len(d.lines) if d.kind == "text" else None,
                "pages": len(d.pages) or None, "rows": len(d.rows) or None,
                "ocr": d.is_ocr, "notes": d.notes,
            })
        return out

    def to_json(self) -> str:
        return json.dumps(self.inventory(), ensure_ascii=False, indent=1)


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n - 1
