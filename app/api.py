"""Die Schnittstelle zwischen Oberfläche (JavaScript) und Programm (Python).

Jede Methode ist in JS als `await pywebview.api.<name>(...)` erreichbar und liefert
{ok: true, data: ...} oder {ok: false, error: "Meldung für den Nutzer"}.
"""

from __future__ import annotations

import functools
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from . import APP_VERSION, paths
from .ai import models
from .ai.llm import make_ai
from .core import library, naming, reorg, setup
from .core.pipeline import Pipeline
from .events import bus
from .settings import SettingsStore
from .store.duplicates import DuplicateIndex
from .store.history import History
from .store.memory import Memory

log = logging.getLogger(__name__)


def api_method(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return {"ok": True, "data": fn(self, *args, **kwargs)}
        except (ValueError, KeyError, FileNotFoundError, RuntimeError) as exc:
            msg = exc.args[0] if exc.args else str(exc)
            log.warning("%s: %s", fn.__name__, msg)
            return {"ok": False, "error": str(msg)}
        except Exception:
            log.exception("Fehler in %s", fn.__name__)
            return {"ok": False, "error": "Da ist etwas schiefgegangen. Bitte versuche es noch einmal."}
    return wrapper


def _day_label(ts: float) -> str:
    d = time.localtime(ts)
    today = time.localtime()
    if d.tm_year == today.tm_year and d.tm_yday == today.tm_yday:
        return "Heute"
    yest = time.localtime(time.time() - 86400)
    if d.tm_year == yest.tm_year and d.tm_yday == yest.tm_yday:
        return "Gestern"
    months = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
              "Oktober", "November", "Dezember"]
    return f"{d.tm_mday}. {months[d.tm_mon - 1]} {d.tm_year}"


class Api:
    def __init__(self):
        self._window = None
        self.settings_store = SettingsStore()
        self.ai_state = {"state": "idle", "label": ""}
        self.ai = make_ai(self.settings_store, on_status=self._on_ai_status)
        self.memory = Memory()
        self.history = History()
        self.dup = DuplicateIndex()
        self.schemes = library.Schemes()
        self.backups = reorg.Backups()
        self.pipeline = Pipeline(self.settings_store, self.ai, self.memory, self.history, self.dup,
                                 self.schemes, bus)
        self.reorganizer = reorg.Reorganizer(self.settings_store, self.ai, self.pipeline, self.history,
                                             self.schemes, self.dup, self.backups, bus)
        self.models = setup.ModelManager(self.settings_store, bus)
        self.scanfinder = setup.ScanFinder(bus)
        self._started = False

    # --- intern ---------------------------------------------------------------------
    def set_window(self, window) -> None:
        self._window = window
        bus.attach_window(window)

    def _on_ai_status(self, state: str, label: str = "") -> None:
        self.ai_state = {"state": state, "label": label}
        bus.emit("ai", self.ai_state)

    def start_background(self) -> None:
        if self._started:
            return
        self._started = True
        self.pipeline.start()
        s = self.settings_store.get()
        spec = models.get(s.model_id)
        if s.setup_done and (spec is None or spec.installed or os.environ.get("ORDNUNGSLIEBE_FAKE_AI")):
            threading.Thread(target=self._warmup, daemon=True).start()

    def _warmup(self) -> None:
        try:
            self.ai.warmup()
        except Exception as exc:
            log.warning("KI-Start fehlgeschlagen: %s", exc)

    def shutdown(self) -> None:
        self.pipeline.stop()
        self.scanfinder.stop()
        self.ai.shutdown()

    # --- Allgemein ------------------------------------------------------------------
    @api_method
    def app_state(self):
        s = self.settings_store.as_dict()
        s["inbox_display"] = setup.pretty_path(s["inbox_dir"]) if s["inbox_dir"] else ""
        s["library_display"] = setup.pretty_path(s["library_dir"]) if s["library_dir"] else ""
        backups = self.backups.list()
        return {
            "version": APP_VERSION,
            "settings": s,
            "model": self.models.status(),
            "ai": self.ai_state,
            "queue": self.pipeline.overview(),
            "reorg": self.reorganizer.status(),
            "memory_count": self.memory.count(),
            "last_backup": backups[0] if backups else None,
            "fake_ai": bool(os.environ.get("ORDNUNGSLIEBE_FAKE_AI")),
        }

    @api_method
    def save_settings(self, changes: dict):
        allowed = {"font_size", "theme", "batch_level", "inbox_dir", "library_dir", "keep_cloud_local"}
        self.settings_store.update(**{k: v for k, v in (changes or {}).items() if k in allowed})
        bus.emit("queue", self.pipeline.overview())
        return self.settings_store.as_dict()

    @api_method
    def choose_folder(self, start: str = ""):
        if self._window is None:
            raise RuntimeError("Kein Fenster")
        import webview
        dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
        if dialog is None:
            dialog = webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(dialog, directory=start or str(Path.home()))
        if not result:
            return None
        folder = result[0] if isinstance(result, (list, tuple)) else result
        return {"path": folder, "display": setup.pretty_path(folder)}

    @api_method
    def open_folder(self, path: str):
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError("Der Ordner existiert nicht mehr.")
        if paths.IS_WINDOWS:
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True

    # --- Einrichtung ----------------------------------------------------------------
    @api_method
    def hardware(self):
        return setup.hardware_report()

    @api_method
    def start_download(self, model_id: str):
        return self.models.start(model_id)

    @api_method
    def pause_download(self):
        self.models.pause()
        return True

    @api_method
    def download_status(self):
        return self.models.status()

    @api_method
    def find_scan_start(self):
        self.scanfinder.start()
        return True

    @api_method
    def find_scan_stop(self):
        self.scanfinder.stop()
        return True

    @api_method
    def suggest_inbox(self):
        """Vorschlag für den Scan-Ordner: ein vorhandener „Scans“-Ordner oder Dokumente\\Scans."""
        home = Path.home()
        for cand in (home / "Documents" / "Scans", home / "Dokumente" / "Scans", home / "Scans",
                     home / "Documents" / "Scanned Documents", home / "Documents" / "Gescannte Dokumente"):
            if cand.is_dir():
                return {"path": str(cand), **setup.inbox_info(str(cand)), "exists": True}
        target = home / "Documents" / "Scans"
        return {"path": str(target), "display": setup.pretty_path(str(target)), "count": 0, "exists": False}

    @api_method
    def inbox_info(self, path: str):
        return setup.inbox_info(path)

    @api_method
    def cloud_roots(self):
        return library.known_cloud_roots()

    @api_method
    def library_info(self, path: str):
        return setup.library_info(path)

    @api_method
    def keep_local(self, path: str):
        def run():
            n = library.keep_local(Path(path), on_progress=lambda d, t: bus.emit("keeplocal", {"done": d, "total": t}))
            bus.emit("keeplocal", {"done": n, "total": n, "finished": True})
        threading.Thread(target=run, daemon=True).start()
        return True

    @api_method
    def finish_setup(self, inbox: str, library_dir: str, choice: str):
        inbox_p, lib_p = Path(inbox), Path(library_dir)
        inbox_p.mkdir(parents=True, exist_ok=True)
        lib_p.mkdir(parents=True, exist_ok=True)
        if inbox_p.resolve() == lib_p.resolve():
            raise ValueError("Scan-Ordner und Ablage müssen verschiedene Ordner sein.")
        self.settings_store.update(inbox_dir=str(inbox_p), library_dir=str(lib_p), setup_done=True,
                                   first_run_choice=choice)
        threading.Thread(target=self._warmup, daemon=True).start()
        return self.settings_store.as_dict()

    # --- Prüfen & Einsortieren -----------------------------------------------------------
    @api_method
    def overview(self, origin: str = "inbox"):
        return self.pipeline.overview(origin)

    @api_method
    def batch(self, origin: str = "inbox"):
        return self.pipeline.batch_items(origin)

    @api_method
    def confirm_batch(self, ids: list[str]):
        return self.pipeline.confirm_batch(ids)

    @api_method
    def decline_batch(self, ids: list[str]):
        self.pipeline.decline_from_batch(ids)
        return True

    @api_method
    def next_single(self, origin: str = "inbox"):
        return self.pipeline.next_single(origin)

    @api_method
    def preview(self, item_id: str, page: int = 0):
        return self.pipeline.preview(item_id, page)

    @api_method
    def thumbs(self, item_id: str):
        return self.pipeline.thumbs(item_id)

    @api_method
    def confirm(self, item_id: str, folder: str = None, filename: str = None):
        return self.pipeline.confirm(item_id, folder, filename)

    @api_method
    def reject(self, item_id: str):
        self.pipeline.reject(item_id)
        return True

    @api_method
    def skip(self, item_id: str):
        self.pipeline.skip(item_id)
        return True

    @api_method
    def retry(self, item_id: str):
        self.pipeline.retry(item_id)
        return True

    @api_method
    def dup_keep(self, item_id: str):
        self.pipeline.keep_duplicate(item_id)
        return True

    @api_method
    def dup_trash(self, item_id: str):
        self.pipeline.trash_duplicate(item_id)
        return True

    @api_method
    def split(self, item_id: str, starts: list[int]):
        return self.pipeline.split(item_id, [int(s) for s in starts])

    @api_method
    def not_stack(self, item_id: str):
        self.pipeline.not_a_stack(item_id)
        return True

    @api_method
    def folders(self, origin: str = "inbox"):
        if origin == "reorg":
            fl = list(self.pipeline.reorg_folders)
        else:
            fl = library.list_folders(Path(self.settings_store.get().library_dir))
        return [{"path": f, "display": naming.display_folder(f)} for f in fl]

    # --- Verlauf ----------------------------------------------------------------------
    @api_method
    def history_view(self):
        days: dict[str, list] = {}
        order: list[str] = []
        for e in self.history.recent(300):
            if e["action"] == "reorg":
                continue
            label = _day_label(e["ts"])
            if label not in days:
                days[label] = []
                order.append(label)
            where = {"move": "nach " + naming.display_folder(e.get("folder", "")),
                     "trash": "doppelt – in den Papierkorb gelegt",
                     "split": f"in {len(e.get('info', {}).get('parts', []))} Dokumente aufgeteilt"}
            days[label].append({
                "id": e["id"], "time": time.strftime("%H:%M", time.localtime(e["ts"])),
                "name": e["name"], "where": where.get(e["action"], ""), "undone": e["undone"],
                "undoable": e["action"] == "move" and not e["undone"]})
        groups = []
        for g in sorted(self.history.groups.values(), key=lambda g: g["ts"], reverse=True):
            if not g.get("done"):
                continue
            entries = self.history.group_entries(g["id"])
            groups.append({"id": g["id"], "label": _day_label(g["ts"]), "count": len(entries),
                           "undone": g.get("undone", False),
                           "folders": len({e.get("folder") for e in entries}),
                           "has_backup": any(b["id"] == g["id"] and b["exists"] for b in self.backups.list())})
        return {"days": [{"label": d, "entries": days[d]} for d in order], "reorgs": groups}

    @api_method
    def undo(self, entry_id: str):
        entry = self.history.get(entry_id)
        if entry is None:
            raise KeyError("Eintrag nicht gefunden.")
        where = reorg.undo_entry(entry, self.settings_store.get(), self.history, self.memory, self.dup)
        return {"where": setup.pretty_path(where)}

    @api_method
    def undo_reorg(self, group_id: str):
        return reorg.undo_group(group_id, self.history, self.memory, self.dup)

    # --- Neuordnung ---------------------------------------------------------------------
    @api_method
    def reorg_start(self, mode: str):
        if mode not in ("neu", "verbessern"):
            raise ValueError("Unbekannte Variante")
        return self.reorganizer.start(mode)

    @api_method
    def reorg_status(self):
        return self.reorganizer.status()

    @api_method
    def reorg_structure(self):
        return self.reorganizer.get_structure()

    @api_method
    def reorg_apply(self, folders: list[dict]):
        return self.reorganizer.apply_structure(folders)

    @api_method
    def reorg_finish(self):
        return self.reorganizer.finish()

    @api_method
    def reorg_cancel(self):
        self.reorganizer.cancel()
        return True

    @api_method
    def library_overview(self):
        root = Path(self.settings_store.get().library_dir)
        info = setup.library_info(str(root)) if root.is_dir() else {"ok": False}
        return info

    # --- Einstellungen -----------------------------------------------------------------
    @api_method
    def reset_memory(self):
        self.memory.reset()
        return True

    @api_method
    def backups_list(self):
        out = []
        for b in self.backups.list():
            out.append({**b, "label": _day_label(b["ts"]), "size_mb": round(b.get("size", 0) / 1e6)})
        return out

    @api_method
    def delete_backup(self, backup_id: str):
        return self.backups.remove(backup_id)

    @api_method
    def change_model(self, model_id: str):
        if models.get(model_id) is None:
            raise ValueError("Unbekanntes Modell")
        self.ai.shutdown()
        return self.models.start(model_id)
