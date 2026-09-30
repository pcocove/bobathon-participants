"""Access to original sources and quote verification.

Lines are counted as in the original file: split on '\n' (bytes), a trailing
'\r' is removed, numbering starts at 1. PDF pages and Excel rows also start at 1.
Nothing here modifies the case files.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .config import SETTINGS

TEXT_EXT = {".md", ".txt", ".json", ".csv", ".mbox", ".ics"}
IMAGE_EXT = {".jpg", ".jpeg", ".png"}


def bundle_path(rel: str) -> Path:
    base = SETTINGS.bundle.resolve()
    p = (base / rel).resolve()
    if base not in p.parents and p != base:
        raise ValueError("Path is outside the case bundle")
    return p


@lru_cache(maxsize=256)
def raw_lines(rel: str) -> tuple[str, ...]:
    data = bundle_path(rel).read_bytes()
    parts = data.split(b"\n")
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    out = []
    for b in parts:
        if b.endswith(b"\r"):
            b = b[:-1]
        out.append(b.decode("utf-8"))
    return tuple(out)


@lru_cache(maxsize=16)
def pdf_pages(rel: str) -> tuple[str, ...]:
    from pypdf import PdfReader
    reader = PdfReader(str(bundle_path(rel)))
    return tuple((pg.extract_text() or "") for pg in reader.pages)


def cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


@lru_cache(maxsize=8)
def xlsx_rows(rel: str) -> dict[str, tuple[tuple[str, ...], ...]]:
    """Sheet name -> rows (Excel row number = index + 1), cells as text."""
    import openpyxl
    wb = openpyxl.load_workbook(str(bundle_path(rel)), read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(tuple(cell_text(v) for v in r))
        out[ws.title] = tuple(rows)
    wb.close()
    return out


def first_sheet_rows(rel: str):
    sheets = xlsx_rows(rel)
    return next(iter(sheets.values())) if sheets else ()


# --------------------------------------------------------------------------- source references

SOURCE_RE = re.compile(r"^(?P<path>[^:]+?)(?::(?P<a>\d+)(?:-(?P<b>\d+))?)?$")


def parse_source(source: str) -> dict:
    m = SOURCE_RE.match(source or "")
    if not m:
        raise ValueError("Unreadable source reference")
    path = m.group("path")
    a = int(m.group("a")) if m.group("a") else None
    b = int(m.group("b")) if m.group("b") else None
    ext = Path(path).suffix.lower()
    if path.startswith("/") or ".." in Path(path).parts:
        raise ValueError("Source must be relative to the case bundle root")
    return {"path": path, "start": a, "end": b if b is not None else a, "ext": ext}


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def source_text(source: str) -> tuple[str, list[str]]:
    """Returns (kind, text segments) for a source reference; raises ValueError on problems."""
    s = parse_source(source)
    p = bundle_path(s["path"])
    if not p.exists():
        raise ValueError(f"File not in case bundle: {s['path']}")
    ext = s["ext"]
    if ext in TEXT_EXT:
        if s["start"] is None:
            raise ValueError("Text source without line number")
        lines = raw_lines(s["path"])
        if not (1 <= s["start"] <= s["end"] <= len(lines)):
            raise ValueError(f"Line outside the file (1–{len(lines)})")
        return "lines", list(lines[s["start"] - 1:s["end"]])
    if ext == ".pdf":
        pages = pdf_pages(s["path"])
        if s["start"] is None or s["end"] != s["start"]:
            raise ValueError("PDF source needs exactly one page number")
        if not 1 <= s["start"] <= len(pages):
            raise ValueError(f"Page outside the PDF (1–{len(pages)})")
        return "pdf", [pages[s["start"] - 1]]
    if ext == ".xlsx":
        rows = first_sheet_rows(s["path"])
        if s["start"] is None or s["end"] != s["start"]:
            raise ValueError("Excel source needs exactly one row number")
        if not 1 <= s["start"] <= len(rows):
            raise ValueError(f"Excel row outside the sheet (1–{len(rows)})")
        return "xlsx", list(rows[s["start"] - 1])
    if ext in IMAGE_EXT:
        if s["start"] is not None:
            raise ValueError("Photos are cited without a line number")
        return "image", []
    raise ValueError(f"Unknown source type {ext}")


def verify_quote(source: str, quote: str) -> dict:
    """Is the quote verbatim at the cited location?

    Status:
      exact           – quote is a literal part of the line/page/cell
      pdf_whitespace  – PDF text: identical except line breaks/whitespace (extraction artefact)
      empty           – empty quote, never counts as verified
      image           – image source, quote cannot be machine-verified
      not_found / invalid_source
    """
    if quote is None or quote.strip() == "":
        return {"ok": False, "status": "empty", "detail": "An empty quote is not accepted as evidence."}
    try:
        kind, segs = source_text(source)
    except (ValueError, OSError) as e:
        return {"ok": False, "status": "invalid_source", "detail": str(e)}
    if kind == "image":
        return {"ok": False, "status": "image", "detail": "Image source – quote cannot be verified exactly by machine."}
    if kind == "lines":
        if any(quote in ln for ln in segs):
            return {"ok": True, "status": "exact", "detail": "Quote appears verbatim in the line."}
        if len(segs) > 1 and quote in "\n".join(segs):
            return {"ok": True, "status": "exact", "detail": "Quote appears verbatim in the line range."}
        return {"ok": False, "status": "not_found", "detail": "Quote is not at this location."}
    if kind == "pdf":
        page = segs[0]
        if quote in page:
            return {"ok": True, "status": "exact", "detail": "Quote appears verbatim in the PDF page text."}
        if _ws(quote) and _ws(quote) in _ws(page):
            return {"ok": True, "status": "pdf_whitespace",
                    "detail": "Quote is in the PDF page text; only line breaks/whitespace from text extraction differ."}
        return {"ok": False, "status": "not_found", "detail": "Quote not in the PDF page text layer."}
    if kind == "xlsx":
        if any(quote in c for c in segs if c):
            return {"ok": True, "status": "exact", "detail": "Quote appears verbatim in a cell of this row."}
        return {"ok": False, "status": "not_found", "detail": "Quote is in no cell of this Excel row."}
    return {"ok": False, "status": "invalid_source", "detail": "Unknown"}


# --------------------------------------------------------------------------- quote location

_QUOTE_CHARS = "\"'“”„‟‘’‚‛`´"


def _loose_pattern(quote: str) -> re.Pattern | None:
    q = unicodedata.normalize("NFC", quote.strip())
    if len(q) < 4:
        return None
    parts = []
    for ch in q:
        if ch.isspace():
            if not parts or parts[-1] != r"\s+":
                parts.append(r"\s+")
        elif ch in _QUOTE_CHARS:
            parts.append("[" + re.escape(_QUOTE_CHARS) + "]")
        elif ch in "-–—":
            parts.append("[-–—]")
        elif ch in "…":
            parts.append(r"(?:…|\.\.\.)")
        else:
            parts.append(re.escape(ch))
    return re.compile("".join(parts))


def locate_in_lines(path: str, start: int, end: int, quote: str) -> dict | None:
    """Finds a quote within a line range of the original file.

    Returns the exact original character sequence. If it only matches after
    whitespace/quote-mark normalisation, the text is taken from the original file
    and the normalisation is recorded – the exported text is still verbatim.
    """
    if not quote or not quote.strip():
        return None
    lines = raw_lines(path)
    start = max(1, start)
    end = min(len(lines), end)
    q = quote.strip()
    for i in range(start, end + 1):
        if q in lines[i - 1]:
            return {"source": f"{path}:{i}", "quote": q, "match": "exact"}
    pat = _loose_pattern(q)
    if pat:
        for i in range(start, end + 1):
            m = pat.search(lines[i - 1])
            if m:
                return {"source": f"{path}:{i}", "quote": m.group(0), "match": "normalized"}
        # across line boundaries – display only, not exportable
        block = "\n".join(lines[start - 1:end])
        m = pat.search(block)
        if m:
            a = block.count("\n", 0, m.start()) + start
            b = block.count("\n", 0, m.end()) + start
            return {"source": f"{path}:{a}-{b}", "quote": m.group(0), "match": "multiline"}
    return None


def locate_in_pdf(path: str, page: int, quote: str) -> dict | None:
    pages = pdf_pages(path)
    if not 1 <= page <= len(pages) or not quote.strip():
        return None
    text = pages[page - 1]
    q = quote.strip()
    if q in text:
        return {"source": f"{path}:{page}", "quote": q, "match": "exact"}
    pat = _loose_pattern(q)
    if pat:
        m = pat.search(text)
        if m:
            exact = m.group(0)
            return {"source": f"{path}:{page}", "quote": exact,
                    "match": "exact" if "\n" not in exact else "pdf_whitespace"}
    return None


def locate_in_xlsx(path: str, row: int, quote: str) -> dict | None:
    rows = first_sheet_rows(path)
    if not 1 <= row <= len(rows) or not quote.strip():
        return None
    q = quote.strip()
    for c in rows[row - 1]:
        if c and q in c:
            return {"source": f"{path}:{row}", "quote": q, "match": "exact"}
    cells = sorted((c for c in rows[row - 1] if c and len(c) >= 3 and c in q), key=len, reverse=True)
    if cells:
        return {"source": f"{path}:{row}", "quote": cells[0], "match": "cell"}
    return None
