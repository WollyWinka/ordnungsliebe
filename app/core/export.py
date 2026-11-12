"""Mappen exportieren: als ein PDF mit Inhaltsverzeichnis oder als ZIP mit Kopien.

Die Originale werden nur gelesen, nie verändert oder verschoben.
"""

from __future__ import annotations

import logging
import time
import zipfile
from pathlib import Path

import pymupdf

from ..docs import ocr, office, reader
from . import naming

log = logging.getLogger(__name__)

A4 = pymupdf.paper_rect("a4")


def export_dir() -> Path:
    """Downloads-Ordner (sonst Desktop, sonst Benutzerordner)."""
    home = Path.home()
    for cand in (home / "Downloads", home / "Desktop", home):
        if cand.is_dir():
            return cand
    return home


_FONTS: dict[str, pymupdf.Font] = {}


def _font(bold: bool = False) -> pymupdf.Font:
    key = "hebo" if bold else "helv"
    if key not in _FONTS:
        _FONTS[key] = pymupdf.Font(key)
    return _FONTS[key]


def _text(page, pos, text: str, size: float = 11, bold: bool = False, color=(0, 0, 0)) -> None:
    """Text mit Unicode-Zeichen (– › € …) schreiben."""
    tw = pymupdf.TextWriter(page.rect)
    tw.append(pos, text, font=_font(bold), fontsize=size)
    tw.write_text(page, color=color)


def _text_pages(title: str, text: str) -> pymupdf.Document:
    doc = pymupdf.open()
    body = (text or "").strip() or "(kein Text)"
    rect = pymupdf.Rect(56, 56, A4.width - 56, A4.height - 56)
    first = True
    rest = body
    for _ in range(300):
        page = doc.new_page(width=A4.width, height=A4.height)
        box = rect
        if first:
            _text(page, (56, 72), title[:90], 14, bold=True)
            box = pymupdf.Rect(56, 92, rect.x1, rect.y1)
            first = False
        tw = pymupdf.TextWriter(page.rect)
        over = tw.fill_textbox(box, rest, font=_font(), fontsize=10.5)
        tw.write_text(page)
        if not over:
            break
        rest = "\n".join(line for line, _ in over) if over and isinstance(over[0], tuple) else "\n".join(over)
    return doc


def _as_pdf(path: Path) -> pymupdf.Document:
    kind = reader.file_kind(path)
    if kind == "pdf":
        doc = pymupdf.open(str(path))
        if doc.needs_pass and not doc.authenticate(""):
            doc.close()
            return _text_pages(path.name, "Dieses PDF ist mit einem Passwort geschützt und konnte nicht "
                                          "eingefügt werden. Das Original liegt unverändert in der Ablage.")
        return doc
    if kind == "image":
        return ocr.image_to_pdf(path)
    if kind == "office":
        pdf = office.office_to_pdf(path)
        if pdf is not None:
            return pymupdf.open(str(pdf))
        return _text_pages(path.name, office.office_text_fallback(path))
    if kind == "email":
        view = office.parse_email(path)
        return _text_pages(view.get("subject") or path.name, office.email_text(view))
    return _text_pages(path.name, "Dieser Dateityp lässt sich nicht als PDF darstellen.")


def export_pdf(name: str, docs: list[dict], target_dir: Path | None = None) -> Path:
    """docs: [{"path", "title"}] → ein PDF mit Inhaltsverzeichnis und Lesezeichen."""
    out = pymupdf.open()
    out.new_page(width=A4.width, height=A4.height)  # Platz für das Inhaltsverzeichnis
    entries = []
    for d in docs:
        p = Path(d["path"])
        start = out.page_count + 1
        try:
            src = _as_pdf(p)
        except Exception:
            log.exception("Dokument konnte nicht eingefügt werden: %s", p)
            src = _text_pages(p.name, "Dieses Dokument konnte nicht eingefügt werden.")
        try:
            out.insert_pdf(src)
        finally:
            src.close()
        entries.append((d.get("title") or p.stem, start))

    # Inhaltsverzeichnis (bei vielen Dokumenten über mehrere Seiten, mit anklickbaren Einträgen)
    first_rows, more_rows, line = 36, 39, 18
    extra = max(0, -(-(len(entries) - first_rows) // more_rows))
    for k in range(extra):
        out.new_page(pno=1 + k, width=A4.width, height=A4.height)
    shift = extra
    page = out[0]
    y = 72
    _text(page, (56, y), name, 20, bold=True)
    y += 22
    _text(page, (56, y), f"Zusammengestellt am {time.strftime('%d.%m.%Y')} · {len(entries)} Dokumente",
          10, color=(0.4, 0.4, 0.4))
    y += 30
    pidx = 0
    for i, (title, start) in enumerate(entries, 1):
        if y > A4.height - 60:
            pidx += 1
            page = out[pidx]
            y = 72
        label = f"{i}.  {title}"
        if len(label) > 80:
            label = label[:79] + "…"
        real = start + shift  # Seitennummer (1-basiert) nach dem Verzeichnis
        _text(page, (56, y), label, 11)
        _text(page, (A4.width - 100, y), f"Seite {real}", 11)
        page.insert_link({"kind": pymupdf.LINK_GOTO, "page": real - 1,
                          "from": pymupdf.Rect(52, y - 12, A4.width - 52, y + 4)})
        y += line
    out.set_toc([[1, "Inhalt", 1]] + [[1, t, s + shift] for t, s in entries])
    target = naming.unique_path((target_dir or export_dir()) / naming.clean_filename(f"Mappe {name}", ".pdf"))
    tmp = target.with_name(target.name + ".part")
    out.save(str(tmp), garbage=3, deflate=True)
    out.close()
    check = pymupdf.open(str(tmp))
    pages = check.page_count
    check.close()
    if pages < len(entries) + 1:
        tmp.unlink(missing_ok=True)
        raise IOError("Die Mappe konnte nicht vollständig geschrieben werden.")
    tmp.replace(target)
    return target


def export_zip(name: str, docs: list[dict], target_dir: Path | None = None) -> Path:
    target = naming.unique_path((target_dir or export_dir()) / naming.clean_filename(f"Mappe {name}", ".zip"))
    tmp = target.with_name(target.name + ".part")
    used: set[str] = set()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i, d in enumerate(docs, 1):
            p = Path(d["path"])
            arc = f"{i:02d} {p.name}"
            while arc.lower() in used:
                arc = f"{i:02d}b {p.name}"
            used.add(arc.lower())
            zf.write(str(p), arc)
    with zipfile.ZipFile(tmp) as zf:
        if zf.testzip() is not None or len(zf.namelist()) != len(docs):
            tmp.unlink(missing_ok=True)
            raise IOError("Die ZIP-Datei konnte nicht vollständig geschrieben werden.")
    tmp.replace(target)
    return target
