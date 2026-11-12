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
BLANK_INK = 0.0003         # Anteil „Tinte“ (bei ~100 dpi, relativ zum Papier), unter dem eine Seite leer ist
INK_DELTA = 40             # so viel dunkler als das Papier gilt als Tinte (auch Bleistift, Unterschrift)
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


def _ink(gray: Image.Image) -> float:
    """Anteil der Pixel, die deutlich dunkler sind als das Papier (Rand bleibt außen vor)."""
    w, h = gray.size
    mx, my = int(w * 0.04), int(h * 0.04)
    inner = gray.crop((mx, my, w - mx, h - my))
    hist = inner.histogram()
    total = max(1, inner.size[0] * inner.size[1])
    # Papierfarbe = häufigster heller Wert
    paper = max(range(100, 256), key=lambda v: hist[v])
    dark = sum(hist[: max(0, paper - INK_DELTA)])
    return dark / total


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


def _rotate_keep_all(img: Image.Image, angle: float) -> Image.Image:
    """Dreht, ohne Ecken abzuschneiden: gedrehtes Bild wird verkleinert auf die alte Seitengröße gesetzt."""
    fill = (255, 255, 255) if img.mode == "RGB" else 255
    rot = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=fill)
    w, h = img.size
    scale = min(w / rot.width, h / rot.height)
    rot = rot.resize((max(1, int(rot.width * scale)), max(1, int(rot.height * scale))), Image.LANCZOS)
    canvas = Image.new(img.mode, (w, h), fill)
    canvas.paste(rot, ((w - rot.width) // 2, (h - rot.height) // 2))
    return canvas


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
    if base <= 0 or best_score < base * 1.15:  # nur bei deutlichem Ergebnis drehen
        return 0.0
    return best


def enhance(doc: pymupdf.Document, page_texts: list[str] | None = None, *, remove_blank: bool = True,
            deskew: bool = True, compress: bool = True) -> tuple[pymupdf.Document, dict]:
    """Gibt ein neues Dokument und eine Übersicht zurück: {"removed": [...], "deskewed": n, "compressed": n}."""
    report = {"removed": [], "deskewed": 0, "compressed": 0}
    # Leere Seiten nur entfernen, wenn die Texterkennung sicher funktioniert hat (andere Seiten haben Text)
    ocr_ok = bool(page_texts) and len(page_texts) == doc.page_count and \
        any(len((t or "").strip()) >= 20 for t in page_texts)
    plan = []  # (index, None | jpeg_bytes, rect)
    for i, page in enumerate(doc):
        if not _is_scan_page(page):
            plan.append((i, None, page.rect))
            continue
        try:
            dpi = _page_dpi(page)
            img = _render(page, dpi)
            gray = img.convert("L")
            w100 = max(1, int(page.rect.width / 72 * 100))  # etwa 100 dpi
            ink = _ink(gray.resize((w100, max(1, int(w100 * gray.height / gray.width))), Image.BOX))
            text = (page_texts[i] if page_texts and i < len(page_texts) else "") or ""
            if remove_blank and ocr_ok and ink < BLANK_INK and len(text.strip()) < 3:
                report["removed"].append(i + 1)
                continue
            out_img = img if _is_color(img) else gray
            changed = False
            if deskew and ink > 0.01:
                angle = skew_angle(gray)
                if abs(angle) >= DESKEW_MIN:
                    out_img = _rotate_keep_all(out_img, angle)
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
