"""Bestand nachträglich prüfen (Idee D) und große Ordner unterteilen (Idee E).

Bestandsprüfung: Die KI liest bereits abgelegte Dokumente und merkt sich Kurzbeschreibung,
Steuer-Relevanz, Fristen und Person. Es wird nichts verschoben oder umbenannt. Läuft im
Hintergrund, nur wenn sonst nichts zu tun ist, und setzt nach Neustart/Update dort fort.

Feinschliff: Für einen vollen Ordner schlägt die KI Unterordner vor; der Nutzer prüft und
bestätigt, erst dann wird verschoben – mit Verlauf und „Alles rückgängig“.
"""

from __future__ import annotations

import datetime as _dt
import logging
import threading
import time
from pathlib import Path

from .. import jsonfile, paths
from ..ai import tasks
from ..docs import reader
from . import library, naming

log = logging.getLogger(__name__)

REFINE_MIN_DOCS = 25


def _rel_folder(root: Path, p: Path) -> str:
    try:
        return "/".join(p.parent.relative_to(root).parts)
    except ValueError:
        return ""


def _text_for(p: Path, sha: str) -> str:
    text = reader.cached_text(sha)
    if text is None:
        text = reader.read_document(p, sha=sha).text
    return text or ""


class _Background:
    """Gemeinsame Grundlage: Zustand in einer Datei, ein Arbeits-Thread, Pause, Fortsetzen."""

    FILE = ""
    EVENT = ""

    def __init__(self, ctx):
        self.ctx = ctx
        self.path = paths.local_dir() / self.FILE
        self.state: dict = jsonfile.load(self.path, {})
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _save(self) -> None:
        with self._lock:
            jsonfile.save(self.path, self.state)

    def _emit(self) -> None:
        try:
            self.ctx.bus.emit(self.EVENT, self.status())
        except Exception:
            log.exception("Statusmeldung fehlgeschlagen")

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _launch(self, target) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._guard(target), name=self.FILE, daemon=True)
        self._thread.start()

    def _guard(self, target):
        def run():
            try:
                target()
            except Exception as exc:
                log.exception("%s fehlgeschlagen", self.FILE)
                self.state.update(phase="error", error=str(exc) or "Unbekannter Fehler",
                                  active=self.state.get("active", False) and self.EVENT == "inspect")
                self._save()
            self._emit()
        return run

    def _wait_idle(self) -> bool:
        """Wartet, bis Einsortieren und Neuordnung nichts zu tun haben. False = abbrechen."""
        while not self._stop.is_set():
            if not self.ctx.busy():
                return True
            self._stop.wait(2)
        return False

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=10)


class Inspector(_Background):
    FILE = "bestandspruefung.json"
    EVENT = "inspect"

    def status(self) -> dict:
        s = self.state
        done, total = s.get("done", 0), s.get("total", 0)
        left = max(0, total - done)
        return {"active": bool(s.get("active")), "running": self.running(), "phase": s.get("phase", "idle"),
                "done": done, "total": total, "left": left, "minutes": max(1, round(left * 6 / 60)) if left else 0,
                "found_tax": s.get("found_tax", 0), "found_deadlines": s.get("found_deadlines", 0),
                "skipped": s.get("skipped", 0), "cloud_only": s.get("cloud_only", 0),
                "finished": s.get("finished", 0), "error": s.get("error", "")}

    def resume_if_active(self) -> None:
        if self.state.get("active") and not self.running():
            self._launch(self._run)

    def start(self) -> dict:
        if not self.ctx.library_root():
            raise ValueError("Bitte zuerst eine Ablage einrichten.")
        if not self.running():
            if self.state.get("phase") in ("done", "error", None, "idle"):
                self.state = {"failed": self.state.get("failed", []), "found_tax": 0, "found_deadlines": 0}
            self.state.update(active=True, phase="counting", error="", started=time.time())
            self._save()
            self._launch(self._run)
        self._emit()
        return self.status()

    def pause(self) -> dict:
        self.state.update(active=False, phase="paused")
        self._save()
        self.stop()
        self._emit()
        return self.status()

    def _run(self) -> None:
        root = self.ctx.library_root()
        if not root:
            return
        self.state["phase"] = "counting"
        self._emit()
        files, cloud = [], 0
        for p in library.walk_documents(root, include_cloud_only=True, skip_photos=True):
            if self._stop.is_set():
                return
            if library.is_cloud_only(p):
                cloud += 1
            else:
                files.append(p)
        failed = set(self.state.get("failed", []))
        todo = []
        for p in files:
            if self._stop.is_set():
                return
            try:
                sha = self.ctx.dup.known_sha(p) or reader.file_hash(p)
            except OSError:
                continue
            if sha in failed or self.ctx.docmeta.get(sha):
                continue
            todo.append((p, sha))
        already = len(files) - len(todo)
        self.state.update(phase="running", total=len(files), done=already, cloud_only=cloud)
        self._save()
        self._emit()
        today = _dt.date.today()
        persons = [x for x in (self.ctx.settings().persons or []) if x]
        errors = 0
        for n, (p, sha) in enumerate(todo, 1):
            if not self._wait_idle():
                return
            if not p.exists():
                self.state["done"] = self.state.get("done", 0) + 1
                continue
            try:
                text = _text_for(p, sha)
            except Exception:
                log.info("Nicht lesbar: %s", p)
                text = ""
            if len(text.strip()) < 20:
                failed.add(sha)
                self.state["skipped"] = self.state.get("skipped", 0) + 1
            else:
                try:
                    info = tasks.inspect(self.ctx.ai, text=text, name=p.name, persons=persons)
                    errors = 0
                except Exception:
                    errors += 1
                    log.exception("Bestandsprüfung: KI-Antwort für %s unbrauchbar", p)
                    if errors >= 3:
                        raise RuntimeError("Die KI antwortet gerade nicht. Ich versuche es beim nächsten Start "
                                           "erneut – du kannst die Prüfung auch selbst fortsetzen.")
                    self.state["done"] = self.state.get("done", 0) + 1
                    self._emit()
                    continue
                # alte Fristen aus dem Bestand interessieren nicht mehr
                dls = [d for d in info["deadlines"] if _dt.date.fromisoformat(d["date"]) >= today - _dt.timedelta(days=7)]
                self.ctx.docmeta.record(sha, str(p), folder=_rel_folder(root, p), summary=info["summary"],
                                        doc_date=info["doc_date"], deadlines=dls, person=info["person"],
                                        steuer=info["steuer"])
                self.ctx.on_inspected(p, sha, text)
                if info["steuer"]:
                    self.state["found_tax"] = self.state.get("found_tax", 0) + 1
                if dls:
                    self.state["found_deadlines"] = self.state.get("found_deadlines", 0) + len(dls)
                    self.ctx.bus.emit("deadlines", {})
            self.state["done"] = self.state.get("done", 0) + 1
            self.state["failed"] = sorted(failed)
            if n % 5 == 0:
                self._save()
            self._emit()
        self.state.update(active=False, phase="done", finished=time.time(), failed=sorted(failed))
        self._save()
        self.ctx.bus.emit("deadlines", {})


class Refiner(_Background):
    FILE = "feinschliff.json"
    EVENT = "refine"

    def candidates(self) -> list[dict]:
        root = self.ctx.library_root()
        if not root:
            return []
        counts = library.folder_counts(root, skip_photos=True)
        out = [{"folder": f, "display": naming.display_folder(f), "count": c}
               for f, c in counts.items()
               if f and c >= REFINE_MIN_DOCS and len(f.split("/")) < 3]
        out.sort(key=lambda x: -x["count"])
        return out[:20]

    def status(self) -> dict:
        s = self.state
        return {"phase": s.get("phase", "idle"), "folder": s.get("folder", ""),
                "display": naming.display_folder(s.get("folder", "")), "done": s.get("done", 0),
                "total": s.get("total", 0), "error": s.get("error", ""), "running": self.running(),
                "moved": s.get("moved", 0), "failed": s.get("failed", 0), "group": s.get("group", ""),
                "cloud_only": s.get("cloud_only", 0)}

    def proposal(self) -> dict:
        s = self.state
        if s.get("phase") != "review":
            return {}
        docs = s.get("docs", [])
        return {"folder": s["folder"], "display": naming.display_folder(s["folder"]),
                "subfolders": [{**sub, "docs": [{"i": i, "name": d["name"]} for i, d in enumerate(docs)
                                                if d.get("target") == sub["name"]]}
                               for sub in s.get("subfolders", [])],
                "stay": [{"i": i, "name": d["name"]} for i, d in enumerate(docs) if not d.get("target")],
                "cloud_only": s.get("cloud_only", 0)}

    def start(self, folder: str) -> dict:
        root = self.ctx.library_root()
        if not root:
            raise ValueError("Bitte zuerst eine Ablage einrichten.")
        if self.running():
            raise ValueError("Ich bin gerade schon mit einem Ordner beschäftigt.")
        if self.ctx.reorg_active():
            raise ValueError("Bitte schließe erst die laufende Neuordnung ab.")
        folder = naming.clean_folder(folder)
        if not folder or len(folder.split("/")) >= 3 or not naming.folder_to_path(root, folder).is_dir():
            raise ValueError("Diesen Ordner kann ich nicht weiter unterteilen.")
        self.state = {"phase": "reading", "folder": folder, "library": str(root), "done": 0, "total": 0}
        self._save()
        self._launch(self._analyze)
        self._emit()
        return self.status()

    def cancel(self) -> dict:
        if self.state.get("phase") == "moving":
            raise ValueError("Ich verschiebe gerade – bitte einen Moment warten.")
        self.stop()
        self.state = {"phase": "idle"}
        self._save()
        self._emit()
        return self.status()

    def _analyze(self) -> None:
        root = Path(self.state["library"])
        folder = self.state["folder"]
        base = naming.folder_to_path(root, folder)
        files, cloud = [], 0
        for p in sorted(base.iterdir(), key=lambda x: x.name.lower()):
            if not p.is_file() or not reader.is_supported(p) or library.is_photo(p):
                continue
            if library.is_cloud_only(p):
                cloud += 1
                continue
            files.append(p)
        self.state.update(total=len(files), cloud_only=cloud)
        docs = []
        for i, p in enumerate(files, 1):
            if self._stop.is_set():
                return
            try:
                sha = self.ctx.dup.known_sha(p) or reader.file_hash(p)
                text = _text_for(p, sha)
            except Exception:
                sha, text = "", ""
            meta = self.ctx.docmeta.get(sha) if sha else None
            docs.append({"path": str(p), "name": p.name, "sha": sha,
                         "text": ((meta or {}).get("summary", "") + " " + text[:600]).strip()})
            self.state["done"] = i
            if i % 3 == 0 or i == len(files):
                self._emit()
        if len(docs) < 6:
            raise ValueError("In diesem Ordner liegen zu wenige lesbare Dokumente.")
        self.state.update(phase="thinking", done=0, total=len(docs))
        self._emit()

        def progress(d, t):
            self.state.update(done=d, total=t)
            self._emit()
        result = tasks.refine_folder(self.ctx.ai, folder=folder, docs=docs, on_progress=progress,
                                     should_stop=self._stop.is_set)
        if self._stop.is_set():
            return
        if not result["subfolders"]:
            raise ValueError("Mir ist keine sinnvolle Unterteilung eingefallen – der Ordner ist wohl schon gut so.")
        for d, target in zip(docs, result["assign"]):
            d["target"] = target
            d["text"] = d["text"][:400]
        self.state.update(phase="review", subfolders=result["subfolders"], docs=docs)
        self._save()

    def apply(self, subfolders: list[dict], moves: dict[str, str]) -> dict:
        """subfolders: [{"name" (alt), "new_name"}]; moves: {"<index>": "<alter Name>" | ""} (Abweichungen)."""
        s = self.state
        if s.get("phase") != "review" or self.running():
            raise ValueError("Es gibt gerade keinen Vorschlag zum Übernehmen.")
        root = Path(s["library"])
        if self.ctx.library_root() != root:
            raise ValueError("Die Ablage wurde inzwischen geändert.")
        rename = {}
        for sub in subfolders or []:
            old = sub.get("name", "")
            new = _clean(sub.get("new_name", old))
            rename[old] = new  # leer = Unterordner verwerfen
        docs = s.get("docs", [])
        for k, v in (moves or {}).items():
            try:
                docs[int(k)]["target"] = v or ""
            except (ValueError, IndexError):
                pass
        plan = []
        for d in docs:
            t = d.get("target") or ""
            t = rename.get(t, t) if t else ""
            if t:
                plan.append((d, t))
        if not plan:
            raise ValueError("Es ist kein Dokument zum Verschieben ausgewählt.")
        s.update(phase="moving", done=0, total=len(plan), moved=0, failed=0)
        self._save()
        self._launch(lambda: self._move(root, plan))
        self._emit()
        return self.status()

    def _move(self, root: Path, plan: list[tuple[dict, str]]) -> None:
        s = self.state
        folder = s["folder"]
        gid = self.ctx.history.start_group("feinschliff", library=str(root), folder=folder)
        s["group"] = gid
        moved = failed = 0
        for d, sub in plan:
            src = Path(d["path"])
            target_folder = naming.clean_folder(f"{folder}/{sub}")
            try:
                if not src.is_file():
                    failed += 1
                    continue
                if d.get("sha") and reader.file_hash(src) != d["sha"]:
                    failed += 1  # inzwischen verändert → lieber liegen lassen
                    continue
                target_dir = naming.folder_to_path(root, target_folder)
                created = [str(p) for p in library.missing_parents(target_dir / "x")]
                dst = naming.unique_path(naming.fit_path(target_dir / src.name))
                dst = library.move_file(src, dst)
                entry = self.ctx.history.add("reorg", str(src), str(dst), target_folder, group=gid,
                                             dst_sha=d.get("sha", ""), dst_size=dst.stat().st_size,
                                             created_dirs=created)
                self.ctx.on_moved(src, dst, d.get("sha", ""), d.get("text", ""), target_folder, entry["id"])
                moved += 1
            except Exception:
                log.exception("Feinschliff: %s konnte nicht verschoben werden", src)
                failed += 1
            s.update(done=moved + failed, moved=moved, failed=failed)
            if (moved + failed) % 5 == 0:
                self._save()
            self._emit()
        try:
            self.ctx.dup.save()
        except Exception:
            log.exception("Index der Doppelten konnte nicht gespeichert werden")
        self.ctx.history.update_group(gid, done=True, moved=moved)
        s.update(phase="done", moved=moved, failed=failed)
        s.pop("docs", None)
        self._save()

    def resume_after_restart(self) -> None:
        """Lesen/Nachdenken wird neu gestartet; ein unterbrochenes Verschieben gilt als beendet."""
        ph = self.state.get("phase")
        if ph in ("reading", "thinking"):
            self._launch(self._analyze)
        elif ph == "moving":
            gid = self.state.get("group")
            if gid:
                self.ctx.history.update_group(gid, done=True)
            self.state.update(phase="done")
            self.state.pop("docs", None)
            self._save()


def _clean(name: str) -> str:
    return naming.clean_part(str(name or "").replace("/", " ").replace("\\", " ").strip(), "")[:50]
