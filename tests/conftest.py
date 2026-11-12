"""Testumgebung: eigene Datenordner, Test-KI, Beispieldokumente."""

from __future__ import annotations

import io
import os
import sys
import time
from email.message import EmailMessage
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def scan_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Erzeugt ein „gescanntes“ PDF (nur Bilder, kein Text)."""
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype(FONT, 34)
    except OSError:
        font = ImageFont.load_default()
    doc = pymupdf.open()
    for lines in pages:
        img = Image.new("L", (1240, 1754), 255)
        d = ImageDraw.Draw(img)
        y = 150
        for line in lines:
            d.text((110, y), line, fill=0, font=font)
            y += 70
        buf = io.BytesIO()
        img.save(buf, "PNG")
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(path))
    return path


def text_pdf(path: Path, lines: list[str]) -> Path:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    doc.save(str(path))
    return path


def eml(path: Path) -> Path:
    msg = EmailMessage()
    msg["From"] = "service@stadtwerke-beispiel.de"
    msg["To"] = "erika@example.org"
    msg["Subject"] = "Ihre Stromabrechnung 2026"
    msg["Date"] = "Tue, 03 Nov 2026 10:00:00 +0100"
    msg.set_content("Sehr geehrte Frau Mustermann,\nanbei Ihre Stromabrechnung vom 03.11.2026. "
                    "Der neue Abschlag beträgt 80 Euro.\nIhre Stadtwerke")
    msg.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename="Abrechnung.pdf")
    path.write_bytes(bytes(msg))
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDNUNGSLIEBE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ORDNUNGSLIEBE_LOCAL", str(tmp_path / "local"))
    monkeypatch.setenv("ORDNUNGSLIEBE_FAKE_AI", "1")
    monkeypatch.setenv("ORDNUNGSLIEBE_FAKE_HW", "16,32")
    monkeypatch.setenv("ORDNUNGSLIEBE_NO_UPDATE", "1")
    monkeypatch.setattr("app.core.pipeline.POLL_SECONDS", 0.5)
    monkeypatch.setattr("send2trash.send2trash", lambda p: os.remove(p))
    inbox = tmp_path / "Scans"
    lib = tmp_path / "Ablage"
    inbox.mkdir()
    (lib / "Finanzen" / "Bank").mkdir(parents=True)
    (lib / "Versicherungen" / "Hausrat").mkdir(parents=True)
    (lib / "Wohnen" / "Strom & Gas").mkdir(parents=True)
    text_pdf(lib / "Finanzen" / "Bank" / "2026-09 Kontoauszug.pdf",
             ["Sparkasse Bamberg", "Kontoauszug Nr. 9 vom 30.09.2026", "Girokonto Kontostand 1.234,00 EUR"])
    return {"tmp": tmp_path, "inbox": inbox, "lib": lib}


def wait_for(cond, timeout=60.0, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False
