"""Office-Dateien und E-Mails: Umwandlung für Vorschau und Textauszug."""

from __future__ import annotations

import email
import email.policy
import hashlib
import logging
import re
import subprocess
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)

OFFICE_SUFFIXES = {".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp"}
EMAIL_SUFFIXES = {".eml", ".msg"}

CREATE_NO_WINDOW = 0x08000000


def _file_key(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:32]


def office_to_pdf(path: Path, timeout: int = 180) -> Path | None:
    """Wandelt eine Office-Datei mit dem mitgelieferten LibreOffice in ein PDF um (zwischengespeichert)."""
    soffice = paths.soffice_path()
    if soffice is None:
        return None
    out_dir = paths.cache_dir() / "office-pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{_file_key(path)}.pdf"
    if target.exists():
        return target
    work = out_dir / "arbeit"
    work.mkdir(exist_ok=True)
    profile = paths.lo_profile_dir().as_uri()
    cmd = [str(soffice), f"-env:UserInstallation={profile}", "--headless", "--norestore",
           "--convert-to", "pdf", "--outdir", str(work), str(path)]
    try:
        kwargs = {"creationflags": CREATE_NO_WINDOW} if paths.IS_WINDOWS else {}
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=timeout, check=False, **kwargs)
    except (subprocess.TimeoutExpired, OSError):
        log.exception("LibreOffice-Umwandlung fehlgeschlagen")
        return None
    produced = work / (path.stem + ".pdf")
    if produced.exists():
        produced.replace(target)
        return target
    return None


def office_text_fallback(path: Path) -> str:
    """Textauszug ohne LibreOffice (nur .docx/.xlsx)."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            import docx  # python-docx
            d = docx.Document(str(path))
            parts = [p.text for p in d.paragraphs]
            for table in d.tables:
                for row in table.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
            return "\n".join(parts)
        if suffix == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            lines = []
            for ws in wb.worksheets[:3]:
                lines.append(f"[{ws.title}]")
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i > 200:
                        break
                    vals = [str(v) for v in row if v is not None]
                    if vals:
                        lines.append(" | ".join(vals))
            return "\n".join(lines)
        if suffix == ".csv":
            return path.read_text(encoding="utf-8", errors="replace")[:20000]
    except Exception:
        log.exception("Office-Text konnte nicht gelesen werden")
    return ""


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def parse_email(path: Path) -> dict:
    """Liest eine E-Mail (.eml oder .msg) in eine einfache Ansicht."""
    view = {"from": "", "to": "", "subject": "", "date": "", "body": "", "attachments": []}
    if path.suffix.lower() == ".msg":
        try:
            import extract_msg
            msg = extract_msg.Message(str(path))
            view["from"] = msg.sender or ""
            view["to"] = msg.to or ""
            view["subject"] = msg.subject or ""
            view["date"] = str(msg.date or "")
            body = msg.body or ""
            if not body.strip() and getattr(msg, "htmlBody", None):
                raw = msg.htmlBody
                body = _html_to_text(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
            view["body"] = body
            view["attachments"] = [getattr(a, "longFilename", None) or getattr(a, "shortFilename", "") or "Anhang"
                                   for a in msg.attachments]
            msg.close()
        except Exception:
            log.exception("E-Mail (.msg) konnte nicht gelesen werden")
        return view

    try:
        with open(path, "rb") as fh:
            msg = email.message_from_binary_file(fh, policy=email.policy.default)
        view["from"] = str(msg.get("From", ""))
        view["to"] = str(msg.get("To", ""))
        view["subject"] = str(msg.get("Subject", ""))
        raw_date = msg.get("Date")
        if raw_date:
            try:
                view["date"] = parsedate_to_datetime(str(raw_date)).strftime("%d.%m.%Y %H:%M")
            except Exception:
                view["date"] = str(raw_date)
        body_part = msg.get_body(preferencelist=("plain", "html"))
        if body_part is not None:
            content = body_part.get_content()
            view["body"] = _html_to_text(content) if body_part.get_content_subtype() == "html" else content
        view["attachments"] = [part.get_filename() or "Anhang" for part in msg.iter_attachments()]
    except Exception:
        log.exception("E-Mail (.eml) konnte nicht gelesen werden")
    return view


def email_text(view: dict) -> str:
    lines = [
        f"E-Mail von: {view.get('from', '')}",
        f"An: {view.get('to', '')}",
        f"Datum: {view.get('date', '')}",
        f"Betreff: {view.get('subject', '')}",
        "",
        view.get("body", ""),
    ]
    if view.get("attachments"):
        lines.append("\nAnhänge: " + ", ".join(view["attachments"]))
    return "\n".join(lines)
