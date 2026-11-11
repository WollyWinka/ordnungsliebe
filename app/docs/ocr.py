"""Texterkennung (OCR) über die in PyMuPDF eingebaute Tesseract-Engine.

Es wird nur der deutsche Sprachdatensatz (deu.traineddata) benötigt, kein separates
Tesseract-Programm.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from .. import paths

log = logging.getLogger(__name__)

OCR_DPI = 300
MIN_PAGE_CHARS = 25          # weniger Text auf einer Seite → als Scan behandeln
OCR_LANG = "deu+eng"


class OcrUnavailable(RuntimeError):
    pass


def _tessdata() -> str:
    td = paths.tessdata_dir()
    if td is None:
        raise OcrUnavailable("Die Sprachdaten für die Texterkennung fehlen.")
    return str(td)


def _lang() -> str:
    td = paths.tessdata_dir()
    if td is not None and (td / "eng.traineddata").exists():
        return OCR_LANG
    return "deu"


def page_needs_ocr(page: "pymupdf.Page") -> bool:
    return len(page.get_text().strip()) < MIN_PAGE_CHARS


def ocr_textpage(page: "pymupdf.Page"):
    return page.get_textpage_ocr(language=_lang(), dpi=OCR_DPI, full=True, tessdata=_tessdata())


def page_text(page: "pymupdf.Page") -> tuple[str, bool]:
    """Text einer Seite; bei Scans per OCR. Gibt (text, ocr_verwendet) zurück."""
    text = page.get_text()
    if len(text.strip()) >= MIN_PAGE_CHARS:
        return text, False
    try:
        tp = ocr_textpage(page)
        return page.get_text(textpage=tp), True
    except OcrUnavailable:
        raise
    except Exception:
        log.exception("Texterkennung fehlgeschlagen")
        return text, False


def add_text_layer(doc: "pymupdf.Document") -> int:
    """Legt auf alle gescannten Seiten eine unsichtbare Textebene. Gibt die Anzahl Seiten zurück.

    Das Originalbild bleibt unverändert; nur der erkannte Text wird unsichtbar darübergelegt,
    damit Suche und Markieren funktionieren.
    """
    changed = 0
    for page in doc:
        if not page_needs_ocr(page):
            continue
        try:
            tp = ocr_textpage(page)
        except OcrUnavailable:
            raise
        except Exception:
            log.exception("Texterkennung für Textebene fehlgeschlagen")
            continue
        words = page.get_text("words", textpage=tp)
        if not words:
            continue
        for x0, y0, x1, y1, word, *_ in words:
            height = max(y1 - y0, 1.0)
            fontsize = max(height * 0.85, 1.0)
            width = pymupdf.get_text_length(word, fontname="helv", fontsize=fontsize) or 1.0
            # Breite an das erkannte Wort anpassen, damit das Markieren passt.
            stretch = (x1 - x0) / width
            matrix = pymupdf.Matrix(stretch, 1.0) if 0.2 < stretch < 5 else pymupdf.Matrix(1, 1)
            origin = pymupdf.Point(x0, y1 - height * 0.18)
            try:
                page.insert_text(origin, word, fontsize=fontsize, fontname="helv",
                                 render_mode=3, morph=(origin, matrix))
            except Exception:
                continue
        changed += 1
    return changed


def image_to_pdf(image_path: Path) -> "pymupdf.Document":
    """Wandelt ein Bild (JPG, PNG, TIFF …) in ein PDF um, eine Seite je Bild/Frame."""
    src = pymupdf.open(str(image_path))
    pdf_bytes = src.convert_to_pdf()
    src.close()
    return pymupdf.open("pdf", pdf_bytes)


def make_searchable_pdf(src: Path, dst: Path) -> bool:
    """Schreibt eine durchsuchbare PDF-Fassung von src nach dst.

    Gibt True zurück, wenn eine neue Datei geschrieben wurde. Bei normalen (digitalen) PDFs
    ohne Scan-Seiten wird nichts geschrieben.
    """
    suffix = src.suffix.lower()
    if suffix == ".pdf":
        doc = pymupdf.open(str(src))
        if not any(page_needs_ocr(p) for p in doc):
            doc.close()
            return False
    else:
        doc = image_to_pdf(src)
    add_text_layer(doc)
    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst), garbage=3, deflate=True)
    doc.close()
    return True
