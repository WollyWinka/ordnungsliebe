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
from .ai import models, tasks
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
            msg = exc.args[0] if exc.args else ""
            log.warning("%s: %r", fn.__name__, exc)
            if not isinstance(msg, str) or " " not in msg.strip():
                # keine verständliche Meldung (z. B. Fehlernummer oder interner Schlüssel)
                msg = ("Die Datei oder der Ordner ist nicht mehr da." if isinstance(exc, FileNotFoundError)
                       else "Da ist etwas schiefgegangen. Bitte versuche es noch einmal.")
            return {"ok": False, "error": msg}
        except Exception:
            log.exception("Fehler in %s", fn.__name__)
            return {"ok": False, "error": "Da ist etwas schiefgegangen. Bitte versuche es noch einmal."}
    wrapper._exposed = True
    return wrapper


def make_bridge(api: "Api"):
    """Objekt, das pywebview an JavaScript gibt: nur die freigegebenen Methoden, keine Interna.

    pywebview durchsucht das übergebene Objekt samt Unterobjekten; deshalb bekommt es nicht die
    Api selbst (mit Warteschlange, Sperren usw.), sondern diese schlanke Hülle.
    """
    class Bridge:
        pass

    def make(name):
        original = getattr(Api, name)

        @functools.wraps(original)
        def method(self, *args):
            return getattr(api, name)(*args)
        return method

    for name in dir(Api):
        if not name.startswith("_") and getattr(getattr(Api, name), "_exposed", False):
            setattr(Bridge, name, make(name))
    return Bridge()


def _nested(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _mail_where(e: dict) -> str:
    info = e.get("info", {})
    n = len(info.get("parts", []))
    what = {"attachments": "Anhang" if n == 1 else f"{n} Anhänge", "mail": "Mail als PDF",
            "both": f"Mail als PDF und {n - 1} Anhang" if n == 2 else f"Mail als PDF und {n - 1} Anhänge"}.get(
        info.get("choice", ""), f"{n} Dokumente")
    return f"Mail „{info.get('subject', '')}“ → {what}"


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
        from .store.hints import Hints, Ignored
        self.hints = Hints()
        self.ignored = Ignored()
        from .store.collections import Collections
        from .store.docmeta import DocMeta
        from .store.search import SearchIndex
        self.docmeta = DocMeta()
        self.search_index = SearchIndex()
        self.collections = Collections()
        self._search_lock = threading.Lock()
        self._search_again = False
        self._stopping = threading.Event()
        self.pipeline = Pipeline(self.settings_store, self.ai, self.memory, self.history, self.dup,
                                 self.schemes, bus, hints=self.hints, ignored=self.ignored, docmeta=self.docmeta)
        self.reorganizer = reorg.Reorganizer(self.settings_store, self.ai, self.pipeline, self.history,
                                             self.schemes, self.dup, self.backups, bus)
        self.pipeline.on_filed = self._on_filed
        self.models = setup.ModelManager(self.settings_store, bus)
        from .core.updater import Updater
        self.updater = Updater(self.settings_store, bus)
        from .core.inventory import Inspector, Refiner
        self.inspector = Inspector(self)
        from .core.mailin import MailFetcher
        self.mailer = MailFetcher(self.settings_store, bus, self._inbox_path)
        self.refiner = Refiner(self)
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
        try:
            library.purge_quarantine(30)
            self._purge_originals(30)
            st = self.reorganizer.state
            self.backups.purge_orphans(busy_path=st.get("backup_target", "") if st.get("phase") in reorg.ACTIVE else "")
        except Exception:
            log.exception("Aufräumen beim Start fehlgeschlagen")
        self.pipeline.start()
        self.updater.check_in_background()
        s = self.settings_store.get()
        spec = models.get(s.model_id)
        if s.setup_done and (spec is None or spec.installed or os.environ.get("ORDNUNGSLIEBE_FAKE_AI")):
            threading.Thread(target=self._warmup, daemon=True).start()
        self.index_library_async()
        try:
            self.mailer.start()
        except Exception:
            log.exception("Mail-Abruf konnte nicht gestartet werden")
        try:
            self.inspector.resume_if_active()
            self.refiner.resume_after_restart()
        except Exception:
            log.exception("Hintergrundprüfung konnte nicht fortgesetzt werden")

    # --- Kontext für Bestandsprüfung und Feinschliff ---------------------------------------
    @property
    def bus(self):
        return bus

    def settings(self):
        return self.settings_store.get()

    def _inbox_path(self) -> Path | None:
        d = self.settings_store.get().inbox_dir
        return Path(d) if d and Path(d).is_dir() else None

    def library_root(self) -> Path | None:
        lib = self.settings_store.get().library_dir
        return Path(lib) if lib and Path(lib).is_dir() else None

    def busy(self) -> bool:
        return self.pipeline.busy() or self.reorganizer.state.get("phase") in reorg.RUNNING

    def reorg_active(self) -> bool:
        return self.reorganizer.state.get("phase") in reorg.ACTIVE

    def _moved_back(self, old: Path, new: Path) -> None:
        """Rückgängig gemacht: Fristen, Mappen und Suche zeigen wieder auf den alten Ort."""
        try:
            self.docmeta.moved(str(old), str(new))
            sha = self.search_index.sha_for_path(str(old)) or ""
            self.search_index.remove(str(old))
            root = self.library_root()
            if root and sha:
                from .docs import reader as _r
                text = _r.cached_text(sha)
                if text is not None:
                    self.search_index.put(new, root=root, sha=sha, text=text, extra=self._meta_extra(sha))
        except Exception:
            log.exception("Verweise nach Rückgängig nicht aktualisiert")

    def on_inspected(self, p: Path, sha: str, text: str) -> None:
        root = self.library_root()
        if root:
            self.search_index.put(p, root=root, sha=sha, text=text, extra=self._meta_extra(sha))

    def on_moved(self, src: Path, dst: Path, sha: str, text: str, folder: str, entry_id: str) -> None:
        self.dup.move(src, dst)
        self.docmeta.moved(str(src), str(dst))
        self.search_index.remove(str(src))
        root = self.library_root()
        if root:
            from .docs import reader as _r
            full = _r.cached_text(sha) if sha else None
            self.search_index.put(dst, root=root, sha=sha, text=full if full is not None else text,
                                  extra=self._meta_extra(sha))
        if text:  # künftige Dokumente dieser Art landen gleich im neuen Unterordner
            self.memory.add(text, folder, dst.name, ref=entry_id, original_name=src.name)

    def _purge_originals(self, days: int) -> int:
        """Original-Scans werden 30 Tage aufbewahrt (für „Rückgängig“), danach gilt die aufbereitete Fassung."""
        limit = time.time() - days * 86400
        store = (paths.local_dir() / "Originale").resolve()
        removed = 0
        for e in list(self.history.entries):
            info = e.get("info") or {}
            orig = info.get("original")
            if e.get("action") != "move" or not orig or e.get("undone") or e.get("ts", time.time()) > limit:
                continue
            if (info.get("cleaned") or {}).get("removed"):
                continue  # Seiten wurden entfernt → Original bleibt dauerhaft
            p = Path(orig)
            try:
                if not p.is_file() or p.resolve().parent != store:
                    continue  # schon aufgeräumt
            except OSError:
                continue
            dst = Path(e["dst"])
            if library.is_cloud_only(dst) or not reorg._unchanged(dst, e):
                continue  # abgelegte Fassung nicht prüfbar, fehlt oder wurde verändert → Original behalten
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def index_library_async(self) -> None:
        def run():
            self._index_library()
            self._index_search()
        threading.Thread(target=run, name="ablage-index", daemon=True).start()

    # --- Suchindex ----------------------------------------------------------------------
    def _meta_extra(self, sha: str) -> str:
        rec = self.docmeta.get(sha) if sha else None
        if not rec:
            return ""
        parts = [rec.get("summary", ""), rec.get("person", "")]
        parts += [d.get("what", "") for d in rec.get("deadlines", [])]
        if rec.get("steuer"):
            parts.append("Steuer")
        return " ".join(p for p in parts if p)

    def _on_filed(self, src: Path, dst: Path, sha: str, text: str, suggestion: dict) -> None:
        lib = self.settings_store.get().library_dir
        if not lib:
            return
        if str(src) != str(dst):
            self.search_index.remove(str(src))
        self.search_index.put(dst, root=Path(lib), sha=sha, text=text, extra=self._meta_extra(sha))

    def _index_search(self) -> None:
        """Baut den Suchindex auf: erst alles aus dem Zwischenspeicher, dann ungelesene Dokumente langsam."""
        from .docs import reader
        if not self._search_lock.acquire(blocking=False):
            self._search_again = True
            return
        try:
            while True:
                self._search_again = False
                lib = self.settings_store.get().library_dir
                if not lib or not Path(lib).is_dir():
                    return
                root = Path(lib)
                st = self.search_index.status
                st.update(running=True, done=0, total=0, pending=0)
                everything = list(library.walk_documents(root, include_cloud_only=True, skip_photos=True))
                current = {str(p) for p in everything}  # Cloud-Dateien bleiben im Index (Text ist bekannt)
                files = [p for p in everything if not library.is_cloud_only(p)]
                for old in self.search_index.paths():
                    if old not in current:
                        self.search_index.remove(old)
                todo = [p for p in files if not self.search_index.is_current(p)]
                st.update(total=len(files), done=len(files) - len(todo), pending=len(todo))
                later = []
                for p in todo:
                    if self._stopping.is_set():
                        return
                    try:
                        sha = self.dup.known_sha(p) or reader.file_hash(p)
                    except OSError:
                        continue
                    text = reader.cached_text(sha)
                    if text is None:
                        later.append((p, sha))
                        continue
                    self.search_index.put(p, root=root, sha=sha, text=text, extra=self._meta_extra(sha))
                    st["done"] += 1
                st["pending"] = len(later)
                bus.emit("search", dict(st))
                for p, sha in later:  # ungelesene Dokumente: nur, wenn sonst nichts zu tun ist
                    while (self.pipeline.busy() or self.reorganizer.state.get("phase") in reorg.RUNNING) \
                            and not self._stopping.is_set():
                        time.sleep(2)
                    if self._stopping.is_set() or self._search_again:
                        break
                    try:
                        if not p.exists():
                            continue
                        text = reader.read_document(p, sha=sha).text
                    except Exception:
                        log.info("Für die Suche nicht lesbar: %s", p)
                        text = ""
                    self.search_index.put(p, root=root, sha=sha, text=text, extra=self._meta_extra(sha))
                    st["done"] += 1
                    st["pending"] -= 1
                    if st["pending"] % 10 == 0:
                        bus.emit("search", dict(st))
                    time.sleep(0.05)
                if not self._search_again:
                    break
        except Exception:
            log.exception("Suchindex konnte nicht aufgebaut werden")
        finally:
            self.search_index.status["running"] = False
            bus.emit("search", dict(self.search_index.status))
            self._search_lock.release()

    def _index_library(self) -> None:
        """Prüfsummen der Ablage für die Doppelten-Erkennung (Cloud-Platzhalter werden übersprungen)."""
        from .docs import reader
        from .store import textsim
        lib = self.settings_store.get().library_dir
        if not lib or not Path(lib).is_dir():
            return
        try:
            for p in library.walk_documents(Path(lib), include_cloud_only=False):
                if self.dup.known_sha(p):
                    continue
                try:
                    sha = reader.file_hash(p)
                except OSError:
                    continue
                text = reader.cached_text(sha)
                self.dup.add_file(p, sha, textsim.fingerprint(text) if text else None)
            self.dup.prune_missing()
            self.dup.save()
        except Exception:
            log.exception("Ablage konnte nicht indiziert werden")

    def _warmup(self) -> None:
        try:
            self.ai.warmup()
        except Exception as exc:
            log.warning("KI-Start fehlgeschlagen: %s", exc)

    def shutdown(self) -> None:
        self._stopping.set()
        try:
            self.mailer.stop()
        except Exception:
            pass
        try:  # laufende Neuordnung sauber pausieren, damit sie nach dem Neustart weitergeht
            self.reorganizer.pause()
            t = self.reorganizer._thread
            if t is not None and t is not threading.current_thread():
                t.join(timeout=5)
        except Exception:
            log.exception("Neuordnung konnte beim Beenden nicht pausiert werden")
        for bg in (self.inspector, self.refiner):
            try:
                bg._stop.set()
            except Exception:
                pass
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
            "update": self.updater.status(),
        }

    @api_method
    def save_settings(self, changes: dict):
        allowed = {"font_size", "theme", "batch_level", "inbox_dir", "library_dir", "keep_cloud_local", "auto_update", "scan_enhance",
                   "persons", "person_mode"}
        changes = dict(changes or {})
        if "persons" in changes:
            names, seen = [], set()
            for n in changes["persons"] or []:
                n = naming.clean_part(str(n), "")[:40]
                if n and n.lower() not in seen:
                    seen.add(n.lower())
                    names.append(n)
            changes["persons"] = names[:12]
        if "person_mode" in changes and changes["person_mode"] not in ("dateiname", "unterordner", "merken"):
            raise ValueError("Unbekannte Einstellung.")
        if "library_dir" in changes and self.reorganizer.state.get("phase") in reorg.ACTIVE \
                and changes["library_dir"] != self.settings_store.get().library_dir:
            raise ValueError("Während einer Neuordnung kann die Ablage nicht geändert werden. "
                             "Schließe die Neuordnung erst ab oder brich sie ab.")
        if "inbox_dir" in changes or "library_dir" in changes:
            cur = self.settings_store.get()
            inbox = Path(changes.get("inbox_dir", cur.inbox_dir))
            lib = Path(changes.get("library_dir", cur.library_dir))
            if _nested(inbox, lib):
                raise ValueError("Scan-Ordner und Ablage müssen getrennte Ordner sein – keiner darf im anderen liegen.")
        self.settings_store.update(**{k: v for k, v in (changes or {}).items() if k in allowed})
        if "library_dir" in (changes or {}):
            self.index_library_async()
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
    def list_dir(self, path: str = ""):
        """Für die eingebaute Ordnerauswahl: Unterordner eines Ordners (leer = Startpunkte)."""
        if not path:
            return {"path": "", "display": "", "parent": None, "dirs": library.start_places()}
        p = Path(path)
        if not p.is_dir():
            raise FileNotFoundError("Diesen Ordner gibt es nicht (mehr).")
        parent = str(p.parent) if p.parent != p else ""
        return {"path": str(p), "display": setup.pretty_path(str(p)), "parent": parent,
                "dirs": [{"name": d.name, "path": str(d)} for d in library.subfolders(p)]}

    @api_method
    def make_dir(self, parent: str, name: str):
        clean = naming.clean_part(name, "")
        if not clean:
            raise ValueError("Bitte einen Namen eingeben.")
        target = Path(parent) / clean
        target.mkdir(parents=False, exist_ok=True)
        return {"path": str(target), "display": setup.pretty_path(str(target))}

    @api_method
    def open_folder(self, path: str):
        p = Path(path)
        if not p.is_dir():
            raise FileNotFoundError("Der Ordner existiert nicht mehr.")
        if paths.IS_WINDOWS:
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True

    # --- Updates --------------------------------------------------------------------
    @api_method
    def update_check(self):
        return self.updater.check()

    @api_method
    def update_download(self):
        self.updater.download()
        return self.updater.status()

    @api_method
    def update_install(self):
        """Erst prüfen, dann Neuordnung pausieren, alles sichern und beenden, dann Installation starten."""
        self.updater.check_ready()
        self.reorganizer.pause()
        t = self.reorganizer._thread
        if t is not None:
            t.join(timeout=30)
        try:
            self.pipeline._persist()
        except Exception:
            log.exception("Warteschlange konnte vor dem Update nicht gesichert werden")

        def run():
            time.sleep(0.8)  # Antwort an die Oberfläche geht noch raus
            try:
                self.shutdown()  # gibt KI-Programm und Dateien frei
            except Exception:
                log.exception("Beenden vor dem Update unvollständig")
            try:
                self.updater.install()
            except Exception:
                log.exception("Update konnte nicht gestartet werden")
            os._exit(0)
        threading.Thread(target=run, daemon=True).start()
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
        if _nested(inbox_p, lib_p):
            raise ValueError("Scan-Ordner und Ablage müssen getrennte Ordner sein – keiner darf im anderen liegen.")
        self.settings_store.update(inbox_dir=str(inbox_p), library_dir=str(lib_p), setup_done=True,
                                   first_run_choice=choice)
        threading.Thread(target=self._warmup, daemon=True).start()
        self.index_library_async()
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
    def item(self, item_id: str):
        return self.pipeline._public(self.pipeline.get(item_id), with_text=True)

    @api_method
    def preview(self, item_id: str, page: int = 0):
        return self.pipeline.preview(item_id, page)

    @api_method
    def preview_path(self, path: str, page: int = 0):
        """Vorschau einer bereits abgelegten Datei (nur innerhalb der Ablage)."""
        root = Path(self.settings_store.get().library_dir).resolve()
        p = Path(path).resolve()
        if root not in p.parents:
            raise ValueError("Diese Datei liegt nicht in deiner Ablage.")
        from .docs import preview as pv
        return pv.render_page(p, page, width=500)

    @api_method
    def thumbs(self, item_id: str):
        return self.pipeline.thumbs(item_id)

    @api_method
    def confirm(self, item_id: str, folder: str = None, filename: str = None, extra: dict = None):
        return self.pipeline.confirm(item_id, folder, filename, extra)

    @api_method
    def set_person(self, item_id: str, person: str, folder: str, filename: str):
        """Person im Vorschlag ändern: Ordner/Dateinamen passend zur Einstellung umbauen."""
        st = self.settings_store.get()
        folder, filename = naming.apply_person(folder, filename, person, st.persons or [], st.person_mode)
        return {"folder": folder, "folder_display": naming.display_folder(folder), "filename": filename,
                "person": person}

    # --- Suche ------------------------------------------------------------------------
    def _lib(self) -> Path:
        return Path(self.settings_store.get().library_dir or ".")

    @api_method
    def search(self, text: str):
        hits = self.search_index.search(text or "")
        for h in hits:
            sha = self.search_index.sha_for_path(h["path"])
            rec = self.docmeta.get(sha) if sha else None
            h["summary"] = rec.get("summary", "") if rec else ""
        st = dict(self.search_index.status)
        st["indexed"] = self.search_index.count()
        return {"hits": hits, "status": st}

    @api_method
    def search_status(self):
        st = dict(self.search_index.status)
        st["indexed"] = self.search_index.count()
        return st

    # --- Mappen ------------------------------------------------------------------------
    def _resolve(self, doc: dict) -> dict:
        path = doc.get("path", "")
        if not Path(path).exists() and doc.get("sha"):
            path = self.search_index.path_for_sha(doc["sha"]) or (self.docmeta.get(doc["sha"]) or {}).get("path", path)
        p = Path(path)
        sha = doc.get("sha") or self.search_index.sha_for_path(path) or ""
        rec = self.docmeta.get(sha) if sha else None
        try:
            folder = " › ".join(p.parent.relative_to(self._lib()).parts)
        except ValueError:
            folder = str(p.parent)
        return {"path": str(p), "orig": doc.get("path", ""), "name": p.name, "folder": folder, "exists": p.exists(),
                "sha": sha, "summary": (rec or {}).get("summary", ""), "doc_date": (rec or {}).get("doc_date", "")}

    def _tax_collections(self) -> dict[str, list[dict]]:
        years: dict[str, list[dict]] = {}
        for sha, rec in self.docmeta.all().items():
            if not rec.get("steuer"):
                continue
            year = (rec.get("doc_date") or "")[:4]
            if not year.isdigit():
                year = time.strftime("%Y", time.localtime(rec.get("ts", time.time())))
            years.setdefault(year, []).append({"path": rec["path"], "sha": sha})
        return years

    @api_method
    def collections_list(self):
        out = []
        for year, docs in sorted(self._tax_collections().items(), reverse=True):
            n = sum(1 for d in docs if Path(d["path"]).exists() or self.search_index.path_for_sha(d["sha"]))
            if n:
                out.append({"id": f"steuer-{year}", "name": f"Steuer {year}", "auto": True, "count": n})
        for c in self.collections.list():
            out.append({"id": c["id"], "name": c["name"], "auto": False, "count": len(c["docs"])})
        return out

    def _collection_docs(self, cid: str) -> tuple[str, bool, list[dict]]:
        if cid.startswith("steuer-"):
            year = cid.split("-", 1)[1]
            docs = self._tax_collections().get(year, [])
            return f"Steuer {year}", True, docs
        c = self.collections.get(cid)
        return c["name"], False, c["docs"]

    @api_method
    def collection_view(self, cid: str):
        name, auto, docs = self._collection_docs(cid)
        items = [self._resolve(d) for d in docs]
        if auto:
            items = [i for i in items if i["exists"]]
            items.sort(key=lambda i: (i["doc_date"], i["name"]))
        else:  # verschobene Dokumente merken sich den neuen Ort
            for i in items:
                if i["exists"] and i["orig"] != i["path"]:
                    self.collections.update_path(cid, i["orig"], i["path"])
        return {"id": cid, "name": name, "auto": auto, "items": items}

    @api_method
    def collection_create(self, name: str, path: str = ""):
        c = self.collections.create(name)
        if path:
            self.collections.add(c["id"], path, self.search_index.sha_for_path(path) or "")
        return c

    @api_method
    def collection_rename(self, cid: str, name: str):
        self.collections.rename(cid, name)
        return True

    @api_method
    def collection_delete(self, cid: str):
        """Löscht nur die Mappe (die Liste), nie die Dokumente."""
        self.collections.delete(cid)
        return True

    @api_method
    def collection_add(self, cid: str, path: str):
        if cid.startswith("steuer-"):
            sha = self.search_index.sha_for_path(path)
            if not sha or not self.docmeta.get(sha):
                raise ValueError("Dieses Dokument kenne ich noch nicht genauer – lege es in eine eigene Mappe.")
            self.docmeta.set_flag(sha, steuer=True, steuer_manual=True)
            return True
        if not Path(path).exists():
            raise FileNotFoundError("Die Datei ist nicht mehr da.")
        return self.collections.add(cid, path, self.search_index.sha_for_path(path) or "")

    @api_method
    def collection_remove(self, cid: str, path: str):
        """Nimmt ein Dokument aus der Mappe – die Datei selbst bleibt, wo sie ist."""
        if cid.startswith("steuer-"):
            sha = self.search_index.sha_for_path(path)
            found = self.docmeta.find_path(path)
            sha = sha if sha and self.docmeta.get(sha) else (found[0] if found else "")
            if not sha:
                raise KeyError("Dokument nicht gefunden.")
            self.docmeta.set_flag(sha, steuer=False, steuer_manual=True)
            return True
        self.collections.remove(cid, path)
        return True

    @api_method
    def collection_export(self, cid: str, fmt: str = "pdf"):
        from .core import export
        name, _auto, _docs = self._collection_docs(cid)
        items = [i for i in self.collection_view.__wrapped__(self, cid)["items"] if i["exists"]]
        if not items:
            raise ValueError("In dieser Mappe ist noch kein Dokument.")
        docs = [{"path": i["path"], "title": i["summary"] or Path(i["name"]).stem} for i in items]
        target_dir = Path(os.environ["ORDNUNGSLIEBE_EXPORT"]) if os.environ.get("ORDNUNGSLIEBE_EXPORT") else None
        path = export.export_zip(name, docs, target_dir) if fmt == "zip" else export.export_pdf(name, docs, target_dir)
        return {"path": str(path), "name": path.name, "folder": setup.pretty_path(str(path.parent))}

    @api_method
    def report_ui_error(self, message: str):
        log.warning("Fehler in der Oberfläche: %s", str(message)[:2000])
        return True

    # --- Mails weiterleiten (F) -------------------------------------------------------------
    @api_method
    def mail_status(self):
        return self.mailer.public()

    @api_method
    def mail_provider(self, address: str):
        from .core.mailin import provider_for
        return provider_for(address)

    @api_method
    def mail_save(self, address: str, password: str = "", senders: list = None, host: str = "", port: int = 993):
        return self.mailer.save(address, password or None, senders or [], host, port)

    @api_method
    def mail_enable(self, enabled: bool):
        return self.mailer.set_enabled(enabled)

    @api_method
    def mail_fetch_now(self):
        n = self.mailer.fetch()
        return {**self.mailer.public(), "new": n}

    @api_method
    def mail_allow_sender(self, address: str):
        return self.mailer.allow_sender(address)

    @api_method
    def mail_forget(self):
        return self.mailer.forget()

    @api_method
    def mail_choice(self, item_id: str, choice: str):
        return self.pipeline.mail_choice(item_id, choice)

    # --- Bestandsprüfung (D) und Feinschliff (E) ------------------------------------------
    @api_method
    def inspect_status(self):
        return self.inspector.status()

    @api_method
    def inspect_start(self):
        return self.inspector.start()

    @api_method
    def inspect_pause(self):
        return self.inspector.pause()

    @api_method
    def refine_candidates(self):
        return {"folders": self.refiner.candidates(), "status": self.refiner.status(),
                "reorg_active": self.reorg_active()}

    @api_method
    def refine_start(self, folder: str):
        return self.refiner.start(folder)

    @api_method
    def refine_status(self):
        return self.refiner.status()

    @api_method
    def refine_proposal(self):
        return self.refiner.proposal()

    @api_method
    def refine_apply(self, subfolders: list, moves: dict):
        return self.refiner.apply(subfolders, moves)

    @api_method
    def refine_cancel(self):
        return self.refiner.cancel()

    # --- Fristen ----------------------------------------------------------------------
    @api_method
    def deadlines(self, include_done: bool = False):
        return self.docmeta.deadlines(include_done=include_done)

    @api_method
    def deadline_done(self, dl_id: str, done: bool = True):
        if not self.docmeta.set_done(dl_id, done):
            raise KeyError("Diese Frist gibt es nicht mehr.")
        return True

    @api_method
    def deadline_ics(self, ids: list[str]):
        """Legt eine Kalenderdatei an und öffnet sie – Windows fragt dann, in welchen Kalender."""
        from .store.docmeta import make_ics
        items = [d for d in (self.docmeta.deadline(i) for i in ids or []) if d]
        if not items:
            raise ValueError("Keine Frist ausgewählt.")
        target = paths.cache_dir() / "kalender" / (f"Frist {items[0]['date']}.ics" if len(items) == 1 else "Fristen.ics")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(make_ics(items), encoding="utf-8", newline="")
        self._open(target)
        return str(target)

    def _open(self, p: Path) -> None:
        if os.environ.get("ORDNUNGSLIEBE_NO_OPEN"):
            return
        if paths.IS_WINDOWS:
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(p)])

    def _safe_doc(self, path: str) -> Path:
        """Nur Dokumente aus der Ablage oder exportierte Mappen öffnen – nie Programme."""
        from .core import export
        from .docs import reader
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError("Die Datei ist nicht mehr da – vielleicht wurde sie verschoben.")
        rp = p.resolve()
        roots = [self._lib().resolve(), export.export_dir().resolve(), (paths.cache_dir() / "kalender").resolve()]
        if not any(r in rp.parents for r in roots):
            raise ValueError("Diese Datei liegt nicht in deiner Ablage.")
        if reader.file_kind(p) is None and p.suffix.lower() not in (".zip", ".ics"):
            raise ValueError("Diese Datei kann ich nicht öffnen.")
        return p

    @api_method
    def open_file(self, path: str):
        self._open(self._safe_doc(path))
        return True

    @api_method
    def show_in_folder(self, path: str):
        p = self._safe_doc(path)
        if not p.exists():
            raise FileNotFoundError("Die Datei ist nicht mehr da – vielleicht wurde sie verschoben.")
        if os.environ.get("ORDNUNGSLIEBE_NO_OPEN"):
            return True
        if paths.IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
        return True

    @api_method
    def reject(self, item_id: str):
        self.pipeline.reject(item_id)
        return True

    @api_method
    def give_hint(self, item_id: str, text: str):
        self.pipeline.give_hint(item_id, text)
        return True

    @api_method
    def not_document(self, item_id: str):
        self.pipeline.mark_not_document(item_id, "foto")
        return True

    @api_method
    def hints_view(self):
        return {"hints": self.hints.list(), "ignored": self.ignored.count()}

    @api_method
    def hint_add_rule(self, text: str):
        return self.hints.add(text, "alle", source="")

    @api_method
    def hint_update(self, hint_id: str, text: str = None, scope: str = None):
        return self.hints.update(hint_id, text, scope)

    @api_method
    def hint_delete(self, hint_id: str):
        self.hints.delete(hint_id)
        return True

    @api_method
    def ignored_clear(self):
        n = self.ignored.clear()
        self.pipeline._ignored_inbox.clear()
        return n

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
            where = {"ignore": "als Foto markiert – wird nicht mehr vorgeschlagen",
                     "move": "nach " + naming.display_folder(e.get("folder", "")),
                     "trash": "doppelt – zur Seite gelegt (30 Tage aufbewahrt)",
                     "split": f"in {len(e.get('info', {}).get('parts', []))} Dokumente aufgeteilt",
                     "mail": _mail_where(e)}
            name = e["name"] if e["action"] != "trash" else Path(e["src"]).name
            days[label].append({
                "id": e["id"], "time": time.strftime("%H:%M", time.localtime(e["ts"])),
                "name": name, "where": where.get(e["action"], ""), "undone": e["undone"],
                "action": e["action"],
                "undoable": (e["action"] in ("move", "trash", "mail") and not e["undone"] and Path(e["dst"]).exists())
                            or (e["action"] == "ignore" and not e["undone"])})
        groups = []
        for g in sorted(self.history.groups.values(), key=lambda g: g["ts"], reverse=True):
            if not g.get("done"):
                continue
            entries = self.history.group_entries(g["id"])
            groups.append({"id": g["id"], "label": _day_label(g["ts"]), "count": len(entries),
                           "kind": g.get("kind", "reorg"), "folder": naming.display_folder(g.get("folder", "")),
                           "undone": g.get("undone", False), "cancelled": g.get("cancelled", False),
                           "undo_failed": g.get("undo_failed", 0),
                           "folders": len({e.get("folder") for e in entries}),
                           "has_backup": any(b["id"] == g["id"] and b["exists"] for b in self.backups.list())})
        return {"days": [{"label": d, "entries": days[d]} for d in order], "reorgs": groups}

    @api_method
    def undo(self, entry_id: str):
        entry = self.history.get(entry_id)
        if entry is None:
            raise KeyError("Eintrag nicht gefunden.")
        if entry["action"] == "mail":
            return self._undo_mail(entry)
        if entry["action"] == "ignore":
            self.ignored.remove(entry.get("info", {}).get("ignore_id", ""))
            self.pipeline._ignored_inbox.discard(entry["src"])
            self.history.mark_undone(entry_id)
            return {"where": setup.pretty_path(entry["src"]), "ignore": True}
        where = reorg.undo_entry(entry, self.settings_store.get(), self.history, self.memory, self.dup,
                                 moved=self._moved_back)
        return {"where": setup.pretty_path(where)}

    def _undo_mail(self, entry: dict) -> dict:
        """Mail zurück in den Scan-Ordner; noch nicht abgelegte Teile verschwinden wieder.
        Bereits abgelegte Teile bleiben – die lassen sich einzeln zurücknehmen."""
        if entry.get("undone"):
            raise ValueError("Das wurde schon rückgängig gemacht.")
        kept, back = Path(entry["dst"]), Path(entry["src"])
        if not kept.exists():
            raise FileNotFoundError("Die Mail ist nicht mehr im Papierkorb (nach 30 Tagen gelöscht).")
        left = 0
        for part in entry.get("info", {}).get("parts", []):
            p = Path(part)
            if p.exists():
                self.pipeline.forget_path(p)
                library.quarantine(p)
            else:
                left += 1
        restored = library.move_file(kept, naming.unique_path(back))
        self.history.mark_undone(entry["id"])
        # zurück in die Prüfung – diesmal mit der Frage „Anhang oder ganze Mail?“
        self.pipeline.add_file(restored, origin="inbox", mail_ask=True)
        return {"where": setup.pretty_path(str(restored)), "left": left}

    @api_method
    def undo_reorg(self, group_id: str):
        return reorg.undo_group(group_id, self.history, self.memory, self.dup, moved=self._moved_back)

    # --- Neuordnung ---------------------------------------------------------------------
    @api_method
    def reorg_start(self, mode: str, target: str = ""):
        if mode not in ("neu", "verbessern"):
            raise ValueError("Unbekannte Variante")
        return self.reorganizer.start(mode, target or "")

    @api_method
    def reorg_check_target(self, target: str):
        """Zielordner prüfen und anzeigen, wie viel Platz die Kopien brauchen."""
        import shutil as _sh
        t = self.reorganizer.check_target(target)
        need = count = 0
        for p in library.walk_documents(self.reorganizer.root, skip_photos=True):
            count += 1
            try:
                need += p.stat().st_size
            except OSError:
                pass
        free = _sh.disk_usage(t).free
        return {"path": str(t), "pretty": setup.pretty_path(str(t)), "free_gb": round(free / 1e9, 1),
                "need_gb": round(need * 1.05 / 1e9 + 0.05, 1), "count": count, "enough": free > need * 1.05 + 2e8}

    # --- Struktur als Datei (G) -----------------------------------------------------------
    @api_method
    def structure_parse(self, text: str):
        from .core import structure_io
        if len(text or "") > 500_000:
            raise ValueError("Die Datei ist zu groß für eine Ordnerstruktur.")
        folders, warnings = structure_io.parse(text or "")
        if not folders:
            raise ValueError("In dem Text habe ich keine Ordner gefunden. Eine Zeile pro Ordner, Unterordner eingerückt.")
        return {"folders": tasks.clean_structure(folders), "warnings": warnings}

    @api_method
    def structure_export(self, folders: list):
        from .core import export, structure_io
        text = structure_io.export(tasks.clean_structure(folders or []))
        target = naming.unique_path(export.export_dir() / f"Ordnungsliebe Struktur {time.strftime('%Y-%m-%d')}.txt")
        target.write_text(text, encoding="utf-8")
        return {"path": str(target), "name": target.name, "folder": setup.pretty_path(str(target.parent)),
                "text": text}

    @api_method
    def structure_ai_brief(self, folders: list = None):
        from .core import structure_io
        docs = self.reorganizer.state.get("docs") or []
        if not docs:  # außerhalb einer Neuordnung: aktuelle Ablage beschreiben
            root = self.library_root()
            if root:
                docs = [{"rel": "/".join(p.relative_to(root).parts)}
                        for p, _ in zip(library.walk_documents(root, skip_photos=True), range(20000))]
        return structure_io.ai_brief(docs, tasks.clean_structure(folders or []))

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
        r = self.reorganizer.finish()
        self.index_library_async()
        return r

    @api_method
    def reorg_use_target(self):
        """Nach der Neuordnung in einen neuen Ordner: diesen ab jetzt als Ablage verwenden."""
        st = self.reorganizer.state
        target = st.get("target")
        if st.get("phase") != "done" or not target or not Path(target).is_dir():
            raise ValueError("Es gibt keinen neuen Ordner, auf den ich umstellen könnte.")
        inbox = self.settings_store.get().inbox_dir
        if inbox and _nested(Path(inbox), Path(target)):
            raise ValueError("Der Scan-Ordner liegt in dem neuen Ordner – so geht es nicht.")
        old = self.settings_store.get().library_dir
        self.settings_store.update(library_dir=target)
        # Fristen, Mappen und Suche zeigen ab jetzt auf die Kopien
        for e in self.history.group_entries(st.get("group", "")):
            if e.get("info", {}).get("copy") and not e.get("undone"):
                self.docmeta.moved(e["src"], e["dst"])
        st["switched"] = True
        st["old_library"] = old
        self.reorganizer._save()
        self.index_library_async()
        self.bus.emit("reorg", self.reorganizer.status())
        return {"library": setup.pretty_path(target), "old": setup.pretty_path(old)}

    @api_method
    def reorg_pause(self):
        return self.reorganizer.pause()

    @api_method
    def reorg_resume(self):
        return self.reorganizer.resume()

    @api_method
    def reorg_save_structure(self, folders: list[dict]):
        self.reorganizer.save_draft(folders)
        return True

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
        st = self.reorganizer.state
        if st.get("group") == backup_id and st.get("phase") in reorg.ACTIVE:
            raise ValueError("Diese Sicherung gehört zur laufenden Neuordnung und kann erst danach gelöscht werden.")
        return self.backups.remove(backup_id)

    @api_method
    def change_model(self, model_id: str):
        if models.get(model_id) is None:
            raise ValueError("Unbekanntes Modell")
        self.ai.shutdown()
        return self.models.start(model_id)
