"""Weitergeleitete Mails: Abholen aus dem Postfach und Auswerten (Anhang / ganze Mail / fragen)."""

import imaplib
import re
from email.message import EmailMessage
from pathlib import Path

import pymupdf
import pytest

from app.api import Api
from conftest import wait_for


def _pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def forwarded_invoice(note="Steuer bitte") -> bytes:
    m = EmailMessage()
    m["From"] = "Erika Muster <erika@example.org>"
    m["To"] = "ablage@gmx.de"
    m["Subject"] = "WG: Ihre Rechnung 4711"
    m["Date"] = "Fri, 13 Nov 2026 08:00:00 +0100"
    m["Message-ID"] = "<rechnung-4711@example.org>"
    m.set_content(f"{note}\n\nVon meinem iPhone gesendet\n\nAnfang der weitergeleiteten Nachricht:\n\n"
                  "Von: Stadtwerke Bamberg <rechnung@stadtwerke.example>\nDatum: 2. November 2026 um 10:15:00 MEZ\n"
                  "An: erika@example.org\nBetreff: Ihre Rechnung 4711\n\n"
                  "Sehr geehrte Frau Muster,\nanbei erhalten Sie Ihre Stromabrechnung.\nIhre Stadtwerke\n")
    m.add_attachment(_pdf("Stadtwerke Bamberg Stromabrechnung 4711 Abschlag 80 Euro"), maintype="application",
                     subtype="pdf", filename="Rechnung_4711.pdf")
    m.add_attachment(b"\x89PNG" + b"0" * 800, maintype="image", subtype="png", filename="logo.png")
    return bytes(m)


def booking_mail() -> bytes:
    m = EmailMessage()
    m["From"] = "erika@example.org"
    m["Subject"] = "Fwd: Buchungsbestätigung Hotel Krone"
    m["Date"] = "Fri, 13 Nov 2026 08:00:00 +0100"
    m["Message-ID"] = "<buchung@example.org>"
    m.set_content("---------- Forwarded message ---------\nFrom: Hotel Krone <info@krone.example>\n"
                  "Date: Mon, 9 Nov 2026\nSubject: Buchungsbestätigung Hotel Krone\n\n"
                  "Vielen Dank für Ihre Buchung. Anreise 20.12.2026, Abreise 22.12.2026, Doppelzimmer, 240 Euro.")
    return bytes(m)


def long_mail_with_attachment() -> bytes:
    m = EmailMessage()
    m["From"] = "erika@example.org"
    m["Subject"] = "Vertragsänderung"
    m["Message-ID"] = "<vertrag@example.org>"
    m.set_content("Hallo, hier die besprochenen Punkte: " + "Wir vereinbaren folgende Änderungen am Vertrag. " * 25)
    m.add_attachment(_pdf("Vertrag Nachtrag"), maintype="application", subtype="pdf", filename="Nachtrag.pdf")
    return bytes(m)


def _api(env):
    api = Api()
    api.finish_setup(str(env["inbox"]), str(env["lib"]), "direct")
    api.start_background()
    return api


def _settled(api, n):
    return wait_for(lambda: api.pipeline.overview()["total"] >= n and api.pipeline.overview()["working"] == 0)


def test_forwarded_invoice_keeps_only_attachment_with_note_as_hint(env):
    api = _api(env)
    (env["inbox"] / "rechnung.eml").write_bytes(forwarded_invoice())
    assert _settled(api, 1)
    items = list(api.pipeline.items.values())
    assert len(items) == 1
    it = items[0]
    assert it["name"] == "Rechnung_4711.pdf" and it["hint"] == "Steuer bitte"
    assert it["mail_from"] == "Ihre Rechnung 4711"
    assert sorted(p.name for p in env["inbox"].iterdir()) == ["Rechnung_4711.pdf"]  # Mail ist im Papierkorb
    entry = api.history_view()["data"]["days"][0]["entries"][0]
    assert entry["action"] == "mail" and "Anhang" in entry["where"] and entry["undoable"]
    # Rückgängig: Mail kommt zurück und wird diesmal gefragt
    r = api.undo(entry["id"])["data"]
    assert r["left"] == 0
    assert _settled(api, 1)
    items = list(api.pipeline.items.values())
    assert len(items) == 1 and items[0]["stage"] == "mail" and items[0]["src"].endswith("rechnung.eml")
    api.shutdown()


def test_booking_without_attachment_becomes_pdf(env):
    api = _api(env)
    (env["inbox"] / "buchung.eml").write_bytes(booking_mail())
    assert _settled(api, 1)
    it = next(iter(api.pipeline.items.values()))
    assert it["name"].endswith(".pdf") and "Buchungsbestätigung" in it["name"] and it["name"].startswith("2026-11-09")
    text = pymupdf.open(it["src"])[0].get_text()
    assert "Hotel Krone" in text and "Anreise 20.12.2026" in text
    api.shutdown()


def test_unclear_mail_is_asked_and_both_can_be_chosen(env):
    api = _api(env)
    (env["inbox"] / "vertrag.eml").write_bytes(long_mail_with_attachment())
    assert _settled(api, 1)
    it = api.next_single("inbox")["data"]
    assert it["stage"] == "mail" and it["mail"]["docs"] == ["Nachtrag.pdf"] and it["mail"]["mode"] == "ask"
    assert api.batch("inbox")["data"] == []
    assert api.mail_choice(it["id"], "both")["data"] == 2
    assert _settled(api, 2)
    names = sorted(i["name"] for i in api.pipeline.items.values())
    assert names[0] == "Nachtrag.pdf" and names[1].endswith("Vertragsänderung.pdf")
    api.shutdown()


# --- Abholen aus dem Postfach ---------------------------------------------------------------

class FakeIMAP:
    """Sehr einfacher IMAP-Server im Speicher."""
    boxes: dict = {}
    password = "geheim"

    def __init__(self, host, port=993, ssl_context=None, timeout=None):
        self.host = host
        self.sel = None

    def login(self, user, password):
        if password != self.password:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b"ok"]

    def select(self, box, readonly=False):
        self.sel = box
        self.boxes.setdefault(box, {})
        return "OK", [str(len(self.boxes[box])).encode()]

    def create(self, box):
        if box.strip('"') in self.boxes:
            return "NO", [b"exists"]
        self.boxes[box.strip('"')] = {}
        return "OK", [b""]

    def capability(self):
        return "OK", [b"IMAP4rev1 MOVE UIDPLUS"]

    def uid(self, cmd, *args):
        box = self.boxes[self.sel]
        if cmd == "SEARCH":
            return "OK", [b" ".join(str(u).encode() for u in sorted(box))]
        uid = int(args[0])
        if cmd == "FETCH":
            raw = box.get(uid)
            if raw is None:
                return "OK", [None]
            if "HEADER.FIELDS" in args[1]:
                head = raw.split(b"\n\n", 1)[0] + b"\n\n"
                return "OK", [(f"1 (UID {uid} RFC822.SIZE {len(raw)} BODY[HEADER] {{{len(head)}}}".encode(), head), b")"]
            return "OK", [(f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        if cmd == "MOVE":
            self.boxes[args[1].strip('"')][uid] = box.pop(uid)
            return "OK", [b""]
        raise AssertionError(cmd)

    def expunge(self):
        return "OK", [b""]

    def logout(self):
        return "BYE", [b""]


@pytest.fixture()
def imap(monkeypatch):
    FakeIMAP.boxes = {"INBOX": {}}
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    return FakeIMAP


def test_fetch_only_allowed_senders_and_move_to_done(env, imap):
    imap.boxes["INBOX"] = {1: forwarded_invoice().replace(b"\r\n", b"\n"),
                           2: re.sub(rb"From: [^\n]+", b"From: spam@werbung.example",
                                     booking_mail().replace(b"\r\n", b"\n"), count=1)}
    api = _api(env)
    assert api.mail_provider("ablage@gmx.de")["data"]["host"] == "imap.gmx.net"
    assert not api.mail_provider("x@hotmail.com")["data"]["supported"]
    bad = api.mail_save("ablage@gmx.de", "falsch", ["erika@example.org"])
    assert not bad["ok"] and "abgelehnt" in bad["error"]
    assert not api.mail_save("ablage@gmx.de", "geheim", [])["ok"]  # ohne Absender nicht
    st = api.mail_save("ablage@gmx.de", "geheim", ["Erika <ERIKA@example.org>"])["data"]
    assert st["senders"] == ["erika@example.org"] and st["has_password"]
    r = api.mail_fetch_now()["data"]
    assert r["new"] == 1 and r["error"] == ""
    assert [u["address"] for u in r["unknown"]] == ["spam@werbung.example"]
    assert list(imap.boxes["Abgelegt"]) == [1] and list(imap.boxes["INBOX"]) == [2]
    assert _settled(api, 1)
    assert next(iter(api.pipeline.items.values()))["name"] == "Rechnung_4711.pdf"
    # Nochmal abholen: nichts doppelt
    assert api.mail_fetch_now()["data"]["new"] == 0
    # Absender freigeben → wird beim nächsten Mal geholt
    api.mail_allow_sender("spam@werbung.example")
    assert api.mail_fetch_now()["data"]["new"] == 1 and imap.boxes["INBOX"] == {}
    # Passwort steht nicht im Klartext in den Einstellungen
    assert "geheim" not in (Path(env["tmp"]) / "data" / "einstellungen.json").read_text(encoding="utf-8")
    api.shutdown()
