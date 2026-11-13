"""Weitergeleitete E-Mails auswerten: Was ist das eigentliche Dokument – der Anhang oder die Mail?

- Weiterleitungen werden „ausgepackt“: Absender, Datum und Betreff der ursprünglichen Mail zählen.
- Was der Nutzer beim Weiterleiten dazuschreibt, wird zum Hinweis für die KI.
- Logos, Signaturbilder, Kalender- und Kontaktdateien werden ignoriert.
- Entscheidung: nur Anhänge / ganze Mail (als PDF) / nachfragen.
"""

from __future__ import annotations

import email
import email.policy
import html as _html
import logging
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from . import office

log = logging.getLogger(__name__)

DOC_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".bmp", ".doc", ".docx", ".xls",
                ".xlsx", ".odt", ".ods", ".rtf", ".eml", ".msg"}
IGNORE_SUFFIXES = {".ics", ".vcf", ".p7s", ".asc", ".sig", ".htm", ".html", ".gif"}
IGNORE_NAMES = {"winmail.dat", "smime.p7s", "signature.asc"}
SMALL_IMAGE = 40_000  # Bilder darunter sind meist Logos oder Signaturen

_FWD_MARKERS = re.compile(
    r"^\s*(?:-{2,}\s*(?:Weitergeleitete Nachricht|Forwarded message|Urspr(?:ü|ue)ngliche Nachricht|Original Message)"
    r"\s*-{2,}|Anfang der weitergeleiteten (?:Nachricht|E-Mail):?|Begin forwarded message:?)\s*$",
    re.I | re.M)
_HEADER_LINE = re.compile(r"^\s*\**(Von|From|Datum|Date|Gesendet|Sent|Betreff|Subject|An|To|Cc|Kopie)\**\s*:\s*\**\s*(.*)$", re.I)
_TRANSMITTAL = re.compile(
    r"\b(anbei|im anhang|in der anlage|als anlage|anhängend|angehängt|beigefügt|beiliegend|als pdf|"
    r"erhalten sie (?:ihre|ihren|ihr)|finden sie (?:ihre|ihren|ihr|die|den|das)|attached|attachment|enclosed)\b", re.I)
_SIGNOFF = re.compile(r"^\s*(--\s*$|Von meinem i(Phone|Pad) gesendet|Sent from my i(Phone|Pad)|Gesendet von)", re.I | re.M)
_IOS_NOTE = re.compile(r"^\s*(Von meinem i(Phone|Pad) gesendet|Sent from my i(Phone|Pad))\s*$", re.I | re.M)


@dataclass
class Attachment:
    name: str
    data: bytes
    content_type: str
    inline: bool = False
    content_id: str = ""

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class MailPlan:
    sender: str = ""          # Wer hat sie geschickt (bei Weiterleitung: der ursprüngliche Absender)
    forwarded_by: str = ""
    subject: str = ""
    date: str = ""            # JJJJ-MM-TT
    note: str = ""            # Notiz des Nutzers beim Weiterleiten
    body: str = ""            # Text der (ursprünglichen) Mail
    html: str = ""
    docs: list[Attachment] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    mode: str = "ask"         # attachments | mail | ask
    reason: str = ""

    def summary(self) -> dict:
        return {"sender": self.sender, "subject": self.subject, "date": self.date, "note": self.note,
                "excerpt": re.sub(r"\s+", " ", self.body)[:600], "docs": [d.name for d in self.docs],
                "skipped": self.skipped, "mode": self.mode, "reason": self.reason,
                "has_body": len(_essence(self.body)) >= 40}


def _clean_name(name: str, fallback: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", name or "").strip(" .")
    return name[:120] or fallback


def _attachments(msg: EmailMessage) -> list[Attachment]:
    out = []
    for i, part in enumerate(msg.walk()):
        if part.is_multipart() or part is msg:
            continue
        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "").lower()
        fname = part.get_filename()
        if ctype in ("text/plain", "text/html") and not fname:
            continue  # Mailtext selbst
        if ctype == "message/rfc822":
            continue  # wird beim Auspacken behandelt
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            data = b""
        if not data:
            continue
        guess = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/heic": ".heic",
                 "image/tiff": ".tif"}.get(ctype, "")
        out.append(Attachment(_clean_name(fname or "", f"Anhang {i}{guess}"), data, ctype, inline=disp == "inline",
                              content_id=(part.get("Content-ID") or "").strip("<> ")))
    return out


def _bodies(msg: EmailMessage) -> tuple[str, str]:
    plain = html = ""
    try:
        p = msg.get_body(preferencelist=("plain",))
        if p is not None:
            plain = p.get_content()
        h = msg.get_body(preferencelist=("html",))
        if h is not None:
            html = h.get_content()
    except Exception:
        log.exception("Mailtext nicht lesbar")
    if not plain and html:
        plain = office._html_to_text(html)
    return plain or "", html or ""


def _date(value) -> str:
    try:
        return parsedate_to_datetime(str(value)).date().isoformat()
    except Exception:
        m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", str(value or ""))
        if m:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        months = {"januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7, "august": 8,
                  "september": 9, "oktober": 10, "november": 11, "dezember": 12}
        short = {"jan": 1, "feb": 2, "mär": 3, "mar": 3, "apr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7, "aug": 8,
                 "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12}
        m = re.search(r"(\d{1,2})\.?\s*([A-Za-zäÄ]+)\.?\s+(\d{4})", str(value or ""))
        if m:
            word = m.group(2).lower()
            month = months.get(word) or short.get(word[:3])
            if month:
                return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}"
        m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", str(value or ""))  # Nov 9, 2026
        if m and short.get(m.group(1).lower()[:3]):
            return f"{m.group(3)}-{short[m.group(1).lower()[:3]]:02d}-{int(m.group(2)):02d}"
    return ""


def _essence(text: str) -> str:
    """Text ohne Zitate, Signatur, Weiterleitungs-Kopf und Leerraum."""
    lines = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith(">") or _HEADER_LINE.match(line):
            continue
        if _SIGNOFF.match(line):
            break
        lines.append(line)
    return re.sub(r"\s+", " ", "\n".join(lines)).strip()


def _split_inline_forward(text: str) -> tuple[str, dict, str] | None:
    """Erkennt eine eingebettete Weiterleitung: (Notiz, Kopfzeilen, ursprünglicher Text)."""
    m = _FWD_MARKERS.search(text or "")
    if not m:
        return None
    note = text[:m.start()]
    rest = text[m.end():].lstrip("\r\n")
    headers, body_lines, in_header = {}, [], True
    for line in rest.splitlines():
        if in_header:
            hm = _HEADER_LINE.match(line)
            if hm:
                key = hm.group(1).lower()
                key = {"from": "von", "date": "datum", "sent": "datum", "gesendet": "datum", "subject": "betreff",
                       "to": "an", "kopie": "cc"}.get(key, key)
                headers[key] = hm.group(2).strip()
                continue
            if not line.strip() and not headers:
                continue
            in_header = False
            if not line.strip():
                continue
        body_lines.append(line)
    return note, headers, "\n".join(body_lines)


def _clean_note(note: str) -> str:
    note = _IOS_NOTE.sub("", note or "")
    note = re.sub(r"\s+", " ", note).strip()
    return note[:300]


def analyze(path: Path) -> MailPlan:
    plan = MailPlan()
    if path.suffix.lower() == ".msg":
        return _analyze_msg(path, plan)
    with open(path, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=email.policy.default)
    outer_from = parseaddr(str(msg.get("From", "")))[1].lower()
    plan.subject = re.sub(r"^\s*((wg|fwd?|aw|re|weitergeleitet)\s*:\s*)+", "", str(msg.get("Subject", "")), flags=re.I).strip()
    plan.date = _date(msg.get("Date"))
    plan.sender = str(msg.get("From", ""))
    plain, html = _bodies(msg)
    atts = _attachments(msg)

    # Weiterleitung als Anhang (message/rfc822)
    inner = next((p for p in msg.walk() if p.get_content_type() == "message/rfc822"), None)
    if inner is not None:
        try:
            payload = inner.get_payload()
            inner_msg = payload[0] if isinstance(payload, list) else payload
            if not isinstance(inner_msg, EmailMessage):
                inner_msg = email.message_from_bytes(bytes(inner_msg), policy=email.policy.default)
            plan.forwarded_by = outer_from
            plan.note = _clean_note(plain)
            plan.sender = str(inner_msg.get("From", "")) or plan.sender
            plan.subject = str(inner_msg.get("Subject", "")) or plan.subject
            plan.date = _date(inner_msg.get("Date")) or plan.date
            plain, html = _bodies(inner_msg)
            atts = _attachments(inner_msg) + [a for a in atts if a.suffix not in (".eml",)]
        except Exception:
            log.exception("Weitergeleitete Mail (Anhang) nicht lesbar")
    else:
        fwd = _split_inline_forward(plain)
        if fwd:
            note, headers, body = fwd
            plan.forwarded_by = outer_from
            plan.note = _clean_note(note)
            plan.sender = headers.get("von", plan.sender)
            plan.subject = headers.get("betreff", plan.subject)
            plan.date = _date(headers.get("datum", "")) or plan.date
            plain = body
    plan.body = plain.strip()
    plan.html = html
    _pick_docs(plan, atts)
    _decide(plan)
    return plan


def _analyze_msg(path: Path, plan: MailPlan) -> MailPlan:
    try:
        import extract_msg
        m = extract_msg.Message(str(path))
        plan.sender = m.sender or ""
        plan.subject = m.subject or ""
        plan.date = _date(m.date) if m.date else ""
        plan.body = (m.body or "").strip()
        atts = []
        for i, a in enumerate(m.attachments):
            data = getattr(a, "data", None)
            if isinstance(data, bytes) and data:
                name = getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or f"Anhang {i}"
                atts.append(Attachment(_clean_name(name, f"Anhang {i}"), data, "", content_id=str(getattr(a, "cid", "") or "")))
        m.close()
        fwd = _split_inline_forward(plan.body)
        if fwd:
            note, headers, body = fwd
            plan.note = _clean_note(note)
            plan.sender = headers.get("von", plan.sender)
            plan.subject = headers.get("betreff", plan.subject)
            plan.date = _date(headers.get("datum", "")) or plan.date
            plan.body = body.strip()
        _pick_docs(plan, atts)
    except Exception:
        log.exception("E-Mail (.msg) konnte nicht ausgewertet werden")
    _decide(plan)
    return plan


def _valid(a: Attachment) -> bool:
    """Ist der Anhang wirklich ein lesbares Dokument (und nicht leer oder kaputt)?"""
    head = a.data[:8]
    try:
        if a.suffix == ".pdf" or a.content_type == "application/pdf":
            import pymupdf
            with pymupdf.open(stream=a.data, filetype="pdf") as d:
                return d.page_count > 0
        if a.suffix in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"):
            import io
            from PIL import Image
            with Image.open(io.BytesIO(a.data)) as im:
                im.verify()
            return True
        if a.suffix in (".docx", ".xlsx", ".odt", ".ods"):
            return head.startswith(b"PK")
        if a.suffix in (".doc", ".xls", ".msg"):
            return head.startswith(b"\xd0\xcf\x11\xe0")
        if a.suffix == ".rtf":
            return head.startswith(b"{\\rtf")
        return a.size > 0
    except Exception:
        return False


def _pick_docs(plan: MailPlan, atts: list[Attachment]) -> None:
    cids_in_html = set(re.findall(r"cid:([^\"'\s>)]+)", plan.html or "", re.I))
    seen = set()
    for a in atts:
        low = a.name.lower()
        is_image = a.content_type.startswith("image/") or a.suffix in (".jpg", ".jpeg", ".png", ".heic", ".bmp", ".tif", ".tiff")
        if low in IGNORE_NAMES or a.suffix in IGNORE_SUFFIXES:
            plan.skipped.append(a.name)
            continue
        if a.suffix not in DOC_SUFFIXES:
            plan.skipped.append(a.name)
            continue
        if is_image and (a.size < SMALL_IMAGE or (a.content_id and a.content_id in cids_in_html)):
            plan.skipped.append(a.name)  # Logo, Signatur oder eingebettetes Bild
            continue
        key = (low, a.size)
        if key in seen:
            continue
        if not _valid(a):
            plan.skipped.append(a.name + " (beschädigt)")
            continue
        seen.add(key)
        plan.docs.append(a)


def _decide(plan: MailPlan) -> None:
    core = _essence(plan.body)
    if not plan.docs:
        plan.mode, plan.reason = "mail", "Die Mail hat keinen Anhang – sie selbst ist das Dokument."
        return
    short = len(core) < 700
    if _TRANSMITTAL.search(core[:1500]) or short:
        plan.mode = "attachments"
        plan.reason = ("Die Mail ist nur das Anschreiben zum Anhang." if len(plan.docs) == 1
                       else f"Die Mail ist nur das Anschreiben zu {len(plan.docs)} Anhängen.")
        return
    plan.mode, plan.reason = "ask", "Die Mail hat einen längeren eigenen Text und einen Anhang."


# --- Mail als PDF ------------------------------------------------------------------------

def _safe_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|head|iframe|object|embed|form)\b.*?</\1>", " ", html)
    html = re.sub(r"(?is)<(img|link|meta|base|input|button)\b[^>]*>", " ", html)
    html = re.sub(r'(?i)\s(on\w+|src|background|style)\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', " ", html)
    m = re.search(r"(?is)<body[^>]*>(.*)</body>", html)
    return m.group(1) if m else html


def to_pdf(plan: MailPlan, target: Path) -> Path:
    """Die Mail als gut lesbares, durchsuchbares PDF (Kopf mit Absender, Datum, Betreff)."""
    import pymupdf

    def esc(t):
        return _html.escape(t or "")
    date = ".".join(reversed(plan.date.split("-"))) if plan.date else ""
    head = (f"<h2 style='font-size:15pt;margin:0 0 6pt 0'>{esc(plan.subject) or 'E-Mail'}</h2>"
            f"<p style='font-size:9.5pt;color:#555;margin:0 0 12pt 0'>Von: {esc(plan.sender)}"
            f"{'<br>Datum: ' + esc(date) if date else ''}</p><hr>")
    body_html = ""
    if plan.html and not plan.forwarded_by:
        body_html = _safe_html(plan.html)
    if not body_html.strip():
        body_html = "".join(f"<p style='margin:0 0 4pt 0'>{esc(line) or '&nbsp;'}</p>" for line in plan.body.splitlines())
    if plan.docs:
        body_html += "<hr><p style='font-size:9pt;color:#555'>Anhänge: " + esc(", ".join(d.name for d in plan.docs)) + "</p>"
    content = f"<div style='font-family:sans-serif;font-size:10.5pt'>{head}{body_html}</div>"
    tmp = target.with_name(target.name + ".part")
    try:
        story = pymupdf.Story(html=content)
        writer = pymupdf.DocumentWriter(str(tmp))
        rect = pymupdf.paper_rect("a4")
        where = rect + (50, 50, -50, -50)
        more = True
        pages = 0
        while more and pages < 200:
            dev = writer.begin_page(rect)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            pages += 1
        writer.close()
    except Exception:
        log.exception("Mail-PDF über HTML fehlgeschlagen – nehme Textfassung")
        from ..core import export
        doc = export._text_pages(plan.subject or "E-Mail",
                                 f"Von: {plan.sender}\nDatum: {date}\n\n{plan.body}")
        doc.save(str(tmp))
        doc.close()
    check = pymupdf.open(str(tmp))
    ok = check.page_count > 0
    check.close()
    if not ok:
        tmp.unlink(missing_ok=True)
        raise IOError("Mail-PDF ist leer.")
    tmp.replace(target)
    return target


def sender_address(value: str) -> str:
    return parseaddr(value or "")[1].lower()
