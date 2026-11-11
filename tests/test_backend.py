"""Ende-zu-Ende-Tests des Programmkerns mit der Test-KI (ohne Fenster)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf

from conftest import eml, scan_pdf, text_pdf, wait_for


def make_api(env):
    from app.api import Api
    api = Api()
    r = api.finish_setup(str(env["inbox"]), str(env["lib"]), "direct")
    assert r["ok"], r
    api.start_background()
    return api


def test_inbox_flow_scan_is_ocred_classified_and_made_searchable(env):
    api = make_api(env)
    scan_pdf(env["inbox"] / "Scan_0047.pdf", [[
        "Nordstern Versicherung AG", "Ihre Hausratversicherung HR-4471",
        "Beitragsrechnung 2027 vom 03.11.2026", "Der Beitrag für Ihre Hausrat-Police"]])
    assert wait_for(lambda: api.pipeline.overview()["working"] == 0 and api.pipeline.overview()["total"] == 1)
    batch = api.batch("inbox")["data"]
    single = api.next_single("inbox")["data"]
    item = (batch[0] if batch else single)
    s = item["suggestion"]
    assert s["folder"] == "Versicherungen/Hausrat"
    assert s["filename"].startswith("2026-11") and s["filename"].endswith(".pdf")

    res = api.confirm(item["id"])["data"]
    dst = Path(res["dst"])
    assert dst.exists() and dst.parent == env["lib"] / "Versicherungen" / "Hausrat"
    assert not (env["inbox"] / "Scan_0047.pdf").exists()
    # durchsuchbar: Text ist jetzt direkt im PDF
    assert "Nordstern" in pymupdf.open(str(dst))[0].get_text()

    hist = api.history_view()["data"]
    entry = hist["days"][0]["entries"][0]
    assert entry["undoable"]
    assert api.memory.count() == 1

    # Rückgängig: Original kommt zurück in den Scan-Ordner
    r = api.undo(entry["id"])
    assert r["ok"], r
    assert (env["inbox"] / "Scan_0047.pdf").exists()
    assert not dst.exists()
    assert api.memory.count() == 0
    api.shutdown()


def test_reject_excludes_folder_and_manual_override(env):
    api = make_api(env)
    text_pdf(env["inbox"] / "brief.pdf", ["Stadtwerke Bamberg", "Ihre Stromabrechnung vom 02.10.2026",
                                          "Abschlag Strom und Gas"])
    assert wait_for(lambda: api.pipeline.overview()["total"] == 1 and api.pipeline.overview()["working"] == 0)
    items = api.batch("inbox")["data"] or [api.next_single("inbox")["data"]]
    item = items[0]
    first = item["suggestion"]["folder"]
    api.reject(item["id"])
    assert wait_for(lambda: api.pipeline.overview()["working"] == 0)
    again = api.next_single("inbox")["data"]
    assert again["id"] == item["id"]
    assert again["suggestion"]["folder"] != first
    assert first in again["excluded"]
    # manuell überschreiben
    res = api.confirm(again["id"], "Wohnen/Strom & Gas", "2026-10 Stromabrechnung")["data"]
    assert Path(res["dst"]) == env["lib"] / "Wohnen" / "Strom & Gas" / "2026-10 Stromabrechnung.pdf"
    api.shutdown()


def test_duplicate_detected_and_trashed(env):
    api = make_api(env)
    src = env["lib"] / "Finanzen" / "Bank" / "2026-09 Kontoauszug.pdf"
    # Bestand indizieren wie bei der Neuordnung
    from app.docs import reader
    from app.store import textsim
    api.dup.add_file(src, reader.file_hash(src), textsim.fingerprint(reader.read_document(src).text))
    shutil.copy(src, env["inbox"] / "nochmal.pdf")
    assert wait_for(lambda: api.pipeline.overview()["total"] == 1 and api.pipeline.overview()["working"] == 0)
    item = api.next_single("inbox")["data"]
    assert item["stage"] == "duplicate"
    assert item["dup"]["folder"] == "Finanzen/Bank"
    assert api.dup_trash(item["id"])["ok"]
    assert not (env["inbox"] / "nochmal.pdf").exists()
    api.shutdown()


def test_stack_split(env):
    api = make_api(env)
    scan_pdf(env["inbox"] / "Stapel.pdf", [
        ["Praxis Dr. Muster GmbH", "Arztrechnung vom 01.10.2026", "Behandlung"],
        ["Seite 2 der Arztrechnung", "Summe 80,00 EUR"],
        ["Sparkasse Bamberg AG", "Kontoauszug Nr. 10 vom 31.10.2026", "Girokonto"],
    ])
    assert wait_for(lambda: api.pipeline.overview()["total"] >= 1 and api.pipeline.overview()["working"] == 0)
    item = api.next_single("inbox")["data"]
    assert item["stage"] == "stack", item
    assert item["starts"] == [1, 3]
    assert len(api.thumbs(item["id"])["data"]) == 3
    n = api.split(item["id"], [1, 3])["data"]
    assert n == 2
    assert wait_for(lambda: api.pipeline.overview()["total"] == 2 and api.pipeline.overview()["working"] == 0)
    stages = {i["stage"] for i in api.pipeline.items.values()}
    assert stages == {"doc"}
    api.shutdown()


def test_email_and_office(env):
    api = make_api(env)
    eml(env["inbox"] / "Rechnung.eml")
    import docx
    d = docx.Document()
    d.add_paragraph("Mietvertrag für die Wohnung Musterstraße 1, Vermieter Herr Beispiel, Miete 800 Euro")
    d.save(str(env["inbox"] / "Mietvertrag.docx"))
    assert wait_for(lambda: api.pipeline.overview()["total"] == 2 and api.pipeline.overview()["working"] == 0,
                    timeout=180)
    items = list(api.pipeline.items.values())
    by_kind = {i["kind"]: i for i in items}
    assert by_kind["email"]["suggestion"]["filename"].endswith(".eml")
    assert by_kind["office"]["suggestion"]["filename"].endswith(".docx")
    prev = api.preview(by_kind["email"]["id"])["data"]
    assert prev["type"] == "email" and prev["view"]["subject"] == "Ihre Stromabrechnung 2026"
    assert prev["view"]["attachments"] == ["Abrechnung.pdf"]
    api.shutdown()


def test_reorg_full_cycle_and_undo(env):
    api = make_api(env)
    lib = env["lib"]
    old = lib / "Altes Zeug"
    old.mkdir()
    text_pdf(old / "scan1.pdf", ["Sparkasse", "Kontoauszug Girokonto vom 31.08.2026", "Kontostand"])
    text_pdf(old / "brief.pdf", ["Stadtwerke", "Stromabrechnung vom 01.07.2026", "Abschlag Strom"])
    before = sorted(str(p.relative_to(lib)) for p in lib.rglob("*.pdf"))

    assert api.reorg_start("neu")["ok"]
    assert wait_for(lambda: api.reorganizer.state.get("phase") in ("structure_review", "error"), timeout=120)
    assert api.reorganizer.state["phase"] == "structure_review", api.reorganizer.state
    struct = api.reorg_structure()["data"]
    assert struct["backup"] and Path(struct["backup"]["path"]).exists()
    folders = struct["folders"]
    assert any(f["path"] == "Finanzen/Bank" for f in folders)

    assert api.reorg_apply(folders)["ok"]
    assert wait_for(lambda: api.pipeline.overview("reorg")["working"] == 0, timeout=120)
    for it in api.batch("reorg")["data"]:
        api.confirm(it["id"])
    while True:
        it = api.next_single("reorg")["data"]
        if not it:
            break
        api.confirm(it["id"])
    fin = api.reorg_finish()["data"]
    assert fin["phase"] == "done"
    assert not old.exists()  # leerer Ordner aufgeräumt
    assert (lib / "Finanzen" / "Bank").exists()

    groups = api.history_view()["data"]["reorgs"]
    assert groups and groups[0]["count"] >= 2
    res = api.undo_reorg(groups[0]["id"])["data"]
    assert res["failed"] == 0
    after = sorted(str(p.relative_to(lib)) for p in lib.rglob("*.pdf"))
    assert after == before
    api.shutdown()


def test_setup_helpers(env):
    from app.api import Api
    api = Api()
    hw = api.hardware()["data"]
    assert hw["recommended"] == "gruendlich" and hw["gpu"]
    info = api.inbox_info(str(env["inbox"]))["data"]
    assert info["ok"] and info["count"] == 0
    li = api.library_info(str(env["lib"]))["data"]
    assert li["count"] == 1
    assert api.app_state()["ok"]


def test_concurrent_moves_never_overwrite(tmp_path):
    import threading
    from app.core import library
    target = tmp_path / "ziel" / "gleich.pdf"
    srcs = []
    for i in range(20):
        p = tmp_path / f"q{i}.pdf"
        p.write_bytes(f"inhalt {i}".encode())
        srcs.append(p)
    threads = [threading.Thread(target=library.move_file, args=(p, target)) for p in srcs]
    [t.start() for t in threads]
    [t.join() for t in threads]
    files = list((tmp_path / "ziel").iterdir())
    assert len(files) == 20
    assert sorted(f.read_bytes() for f in files) == sorted(f"inhalt {i}".encode() for i in range(20))


def test_undo_refuses_when_file_was_replaced(env):
    api = make_api(env)
    text_pdf(env["inbox"] / "a.pdf", ["Sparkasse", "Kontoauszug Girokonto vom 01.11.2026", "Kontoauszug"])
    assert wait_for(lambda: api.pipeline.overview()["total"] == 1 and api.pipeline.overview()["working"] == 0)
    item = (api.batch("inbox")["data"] or [api.next_single("inbox")["data"]])[0]
    dst = Path(api.confirm(item["id"])["data"]["dst"])
    entry = api.history_view()["data"]["days"][0]["entries"][0]
    dst.write_bytes(b"ganz anderes Dokument")  # Nutzer hat die Datei ersetzt
    r = api.undo(entry["id"])
    assert not r["ok"] and "verändert" in r["error"]
    assert dst.read_bytes() == b"ganz anderes Dokument"
    api.shutdown()


def test_nested_folders_rejected(env):
    from app.api import Api
    api = Api()
    r = api.finish_setup(str(env["lib"] / "Scans"), str(env["lib"]), "direct")
    assert not r["ok"] and "getrennte" in r["error"]


def test_duplicate_goes_to_own_trash_and_can_be_restored(env):
    api = make_api(env)
    src = env["lib"] / "Finanzen" / "Bank" / "2026-09 Kontoauszug.pdf"
    assert wait_for(lambda: api.dup.known_sha(src) is not None, timeout=20)
    shutil.copy(src, env["inbox"] / "doppelt.pdf")
    assert wait_for(lambda: api.pipeline.overview()["total"] == 1 and api.pipeline.overview()["working"] == 0)
    item = api.next_single("inbox")["data"]
    assert item["stage"] == "duplicate"
    assert api.dup_trash(item["id"])["ok"]
    assert not (env["inbox"] / "doppelt.pdf").exists()
    entry = api.history_view()["data"]["days"][0]["entries"][0]
    assert entry["undoable"]
    api.pipeline.stop()  # Poller anhalten, damit die Datei nicht sofort neu erkannt wird
    assert api.undo(entry["id"])["ok"]
    assert (env["inbox"] / "doppelt.pdf").exists()


def test_image_keeps_real_extension_if_conversion_fails(env, monkeypatch):
    api = make_api(env)
    from PIL import Image
    Image.new("RGB", (400, 300), "white").save(env["inbox"] / "foto.jpg")
    assert wait_for(lambda: api.pipeline.overview()["total"] == 1 and api.pipeline.overview()["working"] == 0)
    item = (api.batch("inbox")["data"] or [api.next_single("inbox")["data"]])[0]
    monkeypatch.setattr("app.docs.ocr.make_searchable_pdf", lambda s, d: (_ for _ in ()).throw(RuntimeError("x")))
    dst = Path(api.confirm(item["id"])["data"]["dst"])
    assert dst.suffix == ".jpg"
    assert dst.read_bytes()[:2] == b"\xff\xd8"
    api.shutdown()


def test_double_confirm_is_rejected(env):
    api = make_api(env)
    text_pdf(env["inbox"] / "b.pdf", ["Sparkasse", "Kontoauszug Girokonto vom 02.11.2026", "Kontoauszug"])
    assert wait_for(lambda: api.pipeline.overview()["total"] == 1 and api.pipeline.overview()["working"] == 0)
    item = (api.batch("inbox")["data"] or [api.next_single("inbox")["data"]])[0]
    assert api.confirm(item["id"])["ok"]
    assert not api.confirm(item["id"])["ok"]
    assert len(list((env["lib"] / "Finanzen" / "Bank").glob("*.pdf"))) == 2
    api.shutdown()
