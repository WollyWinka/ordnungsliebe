"""Rückfall-Tests für Fehler, die bei der Gesamtprüfung gefunden wurden."""

import threading
import time

import pymupdf

from app.ai.llm import LLMError
from app.api import Api
from app.core import pipeline as pl
from conftest import text_pdf, wait_for  # noqa: F401


def _api(env):
    api = Api()
    api.finish_setup(str(env["inbox"]), str(env["lib"]), "direct")
    api.start_background()
    return api


def test_reorg_kept_documents_not_requeued_after_restart(env):
    api = _api(env)
    assert api.reorg_start("verbessern")["ok"]
    assert wait_for(lambda: api.reorganizer.state.get("phase") == "structure_review", timeout=120)
    api.reorg_apply(api.reorg_structure()["data"]["folders"])
    assert wait_for(lambda: api.reorganizer.state["phase"] == "review"
                    and api.pipeline.overview("reorg")["working"] == 0, timeout=60)
    time.sleep(1)
    mem = api.memory.count()
    api.shutdown()
    for _ in range(2):
        api2 = Api()
        api2.start_background()
        assert api2.pipeline.pending_count("reorg") == 0
        time.sleep(1)
        assert api2.memory.count() == mem
        api2.shutdown()


def test_reorg_paused_not_error_when_ai_dies_during_shutdown(env):
    api = _api(env)
    killed, entered = threading.Event(), threading.Event()
    orig = api.ai.chat_json

    def chat(system, user, schema, name, max_tokens=600):
        if name == "struktur":
            entered.set()
            killed.wait(30)
            raise LLMError("Anfrage an die KI fehlgeschlagen")
        return orig(system, user, schema, name, max_tokens)
    api.ai.chat_json = chat
    api.ai.shutdown = killed.set
    api.reorg_start("neu")
    assert entered.wait(60)
    api.shutdown()
    api.reorganizer._thread.join(timeout=5)
    assert api.reorganizer.state["phase"] == "paused"
    api2 = Api()
    assert api2.reorganizer.resume()["phase"] == "structure"
    api2.reorganizer._thread.join(timeout=60)
    api2.shutdown()


def test_split_rolls_back_when_original_locked(env, monkeypatch):
    api = _api(env)
    doc = pymupdf.open()
    for line in ("Sparkasse Kontoauszug Girokonto 30.09.2026", "Stadtwerke Stromabrechnung Abschlag 01.10.2026"):
        doc.new_page().insert_text((72, 72), line)
    doc.save(str(env["inbox"] / "stapel.pdf"))
    assert wait_for(lambda: api.pipeline.overview()["total"] >= 1 and api.pipeline.overview()["working"] == 0)
    item = next(iter(api.pipeline.items.values()))
    item.update(stage="stack", starts=[1, 2])

    def locked(p):
        raise PermissionError(13, "gesperrt")
    monkeypatch.setattr(pl, "_trash", locked)
    r = api.split(item["id"], [1, 2])
    assert not r["ok"] and "geöffnet" in r["error"]
    assert item["status"] == "ready"
    assert sorted(p.name for p in env["inbox"].iterdir()) == ["stapel.pdf"]
    api.shutdown()


def test_guessed_folder_never_lands_in_batch():
    from pathlib import Path
    from app.ai import tasks
    out = tasks._postprocess({"folder": "__NEU__", "new_folder": "", "confidence": "sehr sicher"},
                             original=Path("x.pdf"), kind="pdf", folders=["Arbeit", "Steuern"], excluded=[],
                             allow_new=True, examples=[])
    assert out["confidence"] <= 0.4
    out = tasks._postprocess({"folder": "__NEU__", "new_folder": "Steuern/Bescheide", "confidence": "sehr sicher"},
                             original=Path("x.pdf"), kind="pdf", folders=["Arbeit", "Steuern"], excluded=[],
                             allow_new=True, examples=[], new_only_below=False)
    assert out["folder"] == "Steuern/Bescheide" and out["is_new_folder"]


def test_folder_list_fits_into_ai_context():
    from app.ai import tasks
    folders = [f"Bereich {i}/Unterordner mit langem Namen {j}" for i in range(20) for j in range(8)]
    info = {f: {"scheme": "JJJJ-MM Dokumentart Anbieter", "files": ["2025-01 Beispiel sehr lang.pdf"] * 3} for f in folders}
    block = tasks._folder_block(folders, info, {f: 12 for f in folders}, set())
    assert len(block) <= tasks.FOLDER_BLOCK_BUDGET * 2 and all(f in block for f in folders)


def test_error_messages_are_readable(env):
    api = _api(env)
    r = api.make_dir(str(env["tmp"] / "gibt" / "es" / "nicht"), "Neu")
    assert not r["ok"] and not r["error"].isdigit()
    api.shutdown()
