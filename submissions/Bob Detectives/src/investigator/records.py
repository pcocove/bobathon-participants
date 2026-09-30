"""Parse every source into typed records with exact citations.

Each record keeps:
  source   the citation of the line a human (or the scorer) should look at
  t        a timezone-aware datetime in the case's local zone (None if undated)
  t_raw    the timestamp exactly as written in the source
  basis    how t was derived: utc | offset | epoch | tzid | local-bare | date-only

Detection is by content signature (CSV headers, JSON shape, iCalendar markers, mbox
separators), not by the case's file names, so a different bundle with the same kinds
of exports parses the same way.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from .corpus import Corpus, Doc
from .util import UTC, stable_key


@dataclass
class Event:
    kind: str
    source: str
    t: datetime | None
    t_raw: str
    basis: str
    actor: str | None
    text: str
    attrs: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return stable_key(self.kind, self.source, self.t_raw, self.text[:40])

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "source": self.source,
            "t": self.t.isoformat() if self.t else None, "t_raw": self.t_raw,
            "basis": self.basis, "actor": self.actor, "text": self.text,
            "attrs": {k: v for k, v in self.attrs.items() if _jsonable(v)},
        }


def _jsonable(v) -> bool:
    try:
        json.dumps(v)
        return True
    except TypeError:
        return False


@dataclass
class User:
    id: str
    handle: str
    real_name: str
    title: str
    email: str
    tz: str
    source: str


@dataclass
class Permit:
    row: int
    source: str
    permit_id: str
    plate: str
    holder: str
    company: str
    vehicle: str
    colour: str
    level: str
    cells: list[str]


@dataclass
class Email:
    start: int
    source: str                  # path:start-end of the whole message
    date: datetime | None
    date_raw: str
    sender: str
    to: list[str]
    cc: list[str]
    subject: str
    headers: dict[str, tuple[int, str]]
    body: list[tuple[int, str]]  # (line number, text)

    @property
    def recipients(self) -> list[str]:
        return self.to + self.cc

    def body_text(self) -> str:
        return "\n".join(t for _, t in self.body)


@dataclass
class Interview:
    path: str
    title: str
    interviewee: str
    interviewee_line: int
    started: datetime | None
    header_line: int
    lines: list[dict]            # {line, ts, speaker, text, t}


@dataclass
class Claim:
    """An expense claim with the employee's narrative and the attached card detail."""
    claim_id: str
    handle: str
    heading_line: int
    narrative: str
    narrative_line: int
    items: list[dict]            # {line, detail, t, t_raw, amount}
    finance_note: str
    finance_line: int | None
    path: str


class Records:
    def __init__(self, corpus: Corpus):
        self.corpus = corpus
        self.warnings: list[str] = []
        self.users: dict[str, User] = {}          # slack id -> user
        self.channels: dict[str, str] = {}
        self.permits: list[Permit] = []
        self.emails: list[Email] = []
        self.interviews: list[Interview] = []
        self.claims: list[Claim] = []
        self.events: list[Event] = []
        self.time_basis: dict[str, str] = {}      # source path/prefix -> description
        self.zone = self._detect_zone()
        self._parse_all()

    # ----------------------------------------------------------------- helpers
    def _detect_zone(self) -> ZoneInfo:
        votes: Counter = Counter()
        for d in self.corpus.docs.values():
            if d.kind != "text":
                continue
            if d.path.endswith(".json") and d.lines and d.lines[0].strip() == "[":
                for ln in d.lines:
                    m = re.match(r'\s*"tz":\s*"([^"]+)"', ln)
                    if m:
                        votes[m.group(1)] += 1
            for ln in d.lines[:8]:
                m = re.match(r"X-WR-TIMEZONE:(.+)", ln.strip())
                if m:
                    votes[m.group(1).strip()] += 5
        name = votes.most_common(1)[0][0] if votes else "UTC"
        if not votes:
            self.warnings.append("no local time zone declared anywhere; using UTC")
        return ZoneInfo(name)

    def local(self, dt: datetime) -> datetime:
        return dt.astimezone(self.zone)

    def local_naive(self, dt: datetime) -> datetime:
        return dt.replace(tzinfo=self.zone)

    def _add(self, ev: Event) -> Event:
        self.events.append(ev)
        return ev

    # ------------------------------------------------------------------ driver
    def _parse_all(self) -> None:
        for path, doc in self.corpus.docs.items():
            try:
                if doc.kind == "xlsx":
                    self._parse_permits(doc)
                    continue
                if doc.kind != "text" or not doc.lines:
                    continue
                head = "\n".join(doc.lines[:6])
                if path.endswith(".json") and path.split("/")[-1] == "users.json":
                    self._parse_users(doc)
                elif path.endswith(".json") and path.split("/")[-1] == "channels.json":
                    self._parse_channels(doc)
                elif path.endswith(".json") and '"issues"' in head:
                    self._parse_jira(doc)
                elif path.endswith(".json") and doc.lines[0].strip() == "[" and '"ts"' in "\n".join(doc.lines[:12]):
                    pass  # slack day files parsed after users are known
                elif "BEGIN:VCALENDAR" in head:
                    self._parse_ics(doc)
                elif path.endswith(".mbox") or doc.lines[0].startswith("From "):
                    self._parse_mbox(doc)
                elif path.endswith(".csv"):
                    self._parse_csv(doc)
                elif re.search(r"^Interviewee:", head, re.M):
                    self._parse_interview(doc)
                elif path.endswith(".md"):
                    self._parse_markdown(doc)
            except Exception as exc:  # keep going; report
                self.warnings.append(f"{path}: parse error {type(exc).__name__}: {exc}")
        for path, doc in self.corpus.docs.items():
            if doc.kind == "text" and path.endswith(".json") and doc.lines and doc.lines[0].strip() == "[" \
                    and path.split("/")[-1] not in ("users.json", "channels.json"):
                try:
                    self._parse_slack_day(doc)
                except Exception as exc:
                    self.warnings.append(f"{path}: parse error {exc}")
        self.events.sort(key=lambda e: (e.t is None, e.t or datetime.min.replace(tzinfo=UTC)))

    # ------------------------------------------------------------------- slack
    def _parse_users(self, doc: Doc) -> None:
        data = json.loads("\n".join(doc.lines))
        # line of each user's "id" for citation
        id_lines = {}
        for i, ln in enumerate(doc.lines, 1):
            m = re.match(r'\s*"id":\s*"([^"]+)"', ln)
            if m:
                id_lines[m.group(1)] = i
        for u in data:
            prof = u.get("profile", {}) or {}
            self.users[u["id"]] = User(
                id=u["id"], handle=u.get("name", ""), real_name=u.get("real_name", ""),
                title=prof.get("title", ""), email=prof.get("email", ""), tz=u.get("tz", ""),
                source=f"{doc.path}:{id_lines.get(u['id'], 1)}",
            )
        self.time_basis[doc.path.rsplit("/", 1)[0] + "/"] = "Unix epoch seconds (UTC) in `ts`"

    def _parse_channels(self, doc: Doc) -> None:
        for c in json.loads("\n".join(doc.lines)):
            self.channels[c["id"]] = c["name"]

    def _parse_slack_day(self, doc: Doc) -> None:
        data = json.loads("\n".join(doc.lines))
        channel = doc.path.split("/")[-2] if "/" in doc.path else ""
        # map the i-th message to the line of its "text" field
        text_lines = [i for i, ln in enumerate(doc.lines, 1) if re.match(r'\s*"text":\s*"', ln)]
        for idx, msg in enumerate(data):
            if "ts" not in msg:
                continue
            line = text_lines[idx] if idx < len(text_lines) else 1
            t = datetime.fromtimestamp(float(msg["ts"]), tz=UTC).astimezone(self.zone)
            u = self.users.get(msg.get("user", ""))
            self._add(Event(
                kind="slack", source=f"{doc.path}:{line}", t=t, t_raw=msg["ts"], basis="epoch",
                actor=u.handle if u else msg.get("user"), text=msg.get("text", ""),
                attrs={"channel": channel, "user_id": msg.get("user"), "raw_line": doc.lines[line - 1]},
            ))

    # -------------------------------------------------------------------- jira
    def _parse_jira(self, doc: Doc) -> None:
        key = summary = reporter = created = None
        created_line = None
        in_comments = False
        pending: dict = {}
        for i, ln in enumerate(doc.lines, 1):
            s = ln.strip()
            m = re.match(r'"key":\s*"([^"]+)"', s)
            if m:
                key, in_comments = m.group(1), False
                summary = reporter = created = None
                continue
            m = re.match(r'"summary":\s*"(.*)",?$', s)
            if m and not in_comments:
                summary = _unjson(m.group(1))
                continue
            m = re.match(r'"reporter":\s*"?([^",]*)"?,?$', s)
            if m and not in_comments:
                reporter = m.group(1) or None
                continue
            if s.startswith('"comments"'):
                in_comments = True
                continue
            m = re.match(r'"author":\s*"([^"]*)"', s)
            if m and in_comments:
                pending = {"author": m.group(1)}
                continue
            m = re.match(r'"created":\s*"([^"]+)"', s)
            if m:
                if in_comments:
                    pending["created"] = m.group(1)
                else:
                    created, created_line = m.group(1), i
                continue
            m = re.match(r'"description":\s*"(.*)",?$', s)
            if m and key:
                t = datetime.fromisoformat(created) if created else None
                self._add(Event(
                    kind="jira", source=f"{doc.path}:{i}", t=self.local(t) if t else None,
                    t_raw=created or "", basis="offset", actor=reporter,
                    text=_unjson(m.group(1)) or (summary or ""),
                    attrs={"key": key, "summary": summary, "field": "description",
                           "created_line": created_line, "raw_line": ln},
                ))
                continue
            m = re.match(r'"body":\s*"(.*)",?$', s)
            if m and in_comments and key:
                c = pending.get("created")
                t = datetime.fromisoformat(c) if c else None
                self._add(Event(
                    kind="jira_comment", source=f"{doc.path}:{i}", t=self.local(t) if t else None,
                    t_raw=c or "", basis="offset", actor=pending.get("author"),
                    text=_unjson(m.group(1)), attrs={"key": key, "summary": summary, "raw_line": ln},
                ))
        self.time_basis[doc.path] = "ISO-8601 with explicit UTC offset per field"

    # ----------------------------------------------------------------- iCal
    def _parse_ics(self, doc: Doc) -> None:
        owner = doc.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        cal_name = None
        exporter = None
        ev: dict | None = None
        bases = Counter()
        for i, ln in enumerate(doc.lines, 1):
            s = ln.strip()
            if s.startswith("X-WR-CALNAME:"):
                cal_name = s.split(":", 1)[1]
            elif s.startswith("PRODID:"):
                exporter = s.split(":", 1)[1]
            elif s == "BEGIN:VEVENT":
                ev = {"begin": i}
            elif s == "END:VEVENT" and ev is not None:
                if ev.get("start"):
                    self._add(Event(
                        kind="calendar", source=f"{doc.path}:{ev.get('summary_line', ev['begin'])}",
                        t=ev["start"], t_raw=ev["start_raw"], basis=ev["basis"], actor=owner,
                        text=ev.get("summary", ""),
                        attrs={"end": ev.get("end").isoformat() if ev.get("end") else None,
                               "calendar": cal_name, "exporter": exporter,
                               "raw_line": doc.lines[ev.get("summary_line", ev["begin"]) - 1]},
                    ))
                ev = None
            elif ev is not None:
                for field_name in ("DTSTART", "DTEND"):
                    if s.startswith(field_name):
                        dt, basis = self._ics_time(s)
                        bases[basis] += 1
                        if field_name == "DTSTART":
                            ev.update(start=dt, start_raw=s, basis=basis)
                        else:
                            ev["end"] = dt
                if s.startswith("SUMMARY:"):
                    ev["summary"] = s.split(":", 1)[1]
                    ev["summary_line"] = i
        basis = ", ".join(f"{b} ({n})" for b, n in bases.items())
        self.time_basis[doc.path] = f"{exporter or 'iCalendar'}: {basis}"

    def _ics_time(self, s: str) -> tuple[datetime | None, str]:
        head, val = s.split(":", 1)
        val = val.strip()
        m = re.search(r"TZID=([^;:]+)", head)
        try:
            if val.endswith("Z"):
                return datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).astimezone(self.zone), "utc"
            if "T" in val:
                naive = datetime.strptime(val, "%Y%m%dT%H%M%S")
                zone = ZoneInfo(m.group(1)) if m else self.zone
                return naive.replace(tzinfo=zone).astimezone(self.zone), "tzid" if m else "floating"
            d = datetime.strptime(val, "%Y%m%d")
            return d.replace(tzinfo=self.zone), "date-only"
        except Exception:
            return None, "unparsed"

    # ------------------------------------------------------------------ mbox
    def _parse_mbox(self, doc: Doc) -> None:
        starts = [i for i, ln in enumerate(doc.lines, 1)
                  if ln.startswith("From ") and re.match(r"From \S+@\S+ ", ln)]
        starts.append(len(doc.lines) + 1)
        for a, b in zip(starts, starts[1:]):
            headers: dict[str, tuple[int, str]] = {}
            body: list[tuple[int, str]] = []
            in_headers = True
            last = None
            for i in range(a + 1, b):
                ln = doc.lines[i - 1]
                if in_headers:
                    if ln.strip() == "":
                        in_headers = False
                        continue
                    if ln[:1] in (" ", "\t") and last:
                        n, v = headers[last]
                        headers[last] = (n, v + " " + ln.strip())
                        continue
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        last = k.strip().lower()
                        headers[last] = (i, v.strip())
                else:
                    body.append((i, ln[1:] if ln.startswith(">From ") else ln))
            while body and not body[-1][1].strip():
                body.pop()
            date_raw = headers.get("date", (0, ""))[1]
            try:
                dt = self.local(parsedate_to_datetime(date_raw)) if date_raw else None
            except Exception:
                dt = None
            end = body[-1][0] if body else b - 1
            em = Email(
                start=a, source=f"{doc.path}:{a}-{end}", date=dt, date_raw=date_raw,
                sender=_addr(headers.get("from", (0, ""))[1]),
                to=_addrs(headers.get("to", (0, ""))[1]), cc=_addrs(headers.get("cc", (0, ""))[1]),
                subject=headers.get("subject", (0, ""))[1], headers=headers, body=body,
            )
            self.emails.append(em)
            sline = headers.get("subject", (a, ""))[0]
            self._add(Event(
                kind="email", source=f"{doc.path}:{sline}", t=dt, t_raw=date_raw, basis="offset",
                actor=em.sender.split("@")[0] if em.sender else None, text=em.subject,
                attrs={"to": em.to, "cc": em.cc, "message": em.source},
            ))
        self.time_basis[doc.path] = "RFC 2822 Date header with explicit offset"

    # ------------------------------------------------------------------- CSV
    def _parse_csv(self, doc: Doc) -> None:
        comments = [ln for ln in doc.lines if ln.startswith("#")]
        header_i = next((i for i, ln in enumerate(doc.lines) if ln and not ln.startswith("#")), None)
        if header_i is None:
            return
        header = doc.lines[header_i]
        delim = ";" if header.count(";") > header.count(",") else ","
        cols = [c.strip().lower() for c in next(csv.reader([header], delimiter=delim))]
        note = " ".join(comments)
        if {"cardholder", "merchant"} <= set(cols) or any("card" in c for c in cols):
            self._parse_card_feed(doc, header_i, cols, delim, note)
        elif any(c in ("kennzeichen", "plate", "licence_plate", "license_plate") for c in cols):
            self._parse_garage(doc, header_i, cols, delim, note)
        else:
            self.time_basis[doc.path] = "unrecognised CSV"

    def _parse_card_feed(self, doc: Doc, hi: int, cols: list[str], delim: str, note: str) -> None:
        tcol = next(c for c in cols if "time" in c or "date" in c)
        is_utc = "utc" in tcol or "utc" in note.lower()
        for i in range(hi + 1, len(doc.lines)):
            ln = doc.lines[i]
            if not ln.strip() or ln.startswith("#"):
                continue
            row = dict(zip(cols, next(csv.reader([ln], delimiter=delim))))
            raw = row.get(tcol, "")
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC if is_utc else self.zone)
                dt = self.local(dt)
            except Exception:
                continue
            self._add(Event(
                kind="card", source=f"{doc.path}:{i + 1}", t=dt, t_raw=raw, basis="utc" if is_utc else "local-bare",
                actor=row.get("cardholder"),
                text=f"{row.get('merchant', '')}, {row.get('merchant_city', '')}",
                attrs={"merchant": row.get("merchant", ""), "city": row.get("merchant_city", ""),
                       "mcc": row.get("mcc", ""), "amount": row.get("amount_chf") or row.get("amount"),
                       "last4": row.get("card_last4", ""), "txn": row.get("txn_id", ""), "raw_line": ln},
            ))
        self.time_basis[doc.path] = ("UTC (declared in header)" if is_utc else "local, no zone declared")

    def _parse_garage(self, doc: Doc, hi: int, cols: list[str], delim: str, note: str) -> None:
        def col(*names):
            return next((c for c in cols if c in names), None)
        cd, ct = col("datum", "date"), col("uhrzeit", "time")
        cp, cr = col("kennzeichen", "plate"), col("richtung", "direction")
        cc = col("erkennung", "confidence")
        for i in range(hi + 1, len(doc.lines)):
            ln = doc.lines[i]
            if not ln.strip() or ln.startswith("#"):
                continue
            parts = ln.split(delim)
            row = dict(zip(cols, parts))
            try:
                naive = datetime.strptime(f"{row[cd]} {row[ct]}", "%d.%m.%Y %H:%M:%S")
            except Exception:
                try:
                    naive = datetime.strptime(f"{row[cd]} {row[ct]}", "%d.%m.%Y %H:%M")
                except Exception:
                    continue
            plate = row.get(cp, "").strip()
            conf = int(row[cc]) if cc and row.get(cc, "").strip().isdigit() else None
            self._add(Event(
                kind="garage", source=f"{doc.path}:{i + 1}", t=naive.replace(tzinfo=self.zone),
                t_raw=f"{row[cd]} {row[ct]}", basis="local-bare", actor=plate,
                text=f"{plate} {row.get(cr, '')}",
                attrs={"plate": plate, "direction": row.get(cr, "").strip().lower(), "confidence": conf,
                       "degraded": "?" in plate, "naive": naive.isoformat(), "raw_line": ln},
            ))
        self.time_basis[doc.path] = "bare local wall-clock, no zone declared (" + (note[:120] or "no header note") + ")"

    # ------------------------------------------------------------- permits
    def _parse_permits(self, doc: Doc) -> None:
        header_row = None
        for r, cells in sorted(doc.rows.items()):
            low = [c.lower() for c in cells]
            if any("kennzeichen" in c or "plate" in c for c in low):
                header_row = r
                hdr = low
                break
        if header_row is None:
            return

        def idx(*keys):
            for k in keys:
                for j, h in enumerate(hdr):
                    if k in h:
                        return j
            return None
        ip, ih = idx("kennzeichen", "plate"), idx("inhaber", "holder", "name")
        ic, iv = idx("firma", "company"), idx("fahrzeug", "vehicle")
        ifarbe, ie = idx("farbe", "colour", "color"), idx("ebene", "level")
        iid = idx("bewilligung", "permit")
        for r, cells in sorted(doc.rows.items()):
            if r <= header_row:
                continue

            def g(j):
                return cells[j] if j is not None and j < len(cells) else ""
            if not g(ip):
                continue
            self.permits.append(Permit(
                row=r, source=f"{doc.path}:{r}", permit_id=g(iid), plate=g(ip).strip(), holder=g(ih),
                company=g(ic), vehicle=g(iv), colour=g(ifarbe), level=g(ie), cells=cells,
            ))

    # ------------------------------------------------------------- interviews
    def _parse_interview(self, doc: Doc) -> None:
        interviewee, iv_line, started, date_line = "", 0, None, 0
        for i, ln in enumerate(doc.lines[:12], 1):
            if ln.startswith("Interviewee:"):
                interviewee, iv_line = ln.split(":", 1)[1].strip(), i
            if ln.startswith("Date:"):
                date_line = i
                md = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", ln)
                mt = re.search(r"(?:start|Beginn)\s+(\d{1,2}):(\d{2})", ln, re.I)
                if md:
                    d = datetime(int(md.group(3)), int(md.group(2)), int(md.group(1)),
                                 int(mt.group(1)) if mt else 0, int(mt.group(2)) if mt else 0)
                    started = d.replace(tzinfo=self.zone)
        lines = []
        for i, ln in enumerate(doc.lines, 1):
            m = re.match(r"^\[(\d\d):(\d\d):(\d\d)\]\s+([^:]{1,24}):\s+(.*)$", ln)
            if not m:
                continue
            off = timedelta(hours=int(m.group(1)), minutes=int(m.group(2)), seconds=int(m.group(3)))
            lines.append({"line": i, "ts": ln[1:9], "speaker": m.group(4).strip(), "text": m.group(5),
                          "t": (started + off) if started else None})
        title = doc.lines[0].strip() if doc.lines else doc.path
        self.interviews.append(Interview(doc.path, title, interviewee, iv_line, started, date_line, lines))
        self.time_basis[doc.path] = "recording start (local) + elapsed offset"

    # ------------------------------------------------------------ markdown
    def _parse_markdown(self, doc: Doc) -> None:
        text = "\n".join(doc.lines[:40])
        if re.search(r"^### [A-Z]{2,4}-\d+ · ", "\n".join(doc.lines), re.M) and "Requester:" in "\n".join(doc.lines):
            self._parse_tickets(doc)
        if re.search(r"^\|\s*Date\s*\|\s*Employee\s*\|", text, re.M | re.I) or "### REIMB-" in "\n".join(doc.lines):
            self._parse_expenses(doc)
        if re.search(r"^\|\s*Req", text, re.M | re.I):
            self._parse_table_log(doc, kind="diligence")
        if re.search(r"^### .+ — \d{4}-\d{2}-\d{2}\s*$", "\n".join(doc.lines), re.M):
            self._parse_meetings(doc)
        if re.search(r"^## (Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w* \d{1,2}\.\d{1,2}\.\d{4}", "\n".join(doc.lines), re.M):
            self._parse_notebook(doc)

    def _parse_tickets(self, doc: Doc) -> None:
        cur = None
        for i, ln in enumerate(doc.lines, 1):
            m = re.match(r"^### ([A-Z]{2,4}-\d+) · (.+)$", ln)
            if m:
                cur = {"id": m.group(1), "title": m.group(2), "line": i}
                continue
            if cur is None:
                continue
            m = re.match(r"^Requester:\s*(\S+)\s*·\s*Opened:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", ln)
            if m:
                naive = datetime.strptime(m.group(2), "%Y-%m-%d %H:%M")
                self._add(Event(
                    kind="ticket", source=f"{doc.path}:{cur['line']}", t=naive.replace(tzinfo=self.zone),
                    t_raw=m.group(2), basis="local-bare", actor=m.group(1),
                    text=f"{cur['id']} · {cur['title']}", attrs={"ticket": cur["id"], "title": cur["title"],
                                                                "raw_line": doc.lines[cur["line"] - 1]},
                ))
                continue
            m = re.match(r"^- \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*([^:]+):\s*(.*)$", ln)
            if m:
                naive = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
                self._add(Event(
                    kind="ticket_comment", source=f"{doc.path}:{i}", t=naive.replace(tzinfo=self.zone),
                    t_raw=m.group(1), basis="local-bare", actor=m.group(2).strip(), text=m.group(3),
                    attrs={"ticket": cur["id"], "raw_line": ln},
                ))
        self.time_basis[doc.path] = "bare local 'YYYY-MM-DD HH:MM', no zone declared"

    def _parse_expenses(self, doc: Doc) -> None:
        claim: Claim | None = None
        for i, ln in enumerate(doc.lines, 1):
            m = re.match(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([\w.\-]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|", ln)
            if m and claim is None:
                d = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=self.zone)
                self._add(Event(
                    kind="expense", source=f"{doc.path}:{i}", t=d, t_raw=m.group(1), basis="date-only",
                    actor=m.group(2), text=f"{m.group(3)} {m.group(4)} ({m.group(5)}; {m.group(6)})",
                    attrs={"merchant": m.group(3), "amount": m.group(4), "category": m.group(5),
                           "note": m.group(6), "raw_line": ln},
                ))
                continue
            m = re.match(r"^### (REIMB-[\w-]+) · ([\w.\-]+) · (.*)$", ln)
            if m:
                claim = Claim(m.group(1), m.group(2), i, "", 0, [], "", None, doc.path)
                self.claims.append(claim)
                continue
            if claim is None:
                continue
            m = re.match(r'^Narrative:\s*"?(.*?)"?\s*$', ln)
            if m:
                claim.narrative, claim.narrative_line = m.group(1), i
                continue
            m = re.match(r"^\|\s*Card\s*\|\s*(.*?)\s*\|\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*\|\s*(.*?)\s*\|", ln)
            if m:
                naive = datetime.strptime(m.group(2), "%Y-%m-%d %H:%M")
                claim.items.append({"line": i, "detail": m.group(1), "t": naive.replace(tzinfo=self.zone),
                                    "t_raw": m.group(2), "amount": m.group(3)})
                continue
            if ln.startswith("Finance:"):
                claim.finance_note, claim.finance_line = ln.split(":", 1)[1].strip(), i
        if self.claims:
            self.time_basis[doc.path] = "claim dates are date-only; attached card detail says 'card-terminal times' (local)"

    def _parse_table_log(self, doc: Doc, kind: str) -> None:
        cols = None
        for i, ln in enumerate(doc.lines, 1):
            if not ln.startswith("|"):
                cols = None if not ln.strip() == "" else cols
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            nxt = doc.lines[i] if i < len(doc.lines) else ""
            if nxt.startswith("|") and set(nxt.replace("|", "").strip()) <= {"-", " ", ":"}:
                cols = [c.lower() for c in cells]
                continue
            if set(ln.replace("|", "").strip()) <= {"-", " ", ":"} or cols is None:
                continue
            row = dict(zip(cols, cells))
            dval = next((v for k, v in row.items() if "date" in k), "")
            try:
                d = datetime.strptime(dval, "%Y-%m-%d").replace(tzinfo=self.zone)
            except Exception:
                d = None
            owner = next((v for k, v in row.items() if "owner" in k), None)
            self._add(Event(
                kind=kind, source=f"{doc.path}:{i}", t=d, t_raw=dval, basis="date-only", actor=owner,
                text=" · ".join(cells), attrs={**row, "raw_line": ln},
            ))

    def _parse_meetings(self, doc: Doc) -> None:
        cur = None
        for i, ln in enumerate(doc.lines, 1):
            m = re.match(r"^### (.+?) — (.+?) — (\d{4}-\d{2}-\d{2})\s*$", ln)
            if m:
                people = [p.strip() for p in re.split(r"/|,", m.group(2))]
                d = datetime.strptime(m.group(3), "%Y-%m-%d").replace(tzinfo=self.zone)
                cur = {"type": m.group(1), "people": people, "t": d, "line": i}
                self._add(Event(kind="meeting", source=f"{doc.path}:{i}", t=d, t_raw=m.group(3),
                                basis="date-only", actor=people[0] if people else None,
                                text=ln.lstrip("# "), attrs={"people": people, "type": m.group(1), "raw_line": ln}))
                continue
            if ln.startswith("### ") or ln.startswith("# "):
                cur = None
                continue
            if cur and ln.strip():
                self._add(Event(kind="meeting_note", source=f"{doc.path}:{i}", t=cur["t"],
                                t_raw=cur["t"].date().isoformat(), basis="date-only",
                                actor=cur["people"][0] if cur["people"] else None, text=ln.strip(),
                                attrs={"people": cur["people"], "heading_line": cur["line"], "raw_line": ln}))

    def _parse_notebook(self, doc: Doc) -> None:
        day: datetime | None = None
        year = None
        for i, ln in enumerate(doc.lines, 1):
            m = re.match(r"^## (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w* (\d{1,2})\.(\d{1,2})\.(\d{4})", ln)
            if m:
                year = int(m.group(3))
                day = datetime(year, int(m.group(2)), int(m.group(1))).replace(tzinfo=self.zone)
                continue
            if not ln.strip() or day is None:
                continue
            t, raw = day, day.date().isoformat()
            mi = re.search(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w* (\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?,?\s+(\d{1,2}):(\d{2})", ln)
            if mi:
                y = int(mi.group(3)) if mi.group(3) else year
                t = datetime(y, int(mi.group(2)), int(mi.group(1)), int(mi.group(4)), int(mi.group(5))).replace(tzinfo=self.zone)
                raw = mi.group(0)
            self._add(Event(kind="notebook", source=f"{doc.path}:{i}", t=t, t_raw=raw,
                            basis="local-bare" if mi else "date-only", actor=None, text=ln.strip(),
                            attrs={"raw_line": ln}))

    # ------------------------------------------------------------- lookups
    def by_kind(self, *kinds: str) -> list[Event]:
        return [e for e in self.events if e.kind in kinds]

    def between(self, start: datetime, end: datetime, kinds: tuple[str, ...] | None = None) -> list[Event]:
        return [e for e in self.events if e.t and start <= e.t <= end and (kinds is None or e.kind in kinds)]


def _unjson(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except Exception:
        return s


def _addr(v: str) -> str:
    m = re.search(r"[\w.+\-]+@[\w.\-]+", v)
    return m.group(0).lower() if m else v.strip().lower()


def _addrs(v: str) -> list[str]:
    return [a.lower() for a in re.findall(r"[\w.+\-]+@[\w.\-]+", v)]
