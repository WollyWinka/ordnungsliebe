"""Vorschaubilder für die Oberfläche."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import pymupdf

from . import office, reader

log = logging.getLogger(__name__)

PREVIEW_WIDTH = 900
THUMB_WIDTH = 160


def _png_data_url(pix: "pymupdf.Pixmap") -> str:
    return "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode("ascii")


def _open_for_preview(path: Path) -> "pymupdf.Document | None":
    kind = reader.file_kind(path)
    if kind == "pdf":
        return pymupdf.open(str(path))
    if kind == "image":
        return pymupdf.open(str(path))
    if kind == "office":
        pdf = office.office_to_pdf(path)
        return pymupdf.open(str(pdf)) if pdf else None
    return None


def render_page(path: Path, page_no: int = 0, width: int = PREVIEW_WIDTH) -> dict:
    """Gibt {type, data, page, page_count} zurück. E-Mails kommen als {type: 'email', view}."""
    kind = reader.file_kind(path)
    if kind == "email":
        return {"type": "email", "view": office.parse_email(path), "page": 0, "page_count": 1}
    try:
        doc = _open_for_preview(path)
    except Exception:
        log.exception("Vorschau konnte nicht geöffnet werden")
        doc = None
    if doc is None:
        text = ""
        if kind == "office":
            text = office.office_text_fallback(path)
        return {"type": "text", "text": text[:6000], "page": 0, "page_count": 1}
    try:
        count = doc.page_count
        page_no = max(0, min(page_no, count - 1))
        page = doc[page_no]
        zoom = width / max(page.rect.width, 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return {"type": "image", "data": _png_data_url(pix), "page": page_no, "page_count": count,
                "ratio": page.rect.height / max(page.rect.width, 1)}
    finally:
        doc.close()


def render_thumbs(path: Path, width: int = THUMB_WIDTH, limit: int = 40) -> list[str]:
    """Kleine Seitenbilder (für die Stapel-Trennung)."""
    try:
        doc = _open_for_preview(path)
    except Exception:
        return []
    if doc is None:
        return []
    out = []
    try:
        for i, page in enumerate(doc):
            if i >= limit:
                break
            zoom = width / max(page.rect.width, 1)
            out.append(_png_data_url(page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)))
    finally:
        doc.close()
    return out
