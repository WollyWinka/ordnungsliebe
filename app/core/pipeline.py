"""Die Warteschlange: neue Scans erkennen, analysieren, Vorschläge bereitstellen, einsortieren."""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
import uuid
from pathlib import Path

import pymupdf

from .. import paths
from ..ai import tasks
from ..ai.llm import LLMError
from ..docs import ocr, preview, reader
from ..docs.ocr import OcrUnavailable
from ..store import textsim
from . import library, naming

log = logging.getLogger(__name__)

POLL_SECONDS = float(__import__("os").environ.get("ORDNUNGSLIEBE_POLL", "4"))
PRIO_USER = 0      # Nutzer wartet (z. B. nach „Passt nicht“)
PRIO_NORMAL = 5


def _trash(path: Path) -> Path:
    """Nie endgültig löschen: Dateien kommen 30 Tage in den Ordnungsliebe-Papierkorb."""
    return library.quarantine(path)


class Pipeline:
    def __init__(self, settings_store, ai, memory, history, dupindex, schemes, bus):
        self.settings_store = settings_store
        self.ai = ai
        self.memory = memory
        self.history = history
        self.dup = dupindex
        self.schemes = schemes
        self.bus = bus
        self.items: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._jobs: "queue.PriorityQueue[tuple[int, int, str, str]]" = queue.PriorityQueue()
        self._seq = itertools.count()
        self._skip_seq = itertools.count(1)
        self._stop = threading.Event()
        self._seen_sizes: dict[str, tuple[int, float]] = {}
        self._split_parts: set[str] = set()
        self._ignored_inbox: set[str] = set()
        self.reorg_folders: list[str] = []          # erlaubte Ordner während einer Neuordnung
        self.reorg_group: str = ""
        self._worker = threading.Thread(target=self._work, name="analyse", daemon=True)
        self._poller = threading.Thread(target=self._poll, name="scan-ordner", daemon=True)

    # --- Start/Stopp --------------------------------------------------------------
    def start(self) -> None:
        self._worker.start()
        self._poller.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def settings(self):
        return self.settings_store.get()

    @property
    def library_root(self) -> Path:
        return Path(self.settings.library_dir)

    # --- Ereignisse ---------------------------------------------------------------
    def _changed(self) -> None:
        self.bus.emit("queue", self.overview())

    # --- Scan-Ordner beobachten ---------------------------------------------------
    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan_inbox()
            except Exception:
                log.exception("Fehler beim Prüfen des Scan-Ordners")
            self._stop.wait(POLL_SECONDS)

    def _scan_inbox(self) -> None:
        s = self.settings
        if not s.setup_done or not s.inbox_dir:
            return
        inbox = Path(s.inbox_dir)
        if not inbox.is_dir():
            return
        with self._lock:
            known = {it["src"] for it in self.items.values()}
        now = time.monotonic()
        for p in sorted(inbox.iterdir(), key=lambda x: x.name.lower()):
            sp = str(p)
            if sp in known or sp in self._ignored_inbox or not reader.is_supported(p):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            prev = self._seen_sizes.get(sp)
            if prev is None or prev[0] != size:
                self._seen_sizes[sp] = (size, now)
                continue
            if now - prev[1] < 2 or size == 0:
                continue
            try:  # Scanner noch am Schreiben? Dann ist die Datei meist gesperrt.
                with open(p, "rb+"):
                    pass
            except OSError:
                continue
            self._seen_sizes.pop(sp, None)
            self.add_file(p, origin="inbox")

    # --- Einträge anlegen ---------------------------------------------------------
    def add_file(self, path: Path, origin: str, **extra) -> str:
        item_id = uuid.uuid4().hex[:12]
        item = {"id": item_id, "origin": origin, "src": str(path), "name": path.name,
                "kind": reader.file_kind(path), "status": "waiting", "stage": "doc",
                "suggestion": None, "excluded": [], "page_count": 1, "error": "",
                "skip": 0, "created": time.time(), "split_done": str(path) in self._split_parts,
                "dup_ignored": False, **extra}
        with self._lock:
            self.items[item_id] = item
        self._jobs.put((PRIO_NORMAL, next(self._seq), item_id, "analyze"))
        self._changed()
        return item_id

    # --- Arbeiter -----------------------------------------------------------------
    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                _, _, item_id, job = self._jobs.get(timeout=1)
            except queue.Empty:
                continue
            with self._lock:
                item = self.items.get(item_id)
            if item is None:
                continue
            item["status"] = "analyzing"
            self._changed()
            try:
                if job == "analyze":
                    self._analyze(item)
                elif job == "classify":
                    self._classify(item)
                item["error"] = ""
            except OcrUnavailable as exc:
                item.update(status="error", error=str(exc))
            except LLMError as exc:
                item.update(status="error", error=str(exc))
            except FileNotFoundError:
                with self._lock:
                    self.items.pop(item_id, None)
            except Exception as exc:
                log.exception("Analyse fehlgeschlagen: %s", item.get("src"))
                item.update(status="error", error="Das Dokument konnte nicht gelesen werden.")
            self._changed()
            if item.get("origin") == "reorg":
                self.bus.emit("reorg_item_done", None)

    def _analyze(self, item: dict) -> None:
        src = Path(item["src"])
        if not src.exists():
            raise FileNotFoundError(src)
        sha = item.get("sha") or reader.file_hash(src)
        item["sha"] = sha
        if item["origin"] == "inbox" and not item["dup_ignored"]:
            hit = self.dup.find(sha, [], exclude=src)
            if hit:
                self._mark_duplicate(item, hit)
                return
        doc = reader.read_document(src, sha=sha)
        item["page_count"] = doc.page_count
        item["text"] = doc.text
        item["page_texts"] = doc.page_texts
        item["fingerprint"] = textsim.fingerprint(doc.text)
        if item["origin"] == "inbox" and not item["dup_ignored"]:
            hit = self.dup.find(sha, item["fingerprint"], exclude=src)
            if hit:
                self._mark_duplicate(item, hit)
                return
        if (item["origin"] == "inbox" and not item["split_done"] and doc.kind in ("pdf", "image")
                and 2 <= doc.page_count <= 30):
            starts = tasks.detect_starts(self.ai, doc.page_texts)
            if len(starts) > 1:
                item.update(stage="stack", starts=starts, status="ready")
                return
        self._classify(item)

    def _mark_duplicate(self, item: dict, hit: dict) -> None:
        other = Path(hit["path"])
        folder = ""
        try:
            folder = "/".join(other.parent.relative_to(self.library_root).parts)
        except ValueError:
            pass
        try:
            when = time.strftime("%d.%m.%Y", time.localtime(other.stat().st_mtime))
        except OSError:
            when = ""
        item.update(stage="duplicate", status="ready",
                    dup={"path": str(other), "name": other.name, "folder": folder,
                         "folder_display": naming.display_folder(folder), "date": when,
                         "reason": hit.get("reason", "")})

    def _folder_info(self, folders: list[str], with_files: bool) -> dict[str, dict]:
        root = self.library_root
        schemes = self.schemes.for_library(root)
        info = {}
        for f in folders:
            entry = {"scheme": schemes.get(f, {}).get("scheme", "")}
            files = library.folder_examples(root, f) if with_files else []
            if not files and schemes.get(f, {}).get("example"):
                files = [schemes[f]["example"]]
            entry["files"] = files
            info[f] = entry
        return info

    def _classify(self, item: dict) -> None:
        if "text" not in item:
            doc = reader.read_document(Path(item["src"]), sha=item.get("sha"))
            item.update(text=doc.text, page_count=doc.page_count, page_texts=doc.page_texts)
        if item["origin"] == "reorg":
            folders, allow_new = list(self.reorg_folders), False
        else:
            folders, allow_new = library.list_folders(self.library_root), True
        suggestion = tasks.classify(
            self.ai, text=item["text"], original=Path(item["src"]), kind=item["kind"],
            page_count=item["page_count"], folders=folders,
            folder_info=self._folder_info(folders, with_files=item["origin"] == "inbox"),
            examples=self.memory.similar(item["text"]), excluded=item["excluded"], allow_new=allow_new)
        suggestion["folder_display"] = naming.display_folder(suggestion["folder"])
        suggestion["alt_display"] = naming.display_folder(suggestion["alt_folder"])
        item.update(stage="doc", suggestion=suggestion, status="ready")
        if item["origin"] == "reorg":
            self._auto_keep_if_unchanged(item)

    def _auto_keep_if_unchanged(self, item: dict) -> None:
        src = Path(item["src"])
        try:
            current = "/".join(src.parent.relative_to(self.library_root).parts)
        except ValueError:
            return
        s = item["suggestion"]
        if s["folder"] == current and s["filename"] == src.name:
            with self._lock:
                self.items.pop(item["id"], None)
            self.memory.add(item.get("text", ""), current, src.name, ref="", original_name=src.name)

    # --- Abfragen für die Oberfläche ---------------------------------------------
    def _public(self, item: dict, with_text: bool = False) -> dict:
        out = {k: v for k, v in item.items() if k not in ("text", "page_texts", "fingerprint")}
        if with_text:
            out["text_excerpt"] = (item.get("text") or "")[:1500]
        return out

    def _in_batch(self, item: dict) -> bool:
        return (item["status"] == "ready" and item["stage"] == "doc" and item["suggestion"] is not None
                and not item["suggestion"]["is_new_folder"] and not item["excluded"]
                and item["suggestion"]["confidence"] >= self.settings.batch_threshold
                and not item.get("batch_declined"))

    def overview(self, origin: str | None = None) -> dict:
        with self._lock:
            items = [i for i in self.items.values() if origin is None or i["origin"] == origin]
        batch = sum(1 for i in items if self._in_batch(i))
        ready = sum(1 for i in items if i["status"] in ("ready", "error"))
        working = sum(1 for i in items if i["status"] in ("waiting", "analyzing"))
        by_origin = {}
        for o in ("inbox", "reorg"):
            sub = [i for i in self.items.values() if i["origin"] == o]
            by_origin[o] = {"total": len(sub),
                            "working": sum(1 for i in sub if i["status"] in ("waiting", "analyzing")),
                            "batch": sum(1 for i in sub if self._in_batch(i)),
                            "ready": sum(1 for i in sub if i["status"] in ("ready", "error"))}
        return {"total": len(items), "batch": batch, "single": ready - batch, "working": working,
                "by_origin": by_origin}

    def batch_items(self, origin: str) -> list[dict]:
        with self._lock:
            items = [i for i in self.items.values() if i["origin"] == origin and self._in_batch(i)]
        items.sort(key=lambda i: i["created"])
        return [self._public(i) for i in items]

    def next_single(self, origin: str) -> dict | None:
        with self._lock:
            cands = [i for i in self.items.values() if i["origin"] == origin
                     and i["status"] in ("ready", "error") and not self._in_batch(i)]
        if not cands:
            return None
        cands.sort(key=lambda i: (i["skip"], i["created"]))
        return self._public(cands[0], with_text=True)

    def get(self, item_id: str) -> dict:
        with self._lock:
            item = self.items.get(item_id)
        if item is None:
            raise KeyError("Dieses Dokument ist nicht mehr in der Warteschlange.")
        return item

    def preview(self, item_id: str, page: int = 0) -> dict:
        return preview.render_page(Path(self.get(item_id)["src"]), page)

    def thumbs(self, item_id: str) -> list[str]:
        return preview.render_thumbs(Path(self.get(item_id)["src"]))

    # --- Aktionen -----------------------------------------------------------------
    def _claim(self, item_id: str) -> dict:
        """Sperrt einen Eintrag für das Einsortieren (verhindert doppeltes Bestätigen)."""
        with self._lock:
            item = self.items.get(item_id)
            if item is None:
                raise KeyError("Dieses Dokument ist nicht mehr in der Warteschlange.")
            if item["status"] != "ready" or item["stage"] != "doc":
                raise ValueError("Das Dokument wird gerade noch bearbeitet. Bitte einen Moment warten.")
            item["status"] = "moving"
            return item

    def confirm(self, item_id: str, folder: str | None = None, filename: str | None = None) -> dict:
        item = self._claim(item_id)
        try:
            result = self._do_confirm(item, folder, filename)
        except Exception:
            with self._lock:
                if item_id in self.items:
                    item["status"] = "ready"
            self._changed()
            raise
        with self._lock:
            self.items.pop(item_id, None)
        self._changed()
        return result

    def _do_confirm(self, item: dict, folder: str | None, filename: str | None) -> dict:
        item_id = item["id"]
        s = item["suggestion"] or {}
        if folder is None and not s.get("folder"):
            raise ValueError("Bitte zuerst einen Ordner wählen.")
        folder = naming.clean_folder(folder if folder is not None else s.get("folder", ""))
        src = Path(item["src"])
        if not src.exists():
            raise FileNotFoundError("Die Datei ist nicht mehr im Scan-Ordner.")
        root = self.library_root
        target_dir = naming.folder_to_path(root, folder)
        stem = filename if filename else s.get("filename", src.name)

        if item["origin"] == "reorg":
            target = target_dir / naming.clean_filename(stem, src.suffix)
            created = [str(p) for p in library.missing_parents(target)]
            if target.resolve() == src.resolve():
                dst = src
            else:
                dst = library.move_file(src, target)
                self.dup.move(src, dst)
            entry = self.history.add("reorg", str(src), str(dst), folder, group=item.get("group", ""),
                                     dst_sha=item.get("sha", ""), dst_size=dst.stat().st_size,
                                     created_dirs=created)
        else:
            converted = None
            if item["kind"] in ("pdf", "image"):
                tmp = paths.cache_dir() / "umwandlung" / f"{item_id}.pdf"
                try:
                    tmp.unlink(missing_ok=True)
                    if ocr.make_searchable_pdf(src, tmp):
                        converted = tmp
                except Exception:
                    log.exception("Durchsuchbares PDF konnte nicht erstellt werden")
                    converted = None
            # Endung passend zum tatsächlichen Inhalt (bei misslungener Umwandlung bleibt das Bild ein Bild)
            suffix = ".pdf" if converted is not None or item["kind"] == "pdf" else src.suffix.lower()
            target = target_dir / naming.clean_filename(stem, suffix)
            created = [str(p) for p in library.missing_parents(target)]
            original_store = None
            if converted is not None:
                dst = library.move_file(converted, target)
                try:
                    original_store = library.move_file(
                        src, paths.local_dir() / "Originale" / f"{item_id}{src.suffix.lower()}")
                except Exception:
                    # Original lässt sich nicht weglegen (z. B. gesperrt): umgewandelte Kopie zurücknehmen
                    try:
                        dst.unlink()
                    except OSError:
                        pass
                    raise RuntimeError("Die Datei ist gerade von einem anderen Programm geöffnet. "
                                       "Bitte schließe es und versuche es noch einmal.")
            else:
                dst = library.move_file(src, target)
            dst_sha = reader.file_hash(dst)
            entry = self.history.add("move", str(src), str(dst), folder,
                                     original=str(original_store) if original_store else "",
                                     dst_sha=dst_sha, dst_size=dst.stat().st_size, created_dirs=created)
            try:
                self.dup.add_file(dst, dst_sha, item.get("fingerprint"))
                self.dup.save()
            except OSError:
                pass
        self.memory.add(item.get("text", ""), folder, dst.name, ref=entry["id"], original_name=src.name)
        if s and s.get("is_new_folder") and s.get("folder") == folder:
            self.schemes.set_one(root, folder, "JJJJ-MM Dokumentart", dst.stem)
        return {"dst": str(dst), "folder_display": naming.display_folder(folder), "name": dst.name}

    def confirm_batch(self, item_ids: list[str]) -> int:
        done = 0
        for iid in item_ids:
            try:
                self.confirm(iid)
                done += 1
            except Exception:
                log.exception("Sammel-Bestätigung fehlgeschlagen für %s", iid)
        return done

    def decline_from_batch(self, item_ids: list[str]) -> None:
        for iid in item_ids:
            with self._lock:
                item = self.items.get(iid)
            if item:
                item["batch_declined"] = True
        self._changed()

    def reject(self, item_id: str) -> None:
        item = self.get(item_id)
        if item["status"] not in ("ready", "error"):
            raise ValueError("Das Dokument wird gerade bearbeitet.")
        s = item.get("suggestion") or {}
        if s.get("folder") and s["folder"] not in item["excluded"]:
            item["excluded"].append(s["folder"])
        item.update(status="waiting", suggestion=None)
        self._jobs.put((PRIO_USER, next(self._seq), item_id, "classify"))
        self._changed()

    def skip(self, item_id: str) -> None:
        self.get(item_id)["skip"] = next(self._skip_seq)
        self._changed()

    def retry(self, item_id: str) -> None:
        item = self.get(item_id)
        item.update(status="waiting", error="")
        self._jobs.put((PRIO_USER, next(self._seq), item_id, "analyze"))
        self._changed()

    def keep_duplicate(self, item_id: str) -> None:
        item = self.get(item_id)
        item.update(dup_ignored=True, stage="doc", status="waiting")
        item.pop("dup", None)
        self._jobs.put((PRIO_USER, next(self._seq), item_id, "analyze"))
        self._changed()

    def trash_duplicate(self, item_id: str) -> None:
        with self._lock:
            item = self.items.get(item_id)
            if item is None or item["status"] != "ready" or item["stage"] != "duplicate":
                raise ValueError("Das Dokument wird gerade bearbeitet.")
            item["status"] = "moving"
        src = Path(item["src"])
        try:
            kept = _trash(src)
        except Exception:
            item["status"] = "ready"
            raise
        self.history.add("trash", str(src), str(kept), "", reason="doppelt",
                         dst_sha=item.get("sha", ""), dst_size=kept.stat().st_size)
        with self._lock:
            self.items.pop(item_id, None)
        self._changed()

    def not_a_stack(self, item_id: str) -> None:
        item = self.get(item_id)
        item.update(split_done=True, stage="doc", status="waiting")
        self._jobs.put((PRIO_USER, next(self._seq), item_id, "classify"))
        self._changed()

    def split(self, item_id: str, starts: list[int]) -> int:
        """Teilt eine Scan-Datei an den Startseiten auf. Die Teile landen im Scan-Ordner."""
        with self._lock:
            item = self.items.get(item_id)
            if item is None or item["status"] != "ready" or item["stage"] != "stack":
                raise ValueError("Das Dokument wird gerade bearbeitet.")
            item["status"] = "moving"
        try:
            src = Path(item["src"])
            doc = ocr.image_to_pdf(src) if item["kind"] == "image" else pymupdf.open(str(src))
            n = doc.page_count
            starts = sorted({s for s in starts if 1 <= s <= n} | {1})
            bounds = starts + [n + 1]
            work = paths.cache_dir() / "trennen" / item_id
            work.mkdir(parents=True, exist_ok=True)
            built = []
            for k in range(len(starts)):
                part = pymupdf.open()
                part.insert_pdf(doc, from_page=bounds[k] - 1, to_page=bounds[k + 1] - 2)
                tmp = work / f"{src.stem} – Teil {k + 1}.pdf"
                part.save(str(tmp), garbage=3, deflate=True)
                part.close()
                built.append(tmp)
            doc.close()
            # Prüfen: Zusammen müssen die Teile genau alle Seiten enthalten
            total = 0
            for b in built:
                with pymupdf.open(str(b)) as d:
                    total += d.page_count
            if total != n:
                raise RuntimeError("Beim Aufteilen ist etwas schiefgegangen. Die Datei bleibt unverändert.")
        except Exception:
            item["status"] = "ready"
            raise
        inbox = src.parent
        parts = []
        with self._lock:
            for b in built:
                dst = library.move_file(b, inbox / b.name)
                self._split_parts.add(str(dst))
                parts.append(dst)
            kept = _trash(src)
            self.history.add("split", str(src), str(kept), "", parts=[str(p) for p in parts])
            self.items.pop(item_id, None)
            for p in parts:
                self.add_file(p, origin="inbox")
        self._changed()
        return len(parts)

    def remove_origin(self, origin: str) -> None:
        with self._lock:
            for iid in [i for i, it in self.items.items() if it["origin"] == origin]:
                self.items.pop(iid, None)
        self._changed()

    def pending_count(self, origin: str) -> int:
        with self._lock:
            return sum(1 for i in self.items.values() if i["origin"] == origin)
