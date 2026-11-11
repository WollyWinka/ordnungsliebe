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


class Reorganizer:
    """Zustand wird in neuordnung.json gehalten, damit ein Neustart nichts kaputt macht."""

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
        # Nach einem Neustart: laufende Phase zurück auf einen sicheren Punkt setzen
        if self.state.get("phase") in ("backup", "reading", "structure"):
            self.state.update(phase="cancelled")
            self._save()
        elif self.state.get("phase") == "review":
            self._requeue_review()

    @property
    def root(self) -> Path:
        return Path(self.settings_store.get().library_dir)

    def _save(self) -> None:
        jsonfile.save(self.state_path, self.state)

    def _progress(self, phase: str, done: int = 0, total: int = 0, detail: str = "") -> None:
        self.state.update(phase=phase, done=done, total=total, detail=detail)
        self._save()
        self.bus.emit("reorg", self.status())

    def status(self) -> dict:
        st = {k: v for k, v in self.state.items() if k not in ("docs",)}
        if st.get("phase") == "review":
            ov = self.pipeline.overview("reorg")
            st["pending"] = ov["total"]
            st["working"] = ov["working"]
        return st

    # --- Start ----------------------------------------------------------------------
    def start(self, mode: str) -> dict:
        if self._thread and self._thread.is_alive():
            return self.status()
        if self.state.get("phase") in ("structure_review", "review"):
            return self.status()
        self._cancel.clear()
        gid = self.history.start_group("neuordnung", mode=mode, library=str(self.root))
        self.state = {"group": gid, "mode": mode, "phase": "backup", "started": time.time()}
        self._save()
        self._thread = threading.Thread(target=self._run, name="neuordnung", daemon=True)
        self._thread.start()
        return self.status()

    def cancel(self) -> None:
        self._cancel.set()
        if self.state.get("phase") in ("structure_review", "review"):
            self.pipeline.remove_origin("reorg")
            gid = self.state.get("group", "")
            entries = self.history.group_entries(gid)
            if entries:  # bereits verschobene Dokumente bleiben im Verlauf rückgängig machbar
                self.history.update_group(gid, done=True, cancelled=True, count=len(entries))
            self.state.update(phase="cancelled")
            self._save()
            self.bus.emit("reorg", self.status())

    def _run(self) -> None:
        try:
            self._backup()
            if self._cancel.is_set():
                return self._progress("cancelled")
            docs = self._read_all()
            if self._cancel.is_set():
                return self._progress("cancelled")
            self._build_structure(docs)
        except (LLMError, OcrUnavailable) as exc:
            self.state["error"] = str(exc)
            self._progress("error", detail=str(exc))
        except Exception as exc:
            log.exception("Neuordnung fehlgeschlagen")
            self.state["error"] = "Bei der Neuordnung ist ein Fehler aufgetreten. Deine Dateien sind unverändert."
            self._progress("error", detail=str(exc))

    def _backup(self) -> None:
        root = self.root
        count, size = dir_size(root)
        free = shutil.disk_usage(paths.backups_dir()).free
        if free < size * 1.1 + 200 * 1024 * 1024:
            raise RuntimeError("Für die Sicherung ist nicht genug Platz auf dem Computer frei.")
        self._progress("backup", 0, count)
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        target = paths.backups_dir() / f"{stamp} {root.name} {self.state['group'][:4]}"
        copied = [0]

        def copy(src, dst):
            shutil.copy2(src, dst)
            copied[0] += 1
            if copied[0] % 10 == 0:
                self._progress("backup", copied[0], count)

        shutil.copytree(root, target, copy_function=copy)
        rec = {"id": self.state["group"], "ts": time.time(), "path": str(target), "count": count,
               "size": size, "library": str(root)}
        self.backups.add(rec)
        self.state["backup"] = rec
        self._progress("backup", count, count)

    def _read_all(self) -> list[dict]:
        root = self.root
        files = list(library.walk_documents(root))
        docs = []
        for i, p in enumerate(files, 1):
            if self._cancel.is_set():
                break
            self._progress("reading", i - 1, len(files), p.name)
            try:
                sha = reader.file_hash(p)
                doc = reader.read_document(p, sha=sha)
                fp = textsim.fingerprint(doc.text)
                self.dup.add_file(p, sha, fp)
                docs.append({"path": str(p), "rel": "/".join(p.relative_to(root).parts),
                             "text": doc.text[:1500], "sha": sha})
            except OcrUnavailable:
                raise
            except Exception:
                log.exception("Konnte %s nicht lesen", p)
        self.dup.save()
        self.state["docs"] = [{"path": d["path"], "rel": d["rel"], "sha": d["sha"]} for d in docs]
        self._progress("reading", len(files), len(files))
        return docs

    def _build_structure(self, docs: list[dict]) -> None:
        root = self.root
        existing = library.folder_counts(root)
        self._progress("structure", 0, 1)
        structure = tasks.build_taxonomy(self.ai, docs, self.state.get("mode", "neu"), existing,
                                         on_progress=lambda d, t: self._progress("structure", d, t))
        if not structure:
            raise LLMError("Die KI konnte keine Ordnerstruktur vorschlagen.")
        # Beispiel-Dateinamen und Anzahl je Ordner ergänzen (Anzahl ist eine Schätzung)
        self.state["structure"] = structure
        self.state["doc_count"] = len(docs)
        self._progress("structure_review")

    # --- Struktur prüfen ----------------------------------------------------------
    def get_structure(self) -> dict:
        return {"folders": self.state.get("structure", []), "doc_count": self.state.get("doc_count", 0),
                "backup": self.state.get("backup")}

    def apply_structure(self, folders: list[dict]) -> dict:
        folders = tasks.clean_structure(folders)
        if not folders:
            raise ValueError("Die Struktur ist leer.")
        self.state["structure"] = folders
        self.schemes.set_all(self.root, folders)
        self.state["phase"] = "review"
        self._save()
        self._requeue_review()
        self.bus.emit("reorg", self.status())
        return self.status()

    def _requeue_review(self) -> None:
        folders = [f["path"] for f in self.state.get("structure", [])]
        self.pipeline.reorg_folders = folders
        self.pipeline.reorg_group = self.state.get("group", "")
        done = {e["src"] for e in self.history.group_entries(self.state.get("group", ""))}
        queued = {it["src"] for it in self.pipeline.items.values() if it["origin"] == "reorg"}
        for d in self.state.get("docs", []):
            p = Path(d["path"])
            if d["path"] in done or d["path"] in queued or not p.exists():
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


def undo_entry(entry: dict, settings, history, memory, dup) -> str:
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
    dup.save()
    memory.remove_ref(entry["id"])
    history.mark_undone(entry["id"])
    return str(back)


def undo_group(gid: str, history, memory, dup) -> dict:
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
