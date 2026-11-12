"""Einmalige Neuordnung der Ablage: Sicherung → Einlesen → Struktur → Zuordnen → Aufräumen.

Außerdem: Rückgängig für einzelne Einträge und für eine ganze Neuordnung.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path

from .. import jsonfile, paths
from ..ai import tasks
from ..ai.llm import LLMError
from ..docs import reader
from ..docs.ocr import OcrUnavailable
from ..store import textsim
from . import library, naming

log = logging.getLogger(__name__)

TOO_MANY = 3000          # ab hier warnt die Oberfläche vor sehr langer Laufzeit
SECONDS_PER_DOC = 5      # grobe Schätzung: Lesen + Einordnen auf einer guten Grafikkarte


class ReorgError(RuntimeError):
    """Fehler mit verständlicher Meldung für den Nutzer."""


class Backups:
    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "sicherungen.json")
        self.items: list[dict] = jsonfile.load(self.path, [])

    def add(self, record: dict) -> None:
        self.items.append(record)
        jsonfile.save(self.path, self.items)

    def list(self) -> list[dict]:
        out = []
        for b in reversed(self.items):
            b = dict(b)
            b["exists"] = Path(b["path"]).exists()
            out.append(b)
        return out

    def purge_orphans(self, busy_path: str = "") -> int:
        """Entfernt halbfertige Sicherungen früherer, abgebrochener Versuche (nicht in der Liste)."""
        known = {str(Path(b["path"])) for b in self.items}
        removed = 0
        root = paths.backups_dir()
        for d in root.iterdir():
            if d.is_dir() and str(d) not in known and str(d) != busy_path and time.time() - d.stat().st_mtime > 3600:
                shutil.rmtree(library.long_path(d), ignore_errors=True)
                removed += 1
        return removed

    def remove(self, backup_id: str) -> bool:
        rec = next((b for b in self.items if b["id"] == backup_id), None)
        if rec is None:
            return False
        shutil.rmtree(rec["path"], ignore_errors=True)
        self.items = [b for b in self.items if b["id"] != backup_id]
        jsonfile.save(self.path, self.items)
        return True


def dir_size(root: Path) -> tuple[int, int]:
    count = size = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            try:
                size += (Path(dirpath) / f).stat().st_size
                count += 1
            except OSError:
                pass
    return count, size


RUNNING = ("backup", "reading", "structure")
ACTIVE = RUNNING + ("paused", "structure_review", "review")


class Reorganizer:
    """Zustand wird in neuordnung.json gehalten. Sicherung, Einlesen und Struktur lassen sich
    pausieren und nach einem Neustart (z. B. nach einem Update) genau dort fortsetzen."""

    def __init__(self, settings_store, ai, pipeline, history, schemes, dupindex, backups, bus):
        self.settings_store = settings_store
        self.ai = ai
        self.pipeline = pipeline
        self.history = history
        self.schemes = schemes
        self.dup = dupindex
        self.backups = backups
        self.bus = bus
        self.state_path = paths.data_dir() / "neuordnung.json"
        self.state: dict = jsonfile.load(self.state_path, {})
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._pause_requested = False
        pipeline.on_reorg_folder_added = self._folder_added
        # Nach einem Neustart: laufende Arbeit gilt als pausiert und kann fortgesetzt werden
        if self.state.get("phase") in RUNNING:
            self.state.update(paused_phase=self.state["phase"], phase="paused")
            self._save()
        if self.state.get("phase") == "review":
            self._requeue_review()

    @property
    def root(self) -> Path:
        return Path(self.settings_store.get().library_dir)

    def _save(self) -> None:
        jsonfile.save(self.state_path, self.state)

    def _progress(self, phase: str, done: int = 0, total: int = 0, detail: str = "", save: bool = True) -> None:
        self.state.update(phase=phase, done=done, total=total, detail=detail)
        if save:
            self._save()
        self.bus.emit("reorg", self.status())

    def status(self) -> dict:
        hidden = ("docs", "backed_up", "skipped", "docs_partial", "structure_draft")
        st = {k: v for k, v in self.state.items() if k not in hidden}
        st["skipped_count"] = len(self.state.get("skipped", []))
        if st.get("phase") == "review":
            ov = self.pipeline.overview("reorg")
            st["pending"] = ov["total"]
            st["working"] = ov["working"]
        return st

    # --- Start, Pause, Fortsetzen ---------------------------------------------------
    def start(self, mode: str) -> dict:
        if self._thread and self._thread.is_alive():
            return self.status()
        if self.state.get("phase") in ("structure_review", "review", "paused"):
            return self.status()
        gid = self.history.start_group("neuordnung", mode=mode, library=str(self.root))
        self.state = {"group": gid, "mode": mode, "phase": "backup", "started": time.time(),
                      "library": str(self.root)}
        self._save()
        self._launch("backup")
        return self.status()

    def _launch(self, phase: str) -> None:
        self._cancel.clear()
        self._pause_requested = False
        self._thread = threading.Thread(target=self._run, args=(phase,), name="neuordnung", daemon=True)
        self._thread.start()

    def pause(self) -> dict:
        if self.state.get("phase") in RUNNING and self._thread and self._thread.is_alive():
            self._pause_requested = True
            self._cancel.set()
        return self.status()

    def resume(self) -> dict:
        if self.state.get("phase") != "paused" or (self._thread and self._thread.is_alive()):
            return self.status()
        lib = self.state.get("library")
        if lib and Path(lib) != self.root:
            raise ReorgError("Die Ablage wurde inzwischen geändert. Bitte stelle sie in den Einstellungen wieder auf "
                             f"„{lib}“ oder brich die Neuordnung ab.")
        phase = self.state.get("paused_phase", "backup")
        self.state["phase"] = phase
        self.state["error"] = ""
        self._save()
        self._launch(phase)
        return self.status()

    def cancel(self) -> None:
        self._pause_requested = False
        self._cancel.set()
        if self.state.get("phase") in ("structure_review", "review", "paused"):
            self.pipeline.remove_origin("reorg")
            gid = self.state.get("group", "")
            entries = self.history.group_entries(gid)
            if entries:  # bereits verschobene Dokumente bleiben im Verlauf rückgängig machbar
                self.history.update_group(gid, done=True, cancelled=True, count=len(entries))
            self.state.update(phase="cancelled")
            self._save()
            self.bus.emit("reorg", self.status())

    def _stopped(self, phase: str) -> bool:
        """Wurde unterbrochen? Dann Zustand passend setzen (pausiert oder abgebrochen)."""
        if not self._cancel.is_set():
            return False
        if self._pause_requested:
            self.state["paused_phase"] = phase
            self._progress("paused", self.state.get("done", 0), self.state.get("total", 0))
        else:
            self._progress("cancelled")
        return True

    def _run(self, phase: str = "backup") -> None:
        try:
            if phase == "backup":
                self._backup()
                if self._stopped("backup"):
                    return
            if phase in ("backup", "reading"):
                docs = self._read_all()
                if self._stopped("reading"):
                    return
            else:
                docs = self._docs_from_cache()
            self._build_structure(docs)
            if self._stopped("structure"):
                return
        except (LLMError, OcrUnavailable, ReorgError) as exc:
            cur = self.state.get("phase", phase)
            if self._cancel.is_set() and cur in RUNNING:
                self._stopped(cur)  # Pause/Beenden während die KI antwortete → einfach pausiert
                return
            log.warning("Neuordnung angehalten: %s", exc)
            if isinstance(exc, (LLMError, OcrUnavailable)) and cur in RUNNING:
                # vorübergehendes Problem: pausieren, damit es später weitergehen kann
                self.state["paused_phase"] = cur
                self.state["error"] = str(exc)
                self._progress("paused", self.state.get("done", 0), self.state.get("total", 0))
                return
            self.state["error"] = str(exc)
            self._progress("error", detail="")
        except Exception as exc:
            cur = self.state.get("phase", phase)
            if self._cancel.is_set() and cur in RUNNING:
                self._stopped(cur)
                return
            log.exception("Neuordnung fehlgeschlagen")
            self.state["error"] = "Bei der Neuordnung ist ein Fehler aufgetreten. Deine Dateien sind unverändert."
            self._progress("error", detail=f"{type(exc).__name__}: {exc}"[:300])

    def _copy_with_retry(self, src: Path, dst: Path) -> str:
        """Kopiert eine Datei; bei Cloud-Dateien mit Wartezeit für den Download. Gibt "" oder den Grund zurück."""
        last = ""
        for attempt in range(4):
            try:
                os.makedirs(library.long_path(dst.parent), exist_ok=True)
                shutil.copy2(library.long_path(src), library.long_path(dst))
                if os.path.getsize(library.long_path(dst)) != os.path.getsize(library.long_path(src)):
                    raise OSError("Kopie unvollständig")
                return ""
            except FileNotFoundError:
                return "nicht mehr vorhanden"
            except OSError as exc:
                cloud = getattr(exc, "winerror", None) in library.CLOUD_ERRORS
                last = "konnte nicht aus der Cloud geladen werden" if cloud else (exc.strerror or str(exc))
                if self._cancel.is_set():
                    break
                time.sleep(2 + attempt * 4)
        return last

    def _backup(self) -> None:
        """Sichert genau die Dokumente, die die Neuordnung anfassen darf – Datei für Datei.

        Dateien, die sich nicht sichern lassen (z. B. weil iCloud sie gerade nicht liefert),
        werden übersprungen und später NICHT verschoben. Nach einer Pause geht es mit der
        nächsten noch nicht gesicherten Datei weiter.
        """
        root = self.root
        self._progress("backup", 0, 0, "Ich suche deine Dokumente …")
        files = list(library.walk_documents(root, skip_photos=True))
        if not files:
            raise ReorgError("In deiner Ablage habe ich keine Dokumente gefunden.")
        size = 0
        for p in files:
            try:
                size += p.stat().st_size
            except OSError:
                pass
        target = Path(self.state["backup_target"]) if self.state.get("backup_target") else None
        if target is None:
            free = shutil.disk_usage(paths.backups_dir()).free
            need = size * 1.05 + 300 * 1024 * 1024
            if free < need:
                raise ReorgError(
                    f"Für die Sicherung werden etwa {need / 1e9:.1f} GB gebraucht, frei sind nur "
                    f"{free / 1e9:.1f} GB. Bitte mach Platz frei oder wähle als Ablage einen kleineren Ordner."
                    .replace(".", ",", 2))
            stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            target = paths.backups_dir() / f"{stamp} {root.name} {self.state['group'][:4]}"
            target.mkdir(parents=True, exist_ok=False)
            self.state["backup_target"] = str(target)
            self._save()
        saved: list[str] = self.state.setdefault("backed_up", [])
        if saved:  # nach einer Pause: nur gelten lassen, was wirklich vollständig in der Sicherung liegt
            ok = []
            for x in saved:
                try:
                    rel = Path(x).relative_to(root)
                    if os.path.getsize(library.long_path(target / rel)) == os.path.getsize(library.long_path(Path(x))):
                        ok.append(x)
                except (OSError, ValueError):
                    pass
            saved[:] = ok
        skipped: list[dict] = self.state.setdefault("skipped", [])
        done = set(saved) | {root.joinpath(*x["rel"].split("/")).as_posix() for x in skipped}
        done_posix = {Path(x).as_posix() for x in done}
        for i, p in enumerate(files, 1):
            if self._cancel.is_set():
                self._save()
                return
            if p.as_posix() in done_posix:
                continue
            if i % 5 == 1 or i == len(files):
                self._progress("backup", i - 1, len(files), p.name, save=(i % 50 == 1))
            rel = p.relative_to(root)
            reason = self._copy_with_retry(p, target / rel)
            if reason:
                log.warning("Nicht gesichert: %s (%s)", p, reason)
                skipped.append({"rel": "/".join(rel.parts), "reason": reason})
            else:
                saved.append(str(p))
        if not saved:
            hint = " Läuft iCloud für Windows und bist du angemeldet?" if any(
                "Cloud" in x["reason"] for x in skipped) else ""
            raise ReorgError("Keine einzige Datei ließ sich sichern. Deshalb verändere ich nichts." + hint)
        rec = {"id": self.state["group"], "ts": time.time(), "path": str(target), "count": len(saved),
               "size": size, "library": str(root), "skipped": len(skipped)}
        if not any(b["id"] == rec["id"] for b in self.backups.items):
            self.backups.add(rec)
        self.state["backup"] = rec
        self._progress("backup", len(files), len(files))

    def _read_all(self) -> list[dict]:
        root = self.root
        if "docs" in self.state and "backed_up" not in self.state:
            return self._docs_from_cache()  # Lesen war schon fertig (Neustart kurz danach)
        files = [Path(p) for p in self.state.get("backed_up", [])]  # nur gesicherte Dateien
        partial: list[dict] = self.state.setdefault("docs_partial", [])
        done = {d["path"] for d in partial}
        docs = [dict(d, text=(reader.cached_text(d["sha"]) or "")[:1500]) for d in partial]
        for i, p in enumerate(files, 1):
            if self._cancel.is_set():
                self._save()
                return docs
            if str(p) in done:
                continue
            self._progress("reading", i - 1, len(files), p.name, save=False)
            try:
                sha = reader.file_hash(p)
                doc = reader.read_document(p, sha=sha)
                fp = textsim.fingerprint(doc.text)
                self.dup.add_file(p, sha, fp)
                entry = {"path": str(p), "rel": "/".join(p.relative_to(root).parts), "sha": sha}
                partial.append(entry)
                docs.append(dict(entry, text=doc.text[:1500]))
            except OcrUnavailable:
                raise
            except Exception:
                log.exception("Konnte %s nicht lesen", p)
                self.state.setdefault("skipped", []).append(
                    {"rel": "/".join(p.relative_to(root).parts), "reason": "konnte nicht gelesen werden"})
            if i % 25 == 0:
                self.dup.save()
                self._save()
        self.dup.save()
        self.state["docs"] = [{"path": d["path"], "rel": d["rel"], "sha": d["sha"]} for d in docs]
        self.state.pop("docs_partial", None)
        self.state.pop("backed_up", None)
        self._progress("reading", len(files), len(files))
        return docs

    def _docs_from_cache(self) -> list[dict]:
        return [dict(d, text=(reader.cached_text(d["sha"]) or "")[:1500]) for d in self.state.get("docs", [])]

    def _build_structure(self, docs: list[dict]) -> None:
        root = self.root
        existing = library.folder_counts(root)
        self._progress("structure", 0, 1)
        structure = tasks.build_taxonomy(self.ai, docs, self.state.get("mode", "neu"), existing,
                                         on_progress=lambda d, t: self._progress("structure", d, t),
                                         should_stop=self._cancel.is_set)
        if self._cancel.is_set():
            return
        if not structure:
            raise LLMError("Die KI konnte keine Ordnerstruktur vorschlagen.")
        self.state["structure"] = structure
        self.state["doc_count"] = len(docs)
        self._progress("structure_review")

    # --- Struktur prüfen ----------------------------------------------------------
    def save_draft(self, folders: list[dict]) -> None:
        """Änderungen an der Struktur sofort sichern (auch vor „Struktur übernehmen“)."""
        if self.state.get("phase") == "structure_review":
            self.state["structure_draft"] = folders
            self._save()

    def get_structure(self) -> dict:
        skipped = self.state.get("skipped", [])
        folders = self.state.get("structure_draft") or self.state.get("structure", [])
        return {"folders": folders, "doc_count": self.state.get("doc_count", 0),
                "backup": self.state.get("backup"), "skipped_count": len(skipped),
                "skipped": skipped[:8]}

    def apply_structure(self, folders: list[dict]) -> dict:
        folders = tasks.clean_structure(folders)
        if not folders:
            raise ValueError("Die Struktur ist leer.")
        self.state["structure"] = folders
        self.state.pop("structure_draft", None)
        self.schemes.set_all(self.root, folders)
        self.state["phase"] = "review"
        self._save()
        self._requeue_review()
        self.bus.emit("reorg", self.status())
        return self.status()

    def _folder_added(self, folder: str) -> None:
        struct = self.state.setdefault("structure", [])
        if not any(f["path"] == folder for f in struct):
            struct.append({"path": folder, "scheme": "JJJJ-MM Dokumentart", "example": ""})
            self._save()
            self.schemes.set_one(self.root, folder, "JJJJ-MM Dokumentart", "")

    def _requeue_review(self) -> None:
        folders = [f["path"] for f in self.state.get("structure", [])]
        self.pipeline.reorg_folders = folders
        self.pipeline.reorg_group = self.state.get("group", "")
        done = {e["src"] for e in self.history.group_entries(self.state.get("group", ""))}
        queued = {it["src"] for it in self.pipeline.items.values() if it["origin"] == "reorg"}
        for d in self.state.get("docs", []):
            p = Path(d["path"])
            if d["path"] in done or d["path"] in queued or d["path"] in self.pipeline.reorg_kept or not p.exists():
                continue
            self.pipeline.add_file(p, origin="reorg", group=self.state["group"], sha=d.get("sha"))

    # --- Abschluss --------------------------------------------------------------------
    def finish(self) -> dict:
        group = self.history.groups.get(self.state.get("group", ""), {})
        root = Path(group.get("library") or self.root)
        removed = library.remove_empty_dirs(root)
        # Ordner der neuen Struktur anlegen? Nein – nur Ordner mit Inhalt bleiben bestehen.
        self.history.update_group(self.state["group"], done=True, removed_dirs=removed,
                                  count=len(self.history.group_entries(self.state["group"])))
        self.pipeline.remove_origin("reorg")
        self.state.update(phase="done", removed_dirs=removed, finished=time.time())
        self._save()
        self.bus.emit("reorg", self.status())
        return self.status()


# --- Rückgängig -----------------------------------------------------------------------

def _unchanged(path: Path, entry: dict) -> bool:
    """Liegt an path noch genau die Datei, die wir damals abgelegt haben?"""
    info = entry.get("info", {})
    if not path.is_file():
        return False
    try:
        if info.get("dst_size") is not None and path.stat().st_size != info["dst_size"]:
            return False
        if info.get("dst_sha"):
            return reader.file_hash(path) == info["dst_sha"]
    except OSError:
        return False
    return True


def undo_entry(entry: dict, settings, history, memory, dup, moved=None) -> str:
    """Macht einen Verlaufseintrag rückgängig. Gibt den neuen Ort zurück.

    Vorher wird geprüft, dass am Ablageort noch genau dieselbe Datei liegt. Nichts wird gelöscht:
    Eine umgewandelte Kopie wandert in den Ordnungsliebe-Papierkorb.
    """
    if entry.get("undone"):
        return entry.get("src", "")
    action = entry["action"]
    dst = Path(entry["dst"]) if entry.get("dst") else None
    src = Path(entry["src"])
    if action not in ("move", "reorg", "trash") or dst is None:
        raise ValueError("Diese Aktion lässt sich nicht rückgängig machen.")
    if not dst.exists():
        raise FileNotFoundError("Die Datei liegt nicht mehr dort, wo sie abgelegt wurde.")
    if not _unchanged(dst, entry):
        raise ValueError("Die Datei wurde inzwischen verändert oder ersetzt. Bitte verschiebe sie selbst.")
    inbox = Path(settings.inbox_dir) if settings.inbox_dir else src.parent
    if action == "move":
        original = Path(entry.get("info", {}).get("original") or "")
        if original.is_file():
            # erst die umgewandelte Kopie weglegen, dann das Original zurückholen
            parked = library.quarantine(dst)
            try:
                back = library.move_file(original, inbox / src.name)
            except Exception:
                library.move_file(parked, dst)
                raise
        else:
            back = library.move_file(dst, inbox / dst.name)
        dup.remove(dst)
    elif action == "trash":
        back = library.move_file(dst, inbox / src.name)
    else:
        back = library.move_file(dst, src)
        dup.move(dst, back)
        if moved:
            moved(dst, back)
    dup.save()
    memory.remove_ref(entry["id"])
    history.mark_undone(entry["id"])
    return str(back)


def undo_group(gid: str, history, memory, dup, moved=None) -> dict:
    """Macht eine komplette Neuordnung rückgängig (Datei für Datei, in umgekehrter Reihenfolge).

    Dateien, die inzwischen verändert oder weiterverschoben wurden, bleiben, wo sie sind, und
    werden als nicht zurückgesetzt gemeldet. Ein erneuter Versuch ist möglich.
    """
    group = history.groups.get(gid) or {}
    root = Path(group.get("library", ""))
    for rel in group.get("removed_dirs", []):
        try:
            naming.folder_to_path(root, rel).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    ok = failed = 0
    created: list[str] = []
    for entry in reversed(history.group_entries(gid)):
        if entry.get("undone"):
            continue
        dst, src = Path(entry["dst"]), Path(entry["src"])
        try:
            if dst != src:
                if not _unchanged(dst, entry):
                    failed += 1
                    continue
                src.parent.mkdir(parents=True, exist_ok=True)
                back = library.move_file(dst, src)
                dup.move(dst, back)
                if moved:
                    moved(dst, back)
            history.mark_undone(entry["id"])
            memory.remove_ref(entry["id"])
            created += entry.get("info", {}).get("created_dirs", [])
            ok += 1
        except Exception:
            log.exception("Rückgängig fehlgeschlagen für %s", entry.get("dst"))
            failed += 1
    dup.save()
    # nur Ordner entfernen, die die Neuordnung selbst angelegt hat – und nur, wenn sie leer sind
    for d in sorted(set(created), key=len, reverse=True):
        try:
            Path(d).rmdir()
        except OSError:
            pass
    history.update_group(gid, undone=failed == 0, undo_failed=failed)
    return {"ok": ok, "failed": failed}
