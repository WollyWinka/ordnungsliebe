"""Scans aufbereiten: leere Seiten entfernen, schiefe Seiten gerade richten, Dateigröße verkleinern.

Wird nur auf die umgewandelte Kopie angewendet; das Original bleibt 30 Tage aufbewahrt.
Nur reine Scan-Seiten werden angefasst, digitale Seiten werden unverändert übernommen.
"""

from __future__ import annotations

import io
import logging

import pymupdf
from PIL import Image

log = logging.getLogger(__name__)

MAX_DPI = 300
MIN_DPI = 150
BLANK_INK = 0.004          # Anteil dunkler Pixel, unter dem eine Seite als leer gilt (mit leerem Text)
BLANK_INK_NO_TEXT = 0.0015  # strenger, wenn kein erkannter Text vorliegt
DESKEW_MAX = 5.0
DESKEW_MIN = 0.3
JPEG_QUALITY = 72


def _is_scan_page(page: pymupdf.Page) -> bool:
    return len(page.get_text().strip()) < 25 and bool(page.get_images())


def _page_dpi(page: pymupdf.Page) -> int:
    best = 0
    for info in page.get_image_info():
        w = info.get("width", 0)
        bbox = pymupdf.Rect(info.get("bbox", (0, 0, 0, 0)))
        if bbox.width > page.rect.width * 0.5 and w:
            best = max(best, int(w / (bbox.width / 72)))
    return max(MIN_DPI, min(best or 200, MAX_DPI))


def _render(page: pymupdf.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _ink(gray_small: Image.Image) -> float:
    w, h = gray_small.size
    mx, my = int(w * 0.05), int(h * 0.05)
    inner = gray_small.crop((mx, my, w - mx, h - my))
    hist = inner.histogram()
    dark = sum(hist[:150])
    return dark / max(1, inner.size[0] * inner.size[1])


def _is_color(img: Image.Image) -> bool:
    small = img.resize((120, max(1, int(120 * img.height / img.width))))
    sat = small.convert("HSV").split()[1]
    colorful = sum(sat.histogram()[70:])
    return colorful / max(1, small.size[0] * small.size[1]) > 0.02


def _score(binary: Image.Image) -> float:
    """Wie „streifig“ sind die Zeilen? Gerade Textzeilen ergeben große Unterschiede."""
    rows = list(binary.resize((1, binary.height), Image.BOX).tobytes())
    mean = sum(rows) / len(rows)
    return sum((r - mean) ** 2 for r in rows) / len(rows)


def skew_angle(gray: Image.Image) -> float:
    """Schätzt die Schräglage (Grad, gegen den Uhrzeigersinn zu drehen)."""
    small = gray.resize((600, max(1, int(600 * gray.height / gray.width))))
    inv = small.point(lambda v: 255 if v < 150 else 0)  # Text hell, Hintergrund dunkel
    base = _score(inv)
    best, best_score = 0.0, base
    for step in (0.5, 0.1):
        center = best
        span = DESKEW_MAX if step == 0.5 else 0.5
        a = center - span
        while a <= center + span + 1e-9:
            s = _score(inv.rotate(a, resample=Image.BILINEAR, fillcolor=0))
            if s > best_score:
                best, best_score = round(a, 2), s
            a += step
    if base <= 0 or best_score < base * 1.05:
        return 0.0
    return best


def enhance(doc: pymupdf.Document, page_texts: list[str] | None = None, *, remove_blank: bool = True,
            deskew: bool = True, compress: bool = True) -> tuple[pymupdf.Document, dict]:
    """Gibt ein neues Dokument und eine Übersicht zurück: {"removed": [...], "deskewed": n, "compressed": n}."""
    report = {"removed": [], "deskewed": 0, "compressed": 0}
    plan = []  # (index, None | jpeg_bytes, rect)
    for i, page in enumerate(doc):
        if not _is_scan_page(page):
            plan.append((i, None, page.rect))
            continue
        try:
            dpi = _page_dpi(page)
            img = _render(page, dpi)
            gray = img.convert("L")
            small = gray.resize((300, max(1, int(300 * gray.height / gray.width))))
            ink = _ink(small)
            text = (page_texts[i] if page_texts and i < len(page_texts) else "") or ""
            limit = BLANK_INK if page_texts else BLANK_INK_NO_TEXT
            if remove_blank and ink < limit and len(text.strip()) < 3:
                report["removed"].append(i + 1)
                continue
            out_img = img if _is_color(img) else gray
            changed = False
            if deskew and ink > 0.01:
                angle = skew_angle(gray)
                if abs(angle) >= DESKEW_MIN:
                    fill = (255, 255, 255) if out_img.mode == "RGB" else 255
                    out_img = out_img.rotate(angle, resample=Image.BICUBIC, fillcolor=fill)
                    report["deskewed"] += 1
                    changed = True
            if not (compress or changed):
                plan.append((i, None, page.rect))
                continue
            buf = io.BytesIO()
            out_img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
            data = buf.getvalue()
            old = sum(len(doc.xref_stream_raw(x[0]) or b"") for x in page.get_images())
            if not changed and old and len(data) >= old * 0.9:
                plan.append((i, None, page.rect))  # lohnt sich nicht – Seite bleibt, wie sie ist
                continue
            if not changed:
                report["compressed"] += 1
            plan.append((i, data, page.rect))
        except Exception:
            log.exception("Seite %s konnte nicht aufbereitet werden", i + 1)
            plan.append((i, None, page.rect))

    if not plan:  # alles leer? Dann lieber nichts entfernen
        report["removed"] = []
        return doc, report
    out = pymupdf.open()
    for i, data, rect in plan:
        if data is None:
            out.insert_pdf(doc, from_page=i, to_page=i)
        else:
            page = out.new_page(width=rect.width, height=rect.height)
            page.insert_image(page.rect, stream=data)
    return out, report
