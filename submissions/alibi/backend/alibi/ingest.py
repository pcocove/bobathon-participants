"""Inventory and decomposition of the case bundle into information units.

Deterministic, no AI. Per unit: stable ID, file, location, original text, document
type, people (with the basis of the link), timestamps (original + normalised + basis)
and processing status. Original data (raw), normalised data (text/fields/times/people)
and AI labels (separately in labels.json) are kept apart.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import sources
from .config import SETTINGS, template_names
from .store import write_json

ZRH = ZoneInfo("Europe/Zurich")

DOC_TYPES = {
    "slack": "Slack", "email": "Email", "jira": "Jira", "calendar": "Calendar",
    "interview": "Interview", "notebook": "Investigator notes", "helpdesk": "Helpdesk/Facilities",
    "expense": "Expenses", "card": "Card feed", "garage": "Garage log", "permit": "Parking permits",
    "meeting": "Meeting notes", "diligence": "Diligence log", "pdf": "PDF", "scan": "Scan (image PDF)",
    "photo": "Photo", "meta": "Metadata",
}


# --------------------------------------------------------------------------- time

def t_from_aware(dt: datetime, original: str, basis: str) -> dict:
    return {"original": original, "utc": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "local": dt.astimezone(ZRH).isoformat(), "basis": basis, "precision": "datetime"}


def t_local_wall(dt_naive: datetime, original: str, basis: str) -> dict:
    """Local wall-clock time without zone – interpreted as Europe/Zurich, NOT corrected."""
    dt = dt_naive.replace(tzinfo=ZRH)
    d = t_from_aware(dt, original, basis)
    d["assumed_zone"] = True
    return d


def t_date(original: str, iso: str, basis: str) -> dict:
    return {"original": original, "utc": None, "local": iso, "basis": basis, "precision": "date"}


# --------------------------------------------------------------------------- JSON spans

def object_spans(text: str) -> list[tuple[int, int, int]]:
    """All {...} objects as (start line, end line, depth) in file order."""
    spans, stack = [], []
    line, in_str, esc, depth = 1, False, False, 0
    for ch in text:
        if ch == "\n":
            line += 1
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
            if ch == "{":
                stack.append((line, depth))
            else:
                stack.append((None, depth))
        elif ch in "}]":
            start, d = stack.pop()
            if start is not None:
                spans.append((start, line, d))
            depth -= 1
    spans.sort(key=lambda s: (s[0], -s[1]))
    return spans


# --------------------------------------------------------------------------- people

class People:
    """Person registry with aliases and the documented origin of each alias."""

    def __init__(self):
        self.persons: dict[str, dict] = {}

    @staticmethod
    def handle_from_name(name: str) -> str:
        n = re.sub(r"^(dr\.?|prof\.?)\s+", "", name.strip(), flags=re.I)
        n = re.sub(r"\(.*?\)", "", n)
        return ".".join(p.lower().strip(".") for p in n.split() if p.strip("."))

    def ensure(self, handle: str, name: str | None = None, basis: str | None = None) -> dict:
        handle = handle.strip().lower()
        p = self.persons.get(handle)
        if not p:
            derived = " ".join(w.capitalize() for w in re.split(r"[.\-_]", handle) if w)
            label = name or derived
            kind = "organisation" if re.search(r"\b(AG|GmbH|SA|Ltd|Inc)\b", label) else "person"
            p = {"id": handle, "name": label, "name_basis": basis or "derived from handle",
                 "aliases": [], "suspect": False, "titles": [], "kind": kind}
            self.persons[handle] = p
        elif name and p["name_basis"] == "derived from handle":
            p["name"], p["name_basis"] = name, basis or p["name_basis"]
        return p

    def add_alias(self, handle: str, kind: str, value: str, source: str | None):
        p = self.ensure(handle)
        if not value:
            return
        for a in p["aliases"]:
            if a["kind"] == kind and a["value"] == value:
                return
        p["aliases"].append({"kind": kind, "value": value, "source": source})

    def by_alias(self, kind: str) -> dict[str, str]:
        out = {}
        for h, p in self.persons.items():
            for a in p["aliases"]:
                if a["kind"] == kind:
                    out[a["value"]] = h
        return out


def norm_plate(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def plate_distance(a: str, b: str) -> int:
    if len(a) != len(b):
        return 99
    return sum(1 for x, y in zip(a, b) if x != y)


# --------------------------------------------------------------------------- units

class Ingest:
    def __init__(self, bundle: Path):
        self.bundle = bundle
        self.units: list[dict] = []
        self.files: list[dict] = []
        self.people = People()
        self.ids: set[str] = set()

    def rel(self, p: Path) -> str:
        return p.relative_to(self.bundle).as_posix()

    def add(self, uid: str, file: str, dtype: str, cluster: str, loc: dict, title: str, raw: str,
            text: str | None = None, fields: dict | None = None, times: list | None = None,
            people: list | None = None, status: str = "parsed", note: str | None = None) -> dict:
        base, n = uid, 2
        while uid in self.ids:
            uid = f"{base}-{n}"
            n += 1
        self.ids.add(uid)
        u = {"id": uid, "file": file, "doc_type": dtype, "cluster": cluster, "loc": loc, "title": title[:160],
             "raw": raw, "text": text if text is not None else raw, "fields": fields or {},
             "times": times or [], "people": people or [], "status": status}
        if note:
            u["note"] = note
        self.units.append(u)
        return u

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        all_files = sorted(p for p in self.bundle.rglob("*") if p.is_file() and not p.name.startswith("."))
        # registry sources first (aliases), then every file
        self.load_registry()
        handlers = [
            (lambda r: r == "slack_export/users.json", self.slack_users),
            (lambda r: r == "slack_export/channels.json", self.slack_channels),
            (lambda r: r.startswith("slack_export/") and r.endswith(".json"), self.slack_day),
            (lambda r: r.endswith(".mbox"), self.mbox),
            (lambda r: r.endswith(".ics"), self.ics),
            (lambda r: r.startswith("interviews/") and r.endswith(".txt"), self.interview),
            (lambda r: r.endswith(".csv"), self.csv_file),
            (lambda r: r.endswith(".xlsx"), self.xlsx),
            (lambda r: r.endswith(".pdf"), self.pdf),
            (lambda r: r.lower().endswith((".jpg", ".jpeg", ".png")), self.image),
            (lambda r: r == "jira_export.json", self.jira),
            (lambda r: r.endswith(".md"), self.markdown),
            (lambda r: r.endswith(".txt"), self.plain_text),
        ]
        for p in all_files:
            r = self.rel(p)
            entry = {"file": r, "bytes": p.stat().st_size, "status": "discovered", "units": 0, "error": None}
            before = len(self.units)
            for match, fn in handlers:
                if match(r):
                    try:
                        fn(p, r)
                        entry["status"] = "parsed"
                    except Exception as e:  # every file stays in the inventory
                        entry["status"] = "failed"
                        entry["error"] = f"{type(e).__name__}: {e}"
                    break
            else:
                entry["status"] = "unsupported"
            entry["units"] = len(self.units) - before
            pend = [u for u in self.units[before:] if u["status"] != "parsed"]
            if pend and entry["status"] == "parsed":
                entry["status"] = "partial (" + pend[0]["status"] + ")"
            self.files.append(entry)
        self.link_people()
        return self.save()

    # ------------------------------------------------------------------ registry
    def load_registry(self):
        """Names from the template; aliases from users.json and the parking permits."""
        for n in template_names():
            p = self.people.ensure(People.handle_from_name(n), n, "verdict_template.json")
            p["suspect"] = True
            self.people.add_alias(p["id"], "name", n, "verdict_template.json")
        up = self.bundle / "slack_export/users.json"
        if up.exists():
            text = up.read_text(encoding="utf-8")
            spans = [s for s in object_spans(text) if s[2] == 2]
            for (a, b, _), u in zip(spans, json.loads(text)):
                src = f"slack_export/users.json:{a}-{b}"
                h = u.get("name") or People.handle_from_name(u.get("real_name", u["id"]))
                p = self.people.ensure(h, u.get("real_name"), "slack_export/users.json")
                if u.get("profile", {}).get("title"):
                    p["titles"].append({"value": u["profile"]["title"], "source": src})
                self.people.add_alias(h, "slack_id", u["id"], src)
                self.people.add_alias(h, "handle", h, src)
                if u.get("real_name"):
                    self.people.add_alias(h, "name", u["real_name"], src)
                if u.get("profile", {}).get("email"):
                    self.people.add_alias(h, "email", u["profile"]["email"].lower(), src)
        for x in self.bundle.glob("*.xlsx"):
            rows = sources.first_sheet_rows(self.rel(x))
            header_idx, header = None, None
            for i, r in enumerate(rows):
                low = [c.lower() for c in r]
                if any("kennzeichen" in c for c in low) and any("inhaber" in c for c in low):
                    header_idx, header = i, low
                    break
            if header is None:
                continue
            ci = next(i for i, c in enumerate(header) if "kennzeichen" in c)
            ni = next(i for i, c in enumerate(header) if "inhaber" in c)
            for j in range(header_idx + 1, len(rows)):
                r = rows[j]
                if len(r) <= max(ci, ni) or not r[ci] or not r[ni]:
                    continue
                h = People.handle_from_name(r[ni])
                self.people.ensure(h, r[ni], f"{self.rel(x)}:{j + 1}")
                self.people.add_alias(h, "name", r[ni], f"{self.rel(x)}:{j + 1}")
                self.people.add_alias(h, "plate", norm_plate(r[ci]), f"{self.rel(x)}:{j + 1}")

    # ------------------------------------------------------------------ Slack
    def slack_users(self, p: Path, r: str):
        text = p.read_text(encoding="utf-8")
        lines = sources.raw_lines(r)
        spans = [s for s in object_spans(text) if s[2] == 2]
        for (a, b, _), u in zip(spans, json.loads(text)):
            raw = "\n".join(lines[a - 1:b])
            h = u.get("name")
            self.add(f"SLU-{u['id']}", r, "meta", "Slack · user directory", {"type": "lines", "start": a, "end": b},
                     f"Slack user {u.get('real_name')} ({u['id']})", raw,
                     fields={"slack_id": u["id"], "handle": h, "real_name": u.get("real_name")},
                     people=[{"person": h, "via": f"users.json {u['id']}", "basis": "direct"}])

    def slack_channels(self, p: Path, r: str):
        lines = sources.raw_lines(r)
        self.add("SLC", r, "meta", "Slack · user directory", {"type": "lines", "start": 1, "end": len(lines)},
                 "Slack channel list", "\n".join(lines))

    def slack_day(self, p: Path, r: str):
        channel = p.parent.name
        text = p.read_text(encoding="utf-8")
        lines = sources.raw_lines(r)
        data = json.loads(text)
        spans = [s for s in object_spans(text) if s[2] == 2]
        ids = self.people.by_alias("slack_id")
        for (a, b, _), m in zip(spans, data):
            ts = m.get("ts", "")
            times = []
            try:
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                times.append(t_from_aware(dt, ts, "Slack ts (Unix time, UTC)"))
            except ValueError:
                pass
            uid = m.get("user", "")
            ppl = []
            if uid in ids:
                ppl.append({"person": ids[uid], "via": f"Slack user ID {uid} (users.json)", "basis": "direct", "role": "author"})
            text_line = next((i for i in range(a, b + 1) if lines[i - 1].lstrip().startswith('"text"')), a)
            self.add(f"SL-{channel}-{p.stem}-L{a}", r, "slack", f"Slack · #{channel}",
                     {"type": "lines", "start": a, "end": b, "focus": text_line},
                     f"#{channel}: {m.get('text', '')[:90]}", "\n".join(lines[a - 1:b]), text=m.get("text", ""),
                     fields={"channel": channel, "user": uid, "ts": ts}, times=times, people=ppl)

    # ------------------------------------------------------------------ email
    FROM_RE = re.compile(r"^From \S+ \w{3} \w{3} [ \d]\d \d\d:\d\d:\d\d \d{4}\s*$")

    def mbox(self, p: Path, r: str):
        lines = sources.raw_lines(r)
        starts = [i + 1 for i, ln in enumerate(lines) if self.FROM_RE.match(ln)]
        for k, a in enumerate(starts):
            b = (starts[k + 1] - 1) if k + 1 < len(starts) else len(lines)
            while b > a and not lines[b - 1].strip():
                b -= 1
            block = lines[a - 1:b]
            headers, body_start = {}, None
            last = None
            for j, ln in enumerate(block[1:], start=1):
                if ln == "":
                    body_start = j + 1
                    break
                if ln[:1] in " \t" and last:
                    headers[last] += " " + ln.strip()
                elif ":" in ln:
                    key, val = ln.split(":", 1)
                    last = key.strip().lower()
                    headers[last] = val.strip()
            body = "\n".join(block[body_start:]) if body_start else ""
            times = []
            if headers.get("date"):
                try:
                    times.append(t_from_aware(parsedate_to_datetime(headers["date"]), headers["date"],
                                              "email Date header (with offset)"))
                except (TypeError, ValueError):
                    pass
            ppl = []
            for role, key in (("sender", "from"), ("recipient", "to"), ("cc", "cc"), ("bcc", "bcc")):
                for addr in re.findall(r"[\w.+-]+@[\w.-]+", headers.get(key, "")):
                    addr = addr.lower()
                    local = addr.split("@")[0]
                    if "." in local and addr.endswith("halcyon-systems.ch"):
                        self.people.ensure(local)
                        self.people.add_alias(local, "email", addr, f"{r}:{a}")
                        ppl.append({"person": local, "via": f"{key.capitalize()}: {addr}", "basis": "direct", "role": role})
                    else:
                        ppl.append({"list": addr, "via": f"{key.capitalize()}: {addr}", "basis": "mailing_list", "role": role})
            self.add(f"EM-L{a}", r, "email", "Email", {"type": "lines", "start": a, "end": b},
                     headers.get("subject", "(no subject)"), "\n".join(block),
                     text=f"Subject: {headers.get('subject', '')}\nFrom: {headers.get('from', '')}\nTo: {headers.get('to', '')}"
                          + (f"\nCc: {headers['cc']}" if headers.get("cc") else "") + f"\n\n{body}",
                     fields={k: v for k, v in headers.items() if k in ("from", "to", "cc", "subject", "date", "x-attachment", "message-id")},
                     times=times, people=ppl)

    # ------------------------------------------------------------------ calendars
    def ics(self, p: Path, r: str):
        lines = sources.raw_lines(r)
        cal_handle = p.stem.lower()
        calname, producer = None, None
        i = 0
        # unfold: continuation lines start with space/tab (RFC 5545)
        logical = []  # (start line, end line, text)
        for n, ln in enumerate(lines, start=1):
            if ln[:1] in (" ", "\t") and logical:
                s, _, t = logical[-1]
                logical[-1] = (s, n, t + ln[1:])
            else:
                logical.append((n, n, ln))
        for s, e, t in logical:
            if t.startswith("X-WR-CALNAME:"):
                calname = t.split(":", 1)[1]
            if t.startswith("PRODID:"):
                producer = t.split(":", 1)[1]
        if calname:
            self.people.ensure(cal_handle, calname, f"{r} X-WR-CALNAME")
            self.people.add_alias(cal_handle, "name", calname, f"{r}")
        ev = None
        for s, e, t in logical:
            if t == "BEGIN:VEVENT":
                ev = {"start": s, "props": []}
            elif t == "END:VEVENT" and ev is not None:
                self._ics_event(r, cal_handle, calname, producer, ev, e, lines)
                ev = None
            elif ev is not None:
                ev["props"].append((s, e, t))

    def _ics_event(self, r, cal_handle, calname, producer, ev, end_line, lines):
        props, times, fields = {}, [], {}
        for s, e, t in ev["props"]:
            m = re.match(r"^([A-Z-]+)((?:;[^:]*)?):(.*)$", t)
            if not m:
                continue
            name, params, val = m.group(1), m.group(2), m.group(3)
            val = val.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")
            props[name] = (params, val, s)
        for key in ("DTSTART", "DTEND"):
            if key not in props:
                continue
            params, val, _ = props[key]
            orig = f"{key}{params}:{val}"
            try:
                if val.endswith("Z"):
                    dt = datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                    tv = t_from_aware(dt, orig, "iCalendar UTC (Z)")
                elif "TZID=" in params:
                    tz = ZoneInfo(re.search(r"TZID=([^;:]+)", params).group(1))
                    dt = datetime.strptime(val, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
                    tv = t_from_aware(dt, orig, f"iCalendar TZID={tz.key}")
                elif len(val) == 8:
                    tv = t_date(orig, f"{val[:4]}-{val[4:6]}-{val[6:]}", "iCalendar all-day")
                else:
                    tv = t_local_wall(datetime.strptime(val, "%Y%m%dT%H%M%S"), orig, "iCalendar without zone (floating)")
                tv["role"] = key.lower()
                times.append(tv)
            except (ValueError, KeyError, AttributeError):
                pass
        summary = props.get("SUMMARY", ("", "", 0))[1]
        org = props.get("ORGANIZER", ("", "", 0))
        fields = {"summary": summary, "calendar": calname, "producer": producer,
                  "organizer": re.sub(r"^mailto:", "", org[1]) if org[1] else None}
        if "DESCRIPTION" in props:
            fields["description"] = props["DESCRIPTION"][1]
        if "LOCATION" in props:
            fields["location"] = props["LOCATION"][1]
        ppl = [{"person": cal_handle, "via": f"calendar {r}", "basis": "calendar", "role": "calendar owner"}]
        if fields["organizer"] and "@" in fields["organizer"]:
            oh = fields["organizer"].split("@")[0].lower()
            if oh != cal_handle:
                ppl.append({"person": oh, "via": f"ORGANIZER {fields['organizer']}", "basis": "direct", "role": "organizer"})
                self.people.ensure(oh)
        a = ev["start"]
        text = f"{summary}" + (f"\n{fields.get('description')}" if fields.get("description") else "") + \
               (f"\nLocation: {fields['location']}" if fields.get("location") else "")
        self.add(f"CAL-{cal_handle}-L{a}", r, "calendar", f"Calendar · {calname or cal_handle}",
                 {"type": "lines", "start": a, "end": end_line, "focus": props.get("SUMMARY", ("", "", a))[2]},
                 f"{summary} ({calname})", "\n".join(lines[a - 1:end_line]), text=text,
                 fields=fields, times=times, people=ppl,
                 note="A calendar entry shows a booking, not actual presence.")

    # ------------------------------------------------------------------ Interviews
    TS_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\]\s+([^:]{1,40}):\s?(.*)$")

    def interview(self, p: Path, r: str):
        lines = sources.raw_lines(r)
        m = re.match(r"(interview|followup)_(\d+)_(.+)$", p.stem)
        kind = "IV" if m and m.group(1) == "interview" else "FU"
        num = m.group(2) if m else "0"
        handle = m.group(3).replace("_", ".") if m else None
        header_end = next((i + 1 for i, ln in enumerate(lines) if re.match(r"^-{10,}$", ln)), 0)
        title_line = next((ln for ln in lines[:header_end] if ln.lower().startswith(("interviewee", "subject", "witness", "follow"))), lines[0] if lines else "")
        ppl = []
        if handle and handle in self.people.persons:
            ppl.append({"person": handle, "via": f"file name {p.name}", "basis": "direct", "role": "interviewee"})
        elif handle:
            self.people.ensure(handle)
            ppl.append({"person": handle, "via": f"file name {p.name}", "basis": "direct", "role": "interviewee"})
        date = None
        for ln in lines[:header_end]:
            dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", ln)
            if dm and ln.lower().startswith("date"):
                date = t_date(ln.strip(), f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}", "interview header")
        if header_end:
            self.add(f"{kind}{num}-L1", r, "interview", f"Interview · {p.stem}", {"type": "lines", "start": 1, "end": header_end},
                     f"Header: {title_line.strip()}", "\n".join(lines[:header_end]), times=[date] if date else [], people=ppl)
        # sections: every question by the interviewer (NA) starts a new section
        block_start = None
        def flush(a, b):
            while b >= a and not lines[b - 1].strip():
                b -= 1
            if b < a:
                return
            raw = "\n".join(lines[a - 1:b])
            first = self.TS_RE.match(lines[a - 1])
            title = (first.group(3) if first else lines[a - 1])[:100]
            self.add(f"{kind}{num}-L{a}", r, "interview", f"Interview · {p.stem}", {"type": "lines", "start": a, "end": b},
                     f"{p.stem} · {title}", raw, times=[date] if date else [], people=list(ppl),
                     note="Statement in an automatic transcript – not a confirmed fact; speaker labels may be wrong.")
        for i in range(header_end + 1, len(lines) + 1):
            m2 = self.TS_RE.match(lines[i - 1])
            is_q = m2 and m2.group(2).strip().upper() in ("NA", "NADIA ARSLAN", "INTERVIEWER")
            if block_start is None:
                if lines[i - 1].strip():
                    block_start = i
                continue
            if is_q and i - block_start >= 1:
                flush(block_start, i - 1)
                block_start = i
        if block_start is not None:
            flush(block_start, len(lines))

    # ------------------------------------------------------------------ CSV
    def csv_file(self, p: Path, r: str):
        lines = sources.raw_lines(r)
        comments = [i for i, ln in enumerate(lines, start=1) if ln.startswith("#")]
        header_no = next(i for i, ln in enumerate(lines, start=1) if ln.strip() and not ln.startswith("#"))
        sample = lines[header_no - 1]
        delim = ";" if sample.count(";") > sample.count(",") else ","
        header = next(csv.reader([sample], delimiter=delim))
        low = [h.strip().lower() for h in header]
        is_garage = "kennzeichen" in low
        is_card = "cardholder" in low
        prefix = "GAR" if is_garage else ("CARD" if is_card else "CSV-" + p.stem.upper())
        dtype = "garage" if is_garage else ("card" if is_card else "meta")
        cluster = {"garage": "Garage barrier log", "card": "Card feed Q4"}.get(dtype, p.name)
        head_text = "\n".join(lines[: header_no])
        self.add(f"{prefix}-L1", r, "meta" if dtype == "meta" else dtype, cluster,
                 {"type": "lines", "start": 1, "end": header_no}, f"File header {p.name}", head_text,
                 fields={"comments": [lines[i - 1] for i in comments], "header": header})
        plates = self.people.by_alias("plate")
        handles = self.people.persons
        for n in range(header_no + 1, len(lines) + 1):
            ln = lines[n - 1]
            if not ln.strip():
                continue
            row = next(csv.reader([ln], delimiter=delim))
            rec = dict(zip(header, row))
            times, ppl = [], []
            if is_card:
                ts = rec.get("timestamp_utc", "")
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    times.append(t_from_aware(dt, ts, "column timestamp_utc (UTC per file header, terminal time)"))
                except ValueError:
                    pass
                h = rec.get("cardholder", "").strip().lower()
                if h:
                    self.people.ensure(h)
                    ppl.append({"person": h, "via": f"cardholder {h}", "basis": "cardholder", "role": "cardholder"})
                title = f"{rec.get('cardholder')} · {rec.get('merchant')} · {rec.get('merchant_city')} · CHF {rec.get('amount_chf')}"
            elif is_garage:
                d, t = rec.get("Datum", ""), rec.get("Uhrzeit", "")
                try:
                    dt = datetime.strptime(f"{d} {t}", "%d.%m.%Y %H:%M:%S")
                    times.append(t_local_wall(dt, f"{d} {t}", "barrier system clock (local, uncorrected)"))
                except ValueError:
                    pass
                pl = norm_plate(rec.get("Kennzeichen", ""))
                if pl in plates:
                    ppl.append({"person": plates[pl], "via": f"plate {rec.get('Kennzeichen')} = parking permit",
                                "basis": "vehicle", "role": "vehicle holder"})
                else:
                    near = [(v, h) for v, h in plates.items() if plate_distance(pl, v) == 1]
                    for v, h in near:
                        ppl.append({"person": h, "via": f"plate {rec.get('Kennzeichen')} differs by 1 character from permit {v}",
                                    "basis": "vehicle_uncertain", "role": "vehicle holder?"})
                title = f"{rec.get('Kennzeichen')} · {rec.get('Richtung')} · {d} {t}"
            else:
                title = " · ".join(row[:4])
            self.add(f"{prefix}-L{n}", r, dtype, cluster, {"type": "lines", "start": n, "end": n}, title, ln,
                     text=ln, fields=rec, times=times, people=ppl,
                     note=("A plate entry shows the vehicle, not who was driving." if is_garage else
                           "A card entry shows the card, not who was paying." if is_card else None))

    # ------------------------------------------------------------------ Excel
    def xlsx(self, p: Path, r: str):
        sheets = sources.xlsx_rows(r)
        first = True
        for name, rows in sheets.items():
            header = None
            for i, row in enumerate(rows, start=1):
                vals = [c for c in row if c]
                if not vals:
                    continue
                if header is None and len(vals) >= 3:
                    header = list(row)
                    continue
                rec = dict(zip(header, row)) if header else {}
                ppl = []
                holder = next((v for k, v in rec.items() if k and "inhaber" in k.lower()), None)
                if holder:
                    ppl.append({"person": People.handle_from_name(holder), "via": f"permit holder {holder}", "basis": "direct", "role": "permit holder"})
                cite = f"{r}:{i}" if first else None
                self.add(f"PERMIT-{'' if first else name + '-'}R{i}", r, "permit", "Parking permits",
                         {"type": "row", "row": i, "sheet": name, "citable": first},
                         " · ".join(vals)[:120], " | ".join(row), fields=rec, people=ppl,
                         note=None if first else "Second sheet – export row numbers are only unambiguous for the first sheet.")
                _ = cite
            first = False

    # ------------------------------------------------------------------ PDF
    def pdf(self, p: Path, r: str):
        pages = sources.pdf_pages(r)
        stem = re.sub(r"[^A-Za-z0-9]+", "-", p.stem).upper()
        for i, t in enumerate(pages, start=1):
            if t.strip():
                self.add(f"PDF-{stem}-P{i}", r, "pdf", p.name, {"type": "page", "page": i}, f"{p.name} page {i}",
                         t, people=[])
            else:
                self.add(f"PDF-{stem}-P{i}", r, "scan", p.name, {"type": "page", "page": i},
                         f"{p.name} page {i} (image only)", "", status="pending (image content – Bob Vision)",
                         note="Page has no text layer. Content only via image analysis; quotes from it cannot be verified exactly.")

    def image(self, p: Path, r: str):
        self.add(f"IMG-{p.stem}", r, "photo", "Photos", {"type": "file"}, p.name, "",
                 status="pending (image content – Bob Vision)",
                 note="Photo. Content only via image analysis; quotes from it cannot be verified exactly.")

    # ------------------------------------------------------------------ Jira
    def jira(self, p: Path, r: str):
        text = p.read_text(encoding="utf-8")
        lines = sources.raw_lines(r)
        data = json.loads(text)
        spans = [s for s in object_spans(text) if s[2] == 3]
        for (a, b, _), issue in zip(spans, data.get("issues", [])):
            f = issue.get("fields", {})
            times, ppl = [], []
            for key in ("created", "updated", "resolved"):
                if f.get(key):
                    try:
                        tv = t_from_aware(datetime.fromisoformat(f[key]), f[key], f"Jira {key} (ISO with offset)")
                        tv["role"] = key
                        times.append(tv)
                    except ValueError:
                        pass
            for role in ("reporter", "assignee"):
                if f.get(role):
                    self.people.ensure(f[role])
                    ppl.append({"person": f[role].lower(), "via": f"{role}: {f[role]}", "basis": "direct", "role": role})
            parts = [f"{issue.get('key')}: {f.get('summary', '')}", f"Status: {f.get('status')} · Priority: {f.get('priority')}"]
            if f.get("description"):
                parts.append(f["description"])
            for c in f.get("comments", []):
                parts.append(f"[{c.get('created')}] {c.get('author')}: {c.get('body')}")
                if c.get("author"):
                    self.people.ensure(c["author"])
                    ppl.append({"person": c["author"].lower(), "via": f"comment by {c['author']}", "basis": "direct", "role": "comment"})
                if c.get("created"):
                    try:
                        tv = t_from_aware(datetime.fromisoformat(c["created"]), c["created"], "Jira comment (ISO with offset)")
                        tv["role"] = "comment"
                        times.append(tv)
                    except ValueError:
                        pass
            self.add(f"JI-{issue.get('key')}", r, "jira", "Jira · " + issue.get("key", "?").split("-")[0],
                     {"type": "lines", "start": a, "end": b}, f"{issue.get('key')} · {f.get('summary', '')}",
                     "\n".join(lines[a - 1:b]), text="\n".join(parts),
                     fields={"key": issue.get("key"), "summary": f.get("summary"), "status": f.get("status")},
                     times=times, people=ppl)

    # ------------------------------------------------------------------ Markdown
    MD_TYPES = {
        "investigator_notebook.md": ("notebook", "NB", "Investigator notebook"),
        "helpdesk_and_facilities.md": ("helpdesk", "HD", "Helpdesk & facilities"),
        "expense_reports.md": ("expense", "EX", "Expenses"),
        "meeting_notes.md": ("meeting", "MT", "Meeting notes"),
        "kestrel_diligence_log.md": ("diligence", "KD", "Kestrel diligence"),
        "README.md": ("meta", "README", "Case README"),
    }

    def markdown(self, p: Path, r: str):
        dtype, prefix, cluster = self.MD_TYPES.get(r, ("meta", "MD-" + p.stem.upper(), p.name))
        lines = sources.raw_lines(r)
        heads = [i for i, ln in enumerate(lines, start=1) if re.match(r"^#{1,4} ", ln)]
        bounds = [1] + [h for h in heads if h != 1] + [len(lines) + 1]
        bounds = sorted(set(bounds))
        for k in range(len(bounds) - 1):
            a, b = bounds[k], bounds[k + 1] - 1
            while b >= a and not lines[b - 1].strip():
                b -= 1
            if b < a:
                continue
            heading = lines[a - 1] if re.match(r"^#{1,4} ", lines[a - 1]) else ""
            table = [i for i in range(a, b + 1) if lines[i - 1].startswith("|")]
            if len(table) >= 3:
                # table: header + separator, then one unit per row
                thead = table[0]
                cols = [c.strip() for c in lines[thead - 1].strip().strip("|").split("|")]
                pre = [i for i in range(a, b + 1) if i < thead]
                if pre and any(lines[i - 1].strip() for i in pre):
                    self._md_section(r, dtype, prefix, cluster, lines, pre[0], pre[-1], heading)
                for i in table[2:]:
                    cells = [c.strip() for c in lines[i - 1].strip().strip("|").split("|")]
                    rec = dict(zip(cols, cells))
                    self._md_row(r, dtype, prefix, cluster, lines, i, rec, cols)
                post = [i for i in range(table[-1] + 1, b + 1)]
                if post and any(lines[i - 1].strip() for i in post):
                    s0 = next(i for i in post if lines[i - 1].strip())
                    self._md_section(r, dtype, prefix, cluster, lines, s0, post[-1], heading)
            else:
                self._md_section(r, dtype, prefix, cluster, lines, a, b, heading)

    def _md_section(self, r, dtype, prefix, cluster, lines, a, b, heading):
        # split very long sections at blank lines/bullets
        max_len = 40
        chunks, s = [], a
        while s <= b:
            e = min(b, s + max_len - 1)
            if e < b:
                for j in range(e, s + 10, -1):
                    if not lines[j - 1].strip() or lines[j - 1].startswith("## "):
                        e = j
                        break
            chunks.append((s, e))
            s = e + 1
        for (s, e) in chunks:
            while s <= e and not lines[s - 1].strip():
                s += 1
            if s > e:
                continue
            raw = "\n".join(lines[s - 1:e])
            title = (heading or lines[s - 1]).lstrip("# ").strip()
            times = []
            dm = re.search(r"(\d{4})-(\d{2})-(\d{2})", title) or None
            if dm:
                times.append(t_date(dm.group(0), dm.group(0), "date in heading"))
            else:
                dm2 = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", title)
                if dm2:
                    times.append(t_date(dm2.group(0), f"{dm2.group(3)}-{dm2.group(2)}-{dm2.group(1)}", "date in heading"))
            self.add(f"{prefix}-L{s}", r, dtype, cluster, {"type": "lines", "start": s, "end": e}, title, raw, times=times)

    def _md_row(self, r, dtype, prefix, cluster, lines, i, rec, cols):
        times = []
        for k, v in rec.items():
            if k.lower() in ("date", "datum") and re.match(r"^\d{4}-\d{2}-\d{2}$", v or ""):
                times.append(t_date(v, v, f"column {k}"))
        title = " · ".join(v for v in list(rec.values())[:4] if v)
        self.add(f"{prefix}-L{i}", r, dtype, cluster, {"type": "lines", "start": i, "end": i}, title,
                 lines[i - 1], fields=rec, times=times)

    def plain_text(self, p: Path, r: str):
        lines = sources.raw_lines(r)
        self._md_section(r, "meta", "TXT-" + p.stem.upper(), p.name, lines, 1, len(lines), p.name)

    # ------------------------------------------------------------------ link people
    def link_people(self):
        """Person links from IDs, handles, email, names and plates – not only spelled-out names."""
        persons = self.people.persons
        # unique first/last names as weaker mentions
        first_count, last_count = {}, {}
        for h, p in persons.items():
            parts = p["name"].split()
            if len(parts) >= 2:
                first_count[parts[0].lower()] = first_count.get(parts[0].lower(), 0) + 1
                last_count[parts[-1].lower()] = last_count.get(parts[-1].lower(), 0) + 1
        strong, weak = {}, {}
        for h, p in persons.items():
            strong[h.lower()] = h
            for a in p["aliases"]:
                if a["kind"] in ("name", "email", "handle", "slack_id"):
                    strong[a["value"].lower()] = h
            parts = p["name"].split()
            if len(parts) >= 2:
                strong[p["name"].lower()] = h
                f, l = parts[0].lower(), parts[-1].lower()
                if first_count.get(f) == 1 and len(f) >= 3:
                    weak[f] = (h, "first name")
                if last_count.get(l) == 1 and len(l) >= 4:
                    weak[l] = (h, "last name")
        def rx(keys):
            keys = sorted(keys, key=len, reverse=True)
            return re.compile(r"(?<![\w.@])(" + "|".join(re.escape(k) for k in keys) + r")(?![\w@]|\.\w)", re.I)
        strong_rx, weak_rx = rx(strong), rx(weak)
        for u in self.units:
            have = {x.get("person") for x in u["people"]}
            txt = u["text"] or ""
            found = {}
            for m in strong_rx.finditer(txt):
                h = strong[m.group(1).lower()]
                found.setdefault(h, ("direct", f"name/handle \"{m.group(1)}\" in text"))
            for m in weak_rx.finditer(txt):
                h, what = weak[m.group(1).lower()]
                if h not in found:
                    found[h] = ("name_part", f"{what} \"{m.group(1)}\" in text (unique in registry, but not certain)")
            for h, (basis, via) in found.items():
                if h not in have:
                    u["people"].append({"person": h, "via": via, "basis": "mentioned" if basis == "direct" else "name_part", "role": "mentioned"})

    # ------------------------------------------------------------------ save
    def save(self) -> dict:
        st = SETTINGS.state_dir
        persons = sorted(self.people.persons.values(), key=lambda p: (not p["suspect"], p["name"]))
        counts = {}
        for u in self.units:
            for x in u["people"]:
                if x.get("person"):
                    counts[x["person"]] = counts.get(x["person"], 0) + 1
        for p in persons:
            p["unit_count"] = counts.get(p["id"], 0)
        write_json(st / "units.json", self.units, indent=None)
        write_json(st / "persons.json", persons)
        inv = {"bundle": str(SETTINGS.bundle), "files": self.files, "unit_count": len(self.units),
               "generated_at": datetime.now(timezone.utc).isoformat()}
        write_json(st / "inventory.json", inv)
        return inv


def run_ingest() -> dict:
    sources.raw_lines.cache_clear()
    return Ingest(SETTINGS.bundle).run()


if __name__ == "__main__":
    inv = run_ingest()
    ok = sum(1 for f in inv["files"] if f["status"] == "parsed")
    print(f"{len(inv['files'])} files, {ok} fully parsed, {inv['unit_count']} units")
    for f in inv["files"]:
        if f["status"] != "parsed":
            print(" ", f["file"], f["status"], f["error"] or "")
