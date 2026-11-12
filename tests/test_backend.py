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


def test_reorg_skips_photos_and_unbackupable_files(env, monkeypatch):
    from PIL import Image
    api = make_api(env)
    lib = env["lib"]
    # Kamerafoto (mit Brennweite im EXIF) – darf nicht angefasst werden
    photo = lib / "Urlaub.jpg"
    img = Image.new("RGB", (1200, 900), "skyblue")
    exif = Image.Exif()
    exif.get_ifd(0x8769)[37386] = 50.0
    img.save(photo, exif=exif.tobytes())
    # Datei, die sich nicht sichern lässt (wie eine iCloud-Datei, die gerade nicht lädt)
    stuck = lib / "Wohnen" / "Strom & Gas" / "haengt.pdf"
    text_pdf(stuck, ["Stadtwerke", "Stromabrechnung vom 01.05.2026"])
    import shutil as _sh
    real_copy = _sh.copy2

    def flaky(src, dst, *a, **k):
        if str(src).endswith("haengt.pdf"):
            raise OSError(5, "Zugriff verweigert")
        return real_copy(src, dst, *a, **k)
    monkeypatch.setattr("app.core.reorg.shutil.copy2", flaky)
    monkeypatch.setattr("app.core.reorg.time.sleep", lambda s: None)

    assert api.library_info(str(lib))["data"]["count"] == 2  # Foto zählt nicht
    assert api.reorg_start("neu")["ok"]
    assert wait_for(lambda: api.reorganizer.state.get("phase") in ("structure_review", "error"), timeout=120)
    assert api.reorganizer.state["phase"] == "structure_review", api.reorganizer.state
    st = api.reorg_structure()["data"]
    assert st["skipped_count"] == 1 and st["skipped"][0]["rel"].endswith("haengt.pdf")
    docs = [d["path"] for d in api.reorganizer.state["docs"]]
    assert str(photo) not in docs and str(stuck) not in docs
    api.reorg_apply(st["folders"])
    assert wait_for(lambda: api.pipeline.overview("reorg")["working"] == 0, timeout=60)
    srcs = {i["src"] for i in api.pipeline.items.values()}
    assert str(stuck) not in srcs and str(photo) not in srcs
    api.shutdown()


def test_backup_error_message_is_shown(env, monkeypatch):
    api = make_api(env)
    monkeypatch.setattr("app.core.reorg.shutil.disk_usage", lambda p: type("U", (), {"free": 1000})())
    api.reorg_start("neu")
    assert wait_for(lambda: api.reorganizer.state.get("phase") == "error", timeout=30)
    assert "frei sind nur" in api.reorganizer.state["error"]
    api.shutdown()


def test_hint_changes_suggestion_and_is_remembered(env):
    api = make_api(env)
    text_pdf(env["inbox"] / "brief.pdf", ["Sehr geehrte Damen und Herren", "anbei die Unterlagen vom 05.10.2026",
                                          "Ihr Bankberater"])
    assert wait_for(lambda: api.pipeline.overview()["total"] == 1 and api.pipeline.overview()["working"] == 0)
    item = (api.batch("inbox")["data"] or [api.next_single("inbox")["data"]])[0]
    assert api.give_hint(item["id"], "Das gehört zur Bank")["ok"]
    assert wait_for(lambda: api.pipeline.overview()["working"] == 0)
    again = api.item(item["id"])["data"]
    assert again["suggestion"]["folder"] == "Finanzen/Bank"
    assert again["hint"] == "Das gehört zur Bank"
    hv = api.hints_view()["data"]
    assert hv["hints"][0]["text"] == "Das gehört zur Bank" and hv["hints"][0]["scope"] == "aehnlich"
    # ähnliches Dokument bekommt den Hinweis automatisch mit, ein fremdes nicht
    assert "Das gehört zur Bank" in api.hints.relevant("Sehr geehrte Damen und Herren anbei die Unterlagen Bankberater")
    assert api.hints.relevant("Rezept Apotheke Ibuprofen 400") == []
    # Regel für alle Dokumente
    rule = api.hint_add_rule("Rechnungen von Amazon gehören zu Einkäufe")["data"]
    assert "Rechnungen von Amazon gehören zu Einkäufe" in api.hints.relevant("irgendwas völlig anderes")
    api.hint_update(rule["id"], "Amazon → Einkäufe", None)
    api.hint_delete(rule["id"])
    assert len(api.hints_view()["data"]["hints"]) == 1
    api.shutdown()


def test_not_a_document_is_never_proposed_again(env):
    from PIL import Image
    api = make_api(env)
    Image.new("RGB", (1200, 900), "orange").save(env["inbox"] / "katze.jpg")
    assert wait_for(lambda: api.pipeline.overview()["total"] == 1 and api.pipeline.overview()["working"] == 0)
    item = (api.batch("inbox")["data"] or [api.next_single("inbox")["data"]])[0]
    assert api.not_document(item["id"])["ok"]
    assert (env["inbox"] / "katze.jpg").exists()  # bleibt liegen
    import time as _t
    _t.sleep(2)
    assert api.pipeline.overview()["total"] == 0
    # gleiche Datei unter anderem Namen wird ebenfalls übergangen
    shutil.copy(env["inbox"] / "katze.jpg", env["inbox"] / "katze2.jpg")
    _t.sleep(4)
    assert api.pipeline.overview()["total"] == 0
    # im Verlauf zurücknehmen → wird wieder vorgeschlagen
    entry = next(e for d in api.history_view()["data"]["days"] for e in d["entries"] if e["action"] == "ignore")
    assert entry["undoable"]
    assert api.undo(entry["id"])["ok"]
    assert wait_for(lambda: api.pipeline.overview()["total"] >= 1, timeout=20)
    api.shutdown()


def _entgelt(path, monat):
    text_pdf(path, ["Musterfirma GmbH", f"Entgeltnachweis für {monat} 2026",
                    "Gehalt brutto 3.500,00 EUR", "Lohnsteuer Sozialabgaben Auszahlung"])


def test_correction_into_new_subfolder_is_learned_and_pending_ones_rechecked(env):
    (env["lib"] / "Arbeit" / "Gehalt").mkdir(parents=True)
    api = make_api(env)
    _entgelt(env["inbox"] / "e1.pdf", "September")
    _entgelt(env["inbox"] / "e2.pdf", "Oktober")
    assert wait_for(lambda: api.pipeline.overview()["total"] == 2 and api.pipeline.overview()["working"] == 0)
    items = sorted(api.pipeline.items.values(), key=lambda i: i["name"])
    assert all(i["suggestion"]["folder"] == "Arbeit/Gehalt" for i in items)
    assert items[0]["suggestion"]["reason"]  # Begründung vorhanden
    res = api.confirm(items[0]["id"], "Arbeit/Gehalt/Entgeltnachweise", "2026-09 Entgeltnachweis")["data"]
    assert res["rechecked"] == 1
    assert wait_for(lambda: api.pipeline.overview()["working"] == 0)
    second = api.item(items[1]["id"])["data"]
    assert second["suggestion"]["folder"] == "Arbeit/Gehalt/Entgeltnachweise"
    mem = api.memory.entries[-1]
    assert mem["corrected"] and mem["ai_folder"] == "Arbeit/Gehalt" and mem["ai_reason"]
    entry = api.history.get(api.history_view()["data"]["days"][0]["entries"][0]["id"])
    assert entry["info"]["corrected"] and entry["info"]["ai_folder"] == "Arbeit/Gehalt"
    api.shutdown()


def test_new_subfolder_during_reorg_is_allowed_and_kept(env):
    api = make_api(env)
    lib = env["lib"]
    (lib / "Alt").mkdir()
    _entgelt(lib / "Alt" / "a.pdf", "Juli")
    _entgelt(lib / "Alt" / "b.pdf", "August")
    assert api.reorg_start("neu")["ok"]
    assert wait_for(lambda: api.reorganizer.state.get("phase") in ("structure_review", "error"), timeout=120)
    folders = api.reorg_structure()["data"]["folders"]
    assert any(f["path"] == "Arbeit/Gehalt" for f in folders)
    api.reorg_apply(folders)
    assert wait_for(lambda: api.pipeline.overview("reorg")["working"] == 0 and
                    api.pipeline.overview("reorg")["total"] >= 2, timeout=60)
    reorg_items = sorted([i for i in api.pipeline.items.values() if i["origin"] == "reorg"
                          and "Alt" in i["src"]], key=lambda i: i["name"])
    api.confirm(reorg_items[0]["id"], "Arbeit/Gehalt/Entgeltnachweise", "2026-07 Entgeltnachweis")
    assert "Arbeit/Gehalt/Entgeltnachweise" in api.pipeline.reorg_folders
    assert any(f["path"] == "Arbeit/Gehalt/Entgeltnachweise" for f in api.reorganizer.state["structure"])
    assert wait_for(lambda: api.pipeline.overview("reorg")["working"] == 0)
    assert api.item(reorg_items[1]["id"])["data"]["suggestion"]["folder"] == "Arbeit/Gehalt/Entgeltnachweise"
    assert any(f["path"] == "Arbeit/Gehalt/Entgeltnachweise" for f in api.folders("reorg")["data"])
    api.shutdown()


def test_queue_with_suggestions_survives_restart(env):
    api = make_api(env)
    _entgelt(env["inbox"] / "e1.pdf", "September")
    text_pdf(env["inbox"] / "k.pdf", ["Sparkasse", "Kontoauszug Girokonto vom 01.10.2026", "Kontoauszug"])
    assert wait_for(lambda: api.pipeline.overview()["total"] == 2 and api.pipeline.overview()["working"] == 0)
    before = {i["src"]: i["suggestion"]["folder"] for i in api.pipeline.items.values()}
    api.pipeline.skip(next(iter(api.pipeline.items)))
    api.shutdown()  # speichert die Warteschlange

    from app.api import Api
    api2 = Api()
    calls = []
    orig = api2.ai.chat_json
    api2.ai.chat_json = lambda *a, **k: calls.append(1) or orig(*a, **k)
    after = {i["src"]: (i["status"], i["suggestion"]["folder"]) for i in api2.pipeline.items.values()}
    assert {k: v[1] for k, v in after.items()} == before
    assert all(v[0] == "ready" for v in after.values())
    assert any(i["skip"] for i in api2.pipeline.items.values())
    api2.start_background()
    import time as _t
    _t.sleep(2)
    assert calls == []  # nichts neu berechnet
    item = next(iter(api2.pipeline.items.values()))
    assert api2.confirm(item["id"])["ok"]
    assert api2.memory.entries[-1]["text"]  # Text aus dem Zwischenspeicher wiederhergestellt
    api2.shutdown()


def test_reorg_pause_restart_resume_backup(env, monkeypatch):
    lib = env["lib"]
    (lib / "Alt").mkdir()
    for i in range(12):
        text_pdf(lib / "Alt" / f"d{i}.pdf", ["Stadtwerke", f"Stromabrechnung Nr {i} vom 01.0{1 + i % 9}.2026"])
    api = make_api(env)
    import shutil as _sh
    import time as _t
    real = _sh.copy2
    copied = []

    def slow(src, dst, *a, **k):
        if str(src).endswith(".pdf"):
            _t.sleep(0.15)
            copied.append(str(src))
        return real(src, dst, *a, **k)
    monkeypatch.setattr("app.core.reorg.shutil.copy2", slow)
    api.reorg_start("neu")
    assert wait_for(lambda: len(copied) >= 4, timeout=30)
    api.reorg_pause()
    assert wait_for(lambda: api.reorganizer.state.get("phase") == "paused", timeout=30)
    assert api.reorganizer.state["paused_phase"] == "backup"
    n_first = len(api.reorganizer.state["backed_up"])
    assert 0 < n_first < 13
    api.shutdown()

    from app.api import Api
    api2 = Api()  # „Neustart nach Update“
    assert api2.reorganizer.state["phase"] == "paused"
    api2.start_background()
    copied.clear()
    api2.reorg_resume()
    assert wait_for(lambda: api2.reorganizer.state.get("phase") in ("structure_review", "error"), timeout=120)
    assert api2.reorganizer.state["phase"] == "structure_review", api2.reorganizer.state
    assert len(copied) == 13 - n_first  # bereits gesicherte Dateien wurden nicht erneut kopiert
    backup = Path(api2.reorganizer.state["backup"]["path"])
    assert len(list(backup.rglob("*.pdf"))) == 13
    # Strukturentwurf überlebt einen Neustart
    folders = api2.reorg_structure()["data"]["folders"] + [{"path": "Testordner", "scheme": "", "example": ""}]
    api2.reorg_save_structure(folders)
    api2.shutdown()
    api3 = Api()
    assert any(f["path"] == "Testordner" for f in api3.reorg_structure()["data"]["folders"])
    api3.shutdown()


def test_restart_during_reading_resumes(env, monkeypatch):
    lib = env["lib"]
    (lib / "Alt").mkdir()
    for i in range(8):
        text_pdf(lib / "Alt" / f"r{i}.pdf", ["Finanzamt", f"Steuerbescheid {i} vom 01.02.2026"])
    api = make_api(env)
    from app.docs import reader as rd
    real = rd.read_document
    seen = []

    def slow(p, *a, **k):
        import time as _t
        _t.sleep(0.2)
        seen.append(str(p))
        return real(p, *a, **k)
    monkeypatch.setattr("app.core.reorg.reader.read_document", slow)
    api.reorg_start("neu")
    assert wait_for(lambda: len(seen) >= 3, timeout=60)
    api.reorg_pause()
    assert wait_for(lambda: api.reorganizer.state.get("phase") == "paused", timeout=30)
    assert api.reorganizer.state["paused_phase"] == "reading"
    done_first = len(api.reorganizer.state.get("docs_partial", []))
    api.shutdown()
    from app.api import Api
    api2 = Api()
    seen.clear()
    api2.reorg_resume()
    assert wait_for(lambda: api2.reorganizer.state.get("phase") == "structure_review", timeout=120)
    assert len(seen) == 9 - done_first
    assert len(api2.reorganizer.state["docs"]) == 9
    api2.shutdown()
