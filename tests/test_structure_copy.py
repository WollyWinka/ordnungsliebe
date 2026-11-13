"""Struktur aus Datei (G) und Neuordnung in einen neuen Zielordner (H)."""

import hashlib
from pathlib import Path

from app.api import Api
from app.core import structure_io
from conftest import text_pdf, wait_for

AI_ANSWER = """Gern! Hier ist ein Vorschlag:

```
Finanzen – Bank, Kredite, Geldanlagen
  Bank
    Girokonto – Kontoauszüge
      Archiv
        Alt
Wohnen – alles rund um die Wohnung
  Strom & Gas – Abrechnungen und Abschläge
Versicherungen
  Hausrat
```

Viel Spaß beim Sortieren, ich hoffe das hilft dir!
"""


def _digest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_parse_and_export_roundtrip():
    folders, warnings = structure_io.parse(AI_ANSWER)
    paths = [f["path"] for f in folders]
    assert "Finanzen/Bank/Girokonto/Archiv" in paths and not any(p.count("/") > 3 for p in paths)
    assert any("gekürzt" in w for w in warnings)
    desc = {f["path"]: f["desc"] for f in folders}
    assert desc["Finanzen/Bank/Girokonto"] == "Kontoauszüge" and desc["Wohnen/Strom & Gas"].startswith("Abrechnungen")
    again, _ = structure_io.parse(structure_io.export(folders))
    assert [(f["path"], f["desc"]) for f in again] == [(f["path"], f["desc"]) for f in sorted(
        folders, key=lambda x: [p.lower() for p in x["path"].split("/")])]
    md, _ = structure_io.parse("# Finanzen\n## Bank\n- Girokonto\n# Wohnen\n")
    assert [f["path"] for f in md] == ["Finanzen", "Finanzen/Bank", "Finanzen/Bank/Girokonto", "Wohnen"]


def _run_to_structure(api, **kw):
    assert api.reorg_start("neu", **kw)["ok"]
    assert wait_for(lambda: api.reorganizer.state.get("phase") in ("structure_review", "error"), timeout=120)
    assert api.reorganizer.state["phase"] == "structure_review", api.reorganizer.state


def _confirm_all(api, skip_last=False):
    assert wait_for(lambda: api.pipeline.overview("reorg")["working"] == 0, timeout=120)
    for it in api.batch("reorg")["data"]:
        api.confirm(it["id"])
    skipped = 0
    while True:
        it = api.next_single("reorg")["data"]
        if not it:
            break
        if skip_last and not skipped:
            api.not_document(it["id"])  # bleibt unsortiert → landet in „_Noch zu sortieren“
            skipped += 1
            continue
        api.confirm(it["id"])


def test_copy_reorg_into_new_folder_with_imported_structure(env):
    lib = env["lib"]
    old = lib / "Altes Zeug"
    old.mkdir()
    text_pdf(old / "scan1.pdf", ["Sparkasse", "Kontoauszug Girokonto vom 31.08.2026", "Kontostand"])
    text_pdf(old / "brief.pdf", ["Stadtwerke", "Stromabrechnung vom 01.07.2026", "Abschlag Strom"])
    text_pdf(old / "notiz.pdf", ["Einkaufszettel Milch Brot"])
    before = _digest(lib)
    target = env["tmp"] / "Ablage neu"
    target.mkdir()
    api = Api()
    api.finish_setup(str(env["inbox"]), str(lib), "direct")
    api.start_background()
    # ungeeignete Ziele
    assert not api.reorg_check_target(str(lib / "Finanzen"))["ok"]
    (env["tmp"] / "voll").mkdir()
    (env["tmp"] / "voll" / "x.txt").write_text("x")
    assert "nicht leer" in api.reorg_check_target(str(env["tmp"] / "voll"))["error"]
    chk = api.reorg_check_target(str(target))["data"]
    assert chk["count"] == 4 and chk["enough"]

    _run_to_structure(api, target=str(target))
    assert not api.reorganizer.state.get("backup_target")  # keine Sicherung nötig
    imported = api.structure_parse(AI_ANSWER)["data"]
    brief = api.structure_ai_brief(imported["folders"])["data"]
    assert "Altes Zeug" in brief and "Girokonto – Kontoauszüge" in brief and "Sparkasse" not in brief
    assert api.reorg_apply(imported["folders"])["ok"]
    _confirm_all(api, skip_last=True)
    assert _digest(lib) == before  # Original völlig unverändert
    fin = api.reorg_finish()["data"]
    assert fin["phase"] == "done" and fin["leftover"] == 1
    assert _digest(lib) == before
    copied = sorted(str(p.relative_to(target)) for p in target.rglob("*.pdf"))
    assert len(copied) == 4 and any(c.startswith("_Noch zu sortieren") for c in copied)
    assert (target / "Finanzen" / "Bank" / "Girokonto").exists() or (target / "Wohnen").exists()
    # Beschreibung aus der Datei landete bei den Namensschemata des Ziels
    assert api.schemes.for_library(target)["Wohnen/Strom & Gas"]["desc"].startswith("Abrechnungen")

    # Ablage umstellen
    r = api.reorg_use_target()["data"]
    assert api.settings_store.get().library_dir == str(target) and r["old"]
    # Rückgängig: entfernt nur die Kopien, Original bleibt
    grp = api.history_view()["data"]["reorgs"][0]
    u = api.undo_reorg(grp["id"])["data"]
    assert u["failed"] == 0 and not list(target.rglob("*.pdf"))
    assert _digest(lib) == before
    api.shutdown()


def test_copy_reorg_paused_and_resumed_keeps_target(env):
    target = env["tmp"] / "Neu"
    target.mkdir()
    api = Api()
    api.finish_setup(str(env["inbox"]), str(env["lib"]), "direct")
    api.start_background()
    _run_to_structure(api, target=str(target))
    api.shutdown()
    api2 = Api()
    api2.start_background()
    assert api2.reorganizer.copy_mode and api2.reorganizer.dest == target
    api2.reorg_apply(api2.reorg_structure()["data"]["folders"])
    assert api2.pipeline.reorg_target == target
    _confirm_all(api2)
    assert list(target.rglob("*.pdf")) and (env["lib"] / "Finanzen" / "Bank" / "2026-09 Kontoauszug.pdf").exists()
    api2.shutdown()
