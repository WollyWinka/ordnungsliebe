"""Klickt die Oberfläche im Browser durch und speichert Bildschirmfotos (mit Test-KI)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from conftest import eml, scan_pdf, text_pdf  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots")
DARK = "--dark" in sys.argv
PORT = 8799


def post(name, *args):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/{name}", data=json.dumps(args).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


def main():
    base = Path("/tmp/ol-ui")
    shutil.rmtree(base, ignore_errors=True)
    home = base / "home"
    inbox = home / "Documents" / "Scans"
    lib = home / "iCloudDrive" / "Dokumente"
    inbox.mkdir(parents=True)
    (lib / "Finanzen" / "Bank").mkdir(parents=True)
    (lib / "Versicherungen" / "Hausrat").mkdir(parents=True)
    (lib / "Wohnen" / "Strom & Gas").mkdir(parents=True)
    (lib / "Alte Ablage").mkdir(parents=True)
    text_pdf(lib / "Finanzen" / "Bank" / "2026-09 Kontoauszug.pdf", ["Sparkasse", "Kontoauszug Girokonto 30.09.2026"])
    text_pdf(lib / "Alte Ablage" / "scan77.pdf", ["Stadtwerke", "Stromabrechnung vom 01.07.2026", "Abschlag Strom"])
    text_pdf(lib / "Alte Ablage" / "brief.pdf", ["Finanzamt Bamberg", "Steuerbescheid für 2025 vom 12.06.2026"])
    OUT.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, HOME=str(home), ORDNUNGSLIEBE_FAKE_AI="1", ORDNUNGSLIEBE_FAKE_HW="16,32",
               ORDNUNGSLIEBE_DATA=str(base / "data"), ORDNUNGSLIEBE_LOCAL=str(base / "local"),
               ORDNUNGSLIEBE_POLL="0.5")
    srv = subprocess.Popen([sys.executable, str(ROOT / "tests" / "devserver.py"), str(PORT)], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(2.5)
    from playwright.sync_api import sync_playwright

    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 880},
                                    color_scheme="dark" if DARK else "light")
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.goto(f"http://127.0.0.1:{PORT}/")
            page.wait_for_timeout(1200)
            shot = lambda n: page.screenshot(path=str(OUT / f"{n}.png"), full_page=True)
            shot("01-willkommen")
            page.click("text=Los geht's")
            page.wait_for_timeout(1500)
            shot("02-ki")
            page.click("#next2")
            page.wait_for_timeout(800)
            page.click("text=Ich weiß nicht, wo mein Scanner speichert")
            page.wait_for_timeout(300)
            shot("03-scanordner")
            page.click("text=Weiter")
            page.wait_for_timeout(800)
            shot("04-ablage")
            # Ablage setzen (Ordnerdialog gibt es im Browser nicht)
            page.evaluate(f"S.setup.lib = {{path: {json.dumps(str(lib))}, display: 'iCloud Drive › Dokumente'}}; loadLibInfo(); render();")
            page.wait_for_timeout(800)
            page.click("text=Weiter")
            page.wait_for_timeout(600)
            shot("05-fertig")
            page.click("text=Direkt mit neuen Scans loslegen")
            page.wait_for_timeout(800)
            shot("06-start-leer")

            # Dokumente in den Scan-Ordner legen
            scan_pdf(inbox / "Scan_0047.pdf", [["Nordstern Versicherung AG", "Ihre Hausratversicherung",
                                                 "Beitragsrechnung 2027 vom 03.11.2026", "Hausrat Beitrag 2027"]])
            text_pdf(inbox / "auszug.pdf", ["Sparkasse Bamberg", "Kontoauszug Nr. 11 vom 03.11.2026",
                                            "Girokonto Kontostand", "Kontoauszug"])
            text_pdf(inbox / "unklar.pdf", ["Sehr geehrte Damen und Herren", "anbei die Unterlagen vom 05.10.2026"])
            eml(inbox / "Strom.eml")
            scan_pdf(inbox / "Stapel.pdf", [["Praxis Dr. Muster GmbH", "Arztrechnung vom 01.10.2026"],
                                            ["Seite 2", "Summe 80,00 EUR"],
                                            ["Sparkasse Bamberg AG", "Kontoauszug vom 31.10.2026"]])
            shutil.copy(lib / "Finanzen" / "Bank" / "2026-09 Kontoauszug.pdf", inbox / "nochmal.pdf")
            post("app_state")
            # Bestand für Doppelte indizieren
            for _ in range(80):
                st = post("overview", "inbox")["data"]
                if st["total"] >= 6 and st["working"] == 0:
                    break
                time.sleep(0.5)
            page.wait_for_timeout(1500)
            shot("07-start-mit-dokumenten")
            page.click(".hero")
            page.wait_for_timeout(1200)
            shot("08-sammelliste")
            page.click("button:has-text('einsortieren')")
            page.wait_for_timeout(2000)
            shot("09-einzelpruefung")
            for i in range(8):
                stage = page.evaluate("S.cur && S.cur.item ? S.cur.item.stage + '|' + S.cur.item.kind : 'none'")
                shot(f"10-einzeln-{i}-{stage.replace('|', '-')}")
                if stage == "none":
                    break
                if stage.startswith("stack"):
                    page.click("text=So trennen")
                elif stage.startswith("duplicate"):
                    page.click("text=Zur Seite legen")
                else:
                    if i == 1:
                        page.click("text=Passt nicht – neuer Vorschlag")
                        page.wait_for_timeout(2000)
                        shot(f"10-einzeln-{i}-nach-ablehnen")
                    page.click("text=Passt so – einsortieren")
                page.wait_for_timeout(2500)
            page.evaluate("go('history')")
            page.wait_for_timeout(1000)
            shot("11-verlauf")
            page.evaluate("go('settings')")
            page.wait_for_timeout(800)
            shot("12-einstellungen")
            page.click("text=Sehr groß")
            page.wait_for_timeout(600)
            shot("13-einstellungen-sehr-gross")
            page.click("text=Groß")
            page.wait_for_timeout(400)
            # Neuordnung
            page.evaluate("go('reorg')")
            page.wait_for_timeout(1200)
            shot("14-neuordnung-start")
            page.click("text=Neuordnung starten")
            page.wait_for_timeout(600)
            shot("15-neuordnung-lesen")
            for _ in range(60):
                if page.evaluate("S.state.reorg.phase") == "structure_review":
                    break
                page.wait_for_timeout(500)
            page.wait_for_timeout(1200)
            shot("16-struktur")
            page.click("text=Struktur übernehmen")
            page.wait_for_timeout(4000)
            shot("17-neuordnung-hub")
            browser.close()
    finally:
        srv.terminate()
        log = srv.stdout.read().decode(errors="replace") if srv.stdout else ""
    print("JS-Fehler:", errors or "keine")
    if "Traceback" in log:
        print(log[-3000:])


if __name__ == "__main__":
    main()
