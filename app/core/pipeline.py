"""Die Warteschlange: neue Scans erkennen, analysieren, Vorschläge bereitstellen, einsortieren."""

from __future__ import annotations

import itertools
import json
import logging
import queue
import threading
import time
import uuid
from pathlib import Path

import pymupdf

from .. import jsonfile, paths
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


def _locked(p: Path) -> bool:
    """Ist die Datei gerade von einem anderen Programm zum Schreiben geöffnet?

    Schreibgeschützte Dateien lassen sich nicht mit „rb+“ öffnen – dann reicht der Lesetest.
    """
    try:
        with open(p, "rb+"):
            return False
    except PermissionError:
        try:
            import stat as _stat
            if not (p.stat().st_mode & _stat.S_IWRITE):
                with open(p, "rb"):
                    return False
        except OSError:
            return True
        return True
    except OSError:
        return True


class Pipeline:
    def __init__(self, settings_store, ai, memory, history, dupindex, schemes, bus, hints=None, ignored=None,
                 docmeta=None):
        from ..store.docmeta import DocMeta
        from ..store.hints import Hints, Ignored
        self.docmeta = docmeta or DocMeta()
        self.hints = hints or Hints()
        self.ignored = ignored or Ignored()
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
        self._part_info: dict[str, dict] = {}       # Teile aus Mails: Hinweis und Herkunft
        self._ignored_inbox: set[str] = set()
        self.reorg_folders: list[str] = []          # erlaubte Ordner während einer Neuordnung
        self.reorg_group: str = ""
        self.reorg_kept: set[str] = set()           # Neuordnung: Dokumente, die schon richtig liegen
        self.reorg_target: Path | None = None        # Neuordnung in neuen Ordner: Ziel (Kopien statt Verschieben)
        self.on_reorg_folder_added = None            # Rückruf: neuer Ordner während der Neuordnung
        self.on_filed = None                         # Rückruf: Dokument wurde abgelegt (für die Suche)
        self._worker = threading.Thread(target=self._work, name="analyse", daemon=True)
        self._poller = threading.Thread(target=self._poll, name="scan-ordner", daemon=True)
        self._queue_file = paths.local_dir() / "warteschlange.json"
        self._dirty = False
        self._restore()

    # --- Start/Stopp --------------------------------------------------------------
    def start(self) -> None:
        self._worker.start()
        self._poller.start()

    def stop(self) -> None:
        self._stop.set()
        self._persist()

    # --- Zwischenspeichern ----------------------------------------------------------
    _SKIP_KEYS = ("text", "page_texts", "fingerprint", "vec")

    def _persist(self) -> None:
        """Warteschlange samt fertiger Vorschläge sichern – übersteht Neustart und Update."""
        data = None
        for _ in range(5):  # Einträge können sich gerade ändern → kurze Wiederholung
            try:
                with self._lock:
                    items = list(self.items.values())
                    data = [json.loads(json.dumps({k: v for k, v in it.items() if k not in self._SKIP_KEYS},
                                                  default=str)) for it in items]
                    self._dirty = False
                break
            except RuntimeError:
                time.sleep(0.05)
        if data is None:
            self._dirty = True
            return
        for rec in list(data):
            try:
                st = Path(rec["src"]).stat()
                rec["_size"], rec["_mtime"] = st.st_size, st.st_mtime
            except OSError:
                data.remove(rec)
        try:
            jsonfile.save(self._queue_file, {"v": 1, "items": data, "kept": sorted(self.reorg_kept)})
        except Exception:
            log.warning("Warteschlange konnte nicht gespeichert werden")

    def _restore(self) -> None:
        raw = jsonfile.load(self._queue_file, {})
        self.reorg_kept = set(raw.get("kept", []))
        saved = raw.get("items", [])
        restored = 0
        for rec in saved:
            src = Path(rec.get("src", ""))
            try:
                st = src.stat()
            except OSError:
                continue
            if st.st_size != rec.get("_size") or abs(st.st_mtime - rec.get("_mtime", 0)) > 2:
                continue  # Datei hat sich verändert → wird ohnehin neu erkannt
            item = {k: v for k, v in rec.items() if not k.startswith("_")}
            if item.get("sha"):
                item["text"] = reader.cached_text(item["sha"]) or ""
            if item.get("status") == "moving":
                item["status"] = "ready"
            needs_job = item.get("status") in ("waiting", "analyzing") or (
                item.get("status") == "ready" and item.get("stage") == "doc" and not item.get("suggestion"))
            if needs_job:
                item["status"] = "waiting"
            self.items[item["id"]] = item
            if needs_job:
                job = "classify" if item.get("text") else "analyze"
                self._jobs.put((PRIO_NORMAL, next(self._seq), item["id"], job))
            restored += 1
        if restored:
            log.info("%s Einträge der Warteschlange wiederhergestellt", restored)

    @property
    def settings(self):
        return self.settings_store.get()

    @property
    def library_root(self) -> Path:
        return Path(self.settings.library_dir)

    # --- Ereignisse ---------------------------------------------------------------
    def _changed(self) -> None:
        self._dirty = True
        try:
            self.bus.emit("queue", self.overview())
        except Exception:
            log.exception("Statusmeldung fehlgeschlagen")

    # --- Scan-Ordner beobachten ---------------------------------------------------
    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan_inbox()
            except Exception:
                log.exception("Fehler beim Prüfen des Scan-Ordners")
            if self._dirty:
                try:
                    self._persist()
                except Exception:
                    log.exception("Warteschlange konnte nicht gespeichert werden")
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
            if sp in known or sp in self._ignored_inbox or not reader.is_supported(p) or self.ignored.has_path(sp):
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
            if _locked(p):  # Scanner noch am Schreiben? Dann ist die Datei meist gesperrt.
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
                "dup_ignored": False, **self._part_info.pop(str(path), {}), **extra}
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
        if self.ignored.has_sha(sha):  # als „kein Dokument“ markiert → still übergehen
            self._ignored_inbox.add(str(src))
            with self._lock:
                self.items.pop(item["id"], None)
            return
        if item["origin"] == "inbox" and not item["dup_ignored"]:
            hit = self.dup.find(sha, [], exclude=src)
            if hit:
                self._mark_duplicate(item, hit)
                return
        if item["origin"] == "inbox" and item.get("kind") == "email" and not item.get("mail_checked"):
            from ..docs import mailparts
            try:
                plan = mailparts.analyze(src)
            except Exception:
                log.exception("Mail konnte nicht ausgewertet werden – wird als Ganzes behandelt")
                plan = None
            if plan is not None:
                item["mail"] = plan.summary()
                if plan.mode == "ask" or item.get("mail_ask"):
                    item.update(stage="mail", status="ready")
                    return
                self._expand_mail(item, plan, "attachments" if plan.mode == "attachments" else "mail")
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

    def _folder_info(self, folders: list[str], with_files: bool, root: Path | None = None) -> dict[str, dict]:
        root = root or self.library_root
        schemes = self.schemes.for_library(root)
        info = {}
        for f in folders:
            entry = {"scheme": schemes.get(f, {}).get("scheme", ""), "desc": schemes.get(f, {}).get("desc", "")}
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
            folders, allow_new, below = list(self.reorg_folders), True, True
        else:
            folders, allow_new, below = library.list_folders(self.library_root), True, False
        st = self.settings
        persons = [p for p in (st.persons or []) if p]
        if persons and st.person_mode == "unterordner":
            # Personen-Unterordner setzt das Programm selbst – die KI wählt den Sachordner
            names = {p.lower() for p in persons}
            folders = [f for f in folders if f.split("/")[-1].lower() not in names]
        suggestion = tasks.classify(
            self.ai, text=item["text"], original=Path(item["src"]), kind=item["kind"],
            page_count=item["page_count"], folders=folders,
            folder_info=self._folder_info(folders, with_files=item["origin"] == "inbox",
                                          root=self.reorg_target if item["origin"] == "reorg" else None),
            examples=self.memory.similar(item["text"]), excluded=item["excluded"], allow_new=allow_new,
            user_hints=self.hints.relevant(item["text"]), doc_hint=item.get("hint", ""),
            folder_counts=self.folder_counts(item["origin"]), new_only_below=below, persons=persons)
        if persons:
            suggestion["folder"], suggestion["filename"] = naming.apply_person(
                suggestion["folder"], suggestion["filename"], suggestion.get("person", ""), persons, st.person_mode)
        suggestion["folder_display"] = naming.display_folder(suggestion["folder"])
        suggestion["alt_display"] = naming.display_folder(suggestion["alt_folder"])
        item.update(stage="doc", suggestion=suggestion, status="ready")
        if item["origin"] == "reorg":
            self._auto_keep_if_unchanged(item)

    _counts_cache: tuple[float, dict] = (0.0, {})

    def folder_counts(self, origin: str) -> dict[str, int]:
        """Wie viele Dokumente liegen (oder landen) je Ordner? Hilft der KI, Unterordner vorzuschlagen."""
        if origin == "reorg":
            counts: dict[str, int] = {}
            for e in self.history.group_entries(self.reorg_group):
                if not e.get("undone"):
                    counts[e.get("folder", "")] = counts.get(e.get("folder", ""), 0) + 1
            with self._lock:
                for it in self.items.values():
                    s = it.get("suggestion")
                    if it["origin"] == "reorg" and s:
                        counts[s["folder"]] = counts.get(s["folder"], 0) + 1
            return counts
        ts, cached = self._counts_cache
        if time.time() - ts > 120:
            try:
                cached = library.folder_counts(self.library_root, skip_photos=False) if self.library_root.is_dir() else {}
            except Exception:
                cached = {}
            self._counts_cache = (time.time(), cached)
        return cached

    def _auto_keep_if_unchanged(self, item: dict) -> None:
        if self.reorg_target is not None:
            return  # beim Kopieren in einen neuen Ordner muss jedes Dokument hinüber
        src = Path(item["src"])
        try:
            current = "/".join(src.parent.relative_to(self.library_root).parts)
        except ValueError:
            return
        s = item["suggestion"]
        if s["folder"] == current and s["filename"] == src.name:
            with self._lock:
                self.items.pop(item["id"], None)
                self.reorg_kept.add(str(src))
                self._dirty = True
            self.memory.add(item.get("text", ""), current, src.name, ref="", original_name=src.name)
            self._record_meta(item, src, current, s)

    # --- Abfragen für die Oberfläche ---------------------------------------------
    def _public(self, item: dict, with_text: bool = False) -> dict:
        out = {k: v for k, v in item.items() if k not in ("text", "page_texts", "fingerprint", "vec")}
        if with_text:
            out["text_excerpt"] = (item.get("text") or "")[:1500]
        return out

    def _in_batch(self, item: dict) -> bool:
        return (item["status"] == "ready" and item["stage"] == "doc" and item["suggestion"] is not None
                and not item["suggestion"]["is_new_folder"] and not item["excluded"]
                and item["suggestion"]["confidence"] >= self.settings.batch_threshold
                and not item.get("batch_declined"))

    def busy(self) -> bool:
        with self._lock:
            return any(i["status"] in ("waiting", "analyzing") for i in self.items.values())

    def overview(self, origin: str | None = None) -> dict:
        with self._lock:
            items = [i for i in self.items.values() if origin is None or i["origin"] == origin]
        batch = sum(1 for i in items if self._in_batch(i))
        ready = sum(1 for i in items if i["status"] in ("ready", "error"))
        working = sum(1 for i in items if i["status"] in ("waiting", "analyzing"))
        by_origin = {}
        with self._lock:
            all_items = list(self.items.values())
        for o in ("inbox", "reorg"):
            sub = [i for i in all_items if i["origin"] == o]
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

    def confirm(self, item_id: str, folder: str | None = None, filename: str | None = None,
                extra: dict | None = None) -> dict:
        item = self._claim(item_id)
        try:
            if extra and item.get("suggestion"):
                s = item["suggestion"]
                if isinstance(extra.get("deadlines"), list):
                    s["deadlines"] = tasks.clean_deadlines(extra["deadlines"])
                if "person" in extra:
                    s["person"] = str(extra.get("person") or "")
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
        copy_mode = item["origin"] == "reorg" and self.reorg_target is not None
        root = self.reorg_target if copy_mode else self.library_root
        target_dir = naming.folder_to_path(root, folder)
        stem = filename if filename else s.get("filename", src.name)

        if copy_mode:
            if folder and folder not in self.reorg_folders:
                self.reorg_folders.append(folder)
                if self.on_reorg_folder_added:
                    try:
                        self.on_reorg_folder_added(folder)
                    except Exception:
                        log.exception("Neuer Ordner konnte nicht in die Struktur übernommen werden")
            target = target_dir / naming.clean_filename(stem, src.suffix)
            created = [str(p) for p in library.missing_parents(target)]
            dst = library.copy_file(src, target, sha=item.get("sha", ""))
            entry = self.history.add("reorg", str(src), str(dst), folder, group=item.get("group", ""),
                                     dst_sha=item.get("sha", "") or reader.file_hash(dst),
                                     dst_size=dst.stat().st_size, created_dirs=created, copy=True)
        elif item["origin"] == "reorg":
            if folder and folder not in self.reorg_folders:
                self.reorg_folders.append(folder)
                if self.on_reorg_folder_added:
                    try:
                        self.on_reorg_folder_added(folder)
                    except Exception:
                        log.exception("Neuer Ordner konnte nicht in die Struktur übernommen werden")
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
            enh_report: dict = {}
            if item["kind"] in ("pdf", "image"):
                tmp = paths.cache_dir() / "umwandlung" / f"{item_id}.pdf"
                try:
                    tmp.unlink(missing_ok=True)
                    if ocr.make_searchable_pdf(src, tmp, enhance=self.settings.scan_enhance,
                                               page_texts=item.get("page_texts"), report=enh_report):
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
                                     cleaned={k: v for k, v in enh_report.items() if v} if converted else {},
                                     dst_sha=dst_sha, dst_size=dst.stat().st_size, created_dirs=created)
            try:
                self.dup.add_file(dst, dst_sha, item.get("fingerprint"))
                self.dup.save()
            except OSError:
                pass
        persons = self.settings.persons or []
        mem_folder, mem_name = naming.strip_person(folder, dst.name, persons)
        ai_folder = naming.strip_person(s.get("folder", ""), "", persons)[0] if s.get("folder") else ""
        if self.settings.person_mode != "unterordner":  # Personen-Ordner hat dann der Nutzer selbst angelegt
            mem_folder, ai_folder = folder, s.get("folder", "")
        mem = self.memory.add(item.get("text", ""), mem_folder, mem_name, ref=entry["id"], original_name=src.name,
                              ai_folder=ai_folder, ai_reason=s.get("reason", ""),
                              hint=item.get("hint", ""))
        if not copy_mode:  # Kopien zählen erst, wenn die neue Ablage übernommen wird
            self._record_meta(item, dst, folder, s, sha=entry.get("info", {}).get("dst_sha") or "", entry_id=entry["id"])
        self.history.update(entry["id"], info={**entry.get("info", {}), "ai_folder": s.get("folder", ""),
                                               "reason": s.get("reason", ""), "corrected": mem["corrected"]})
        if s and s.get("is_new_folder") and s.get("folder") == folder and not self.schemes.for_library(root).get(folder):
            self.schemes.set_one(root, folder, "JJJJ-MM Dokumentart", dst.stem)
        rechecked = 0
        if mem["corrected"]:
            rechecked = self.recheck_similar(item.get("text", ""), exclude=item_id, origin=item["origin"],
                                             keep_if_folder=folder)
        cleaned = (entry.get("info") or {}).get("cleaned") or {}
        return {"dst": str(dst), "folder_display": naming.display_folder(folder), "name": dst.name,
                "rechecked": rechecked, "removed_pages": len(cleaned.get("removed", []))}

    def _record_meta(self, item: dict, path: Path, folder: str, s: dict, sha: str = "", entry_id: str = "") -> None:
        try:
            sha = sha or item.get("sha") or reader.file_hash(path)
            self.docmeta.record(sha, str(path), folder=folder, summary=s.get("summary", ""),
                                doc_date=s.get("doc_date", ""), deadlines=s.get("deadlines") or [],
                                person=s.get("person", ""), steuer=bool(s.get("steuer")), entry_id=entry_id)
            if s.get("deadlines"):
                self.bus.emit("deadlines", {})
        except Exception:
            log.exception("Dokumentdaten konnten nicht gespeichert werden")
            return
        if self.on_filed:
            try:
                self.on_filed(Path(item["src"]), path, sha, item.get("text", ""), s)
            except Exception:
                log.exception("Suchindex konnte nicht aktualisiert werden")

    def recheck_similar(self, text: str, exclude: str = "", origin: str | None = None,
                        keep_if_folder: str = "", min_score: float = 0.3) -> int:
        """Lässt fertige Vorschläge ähnlicher Dokumente neu berechnen (nach Korrektur oder Hinweis)."""
        vec = textsim.vector((text or "")[:3000])
        if not vec:
            return 0
        hits = []
        with self._lock:
            for it in self.items.values():
                if (it["id"] == exclude or it["status"] != "ready" or it["stage"] != "doc"
                        or (origin and it["origin"] != origin) or not it.get("suggestion")):
                    continue
                if keep_if_folder and it["suggestion"].get("folder") == keep_if_folder:
                    continue
                if "vec" not in it:
                    it["vec"] = textsim.vector((it.get("text") or "")[:3000])
                if textsim.cosine(vec, it["vec"]) >= min_score:
                    hits.append(it)
            for it in hits:
                it.update(status="waiting", suggestion=None, batch_declined=False)
                self._jobs.put((PRIO_USER, next(self._seq), it["id"], "classify"))
        if hits:
            self._changed()
        return len(hits)

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

    def give_hint(self, item_id: str, text: str, remember: bool = True) -> None:
        """Neuer Vorschlag mit Hinweis des Nutzers; der Hinweis wird für ähnliche Dokumente gemerkt."""
        text = (text or "").strip()
        if not text:
            raise ValueError("Bitte einen Hinweis eingeben.")
        item = self.get(item_id)
        if item["status"] not in ("ready", "error"):
            raise ValueError("Das Dokument wird gerade bearbeitet.")
        if remember:
            self.hints.add(text, "aehnlich", snippet=item.get("text", ""), source=item["name"])
        item["hint"] = text
        item["excluded"] = []  # der Hinweis darf auch einen vorher abgelehnten Ordner begründen
        item.update(status="waiting", suggestion=None)
        self._jobs.put((PRIO_USER, next(self._seq), item_id, "classify"))
        if remember:
            self.recheck_similar(item.get("text", ""), exclude=item_id, origin=item["origin"])
        self._changed()

    def mark_not_document(self, item_id: str, reason: str = "foto") -> None:
        """Datei bleibt liegen und wird nie wieder vorgeschlagen."""
        with self._lock:
            item = self.items.get(item_id)
            if item is None or item["status"] not in ("ready", "error"):
                raise ValueError("Das Dokument wird gerade bearbeitet.")
            item["status"] = "moving"
        src = Path(item["src"])
        sha = item.get("sha") or (reader.file_hash(src) if src.exists() else "")
        rec = self.ignored.add(sha, str(src), reason)
        self._ignored_inbox.add(str(src))
        self.history.add("ignore", str(src), str(src), "", ignore_id=rec["id"], reason=reason)
        with self._lock:
            self.items.pop(item_id, None)
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
            try:
                for b in built:
                    dst = library.move_file(b, naming.unique_path(inbox / b.name))
                    self._split_parts.add(str(dst))
                    parts.append(dst)
                kept = _trash(src)
            except Exception:
                # z. B. Original gerade von Virenscanner/Vorschau gesperrt → Teile wieder entfernen
                for p in parts:
                    try:
                        p.unlink()
                    except OSError:
                        log.warning("Teil konnte nicht zurückgenommen werden: %s", p)
                    self._split_parts.discard(str(p))
                item["status"] = "ready"
                raise RuntimeError("Die Datei ist gerade von einem anderen Programm geöffnet. "
                                   "Bitte schließe es und versuche es noch einmal.")
            self.history.add("split", str(src), str(kept), "", parts=[str(p) for p in parts])
            self.items.pop(item_id, None)
            for p in parts:
                self.add_file(p, origin="inbox")
        self._changed()
        return len(parts)

    def forget_path(self, path: Path) -> None:
        """Eintrag zu einer Datei aus der Warteschlange nehmen (z. B. nach Rückgängig)."""
        with self._lock:
            for k in [k for k, i in self.items.items() if i["src"] == str(path) and i["status"] != "moving"]:
                self.items.pop(k, None)
            self._split_parts.discard(str(path))
            self._dirty = True
        self._changed()

    # --- Mails: Anhänge und/oder Mail als PDF ablegen -------------------------------
    def mail_choice(self, item_id: str, choice: str) -> int:
        """Antwort aus der Einzelprüfung: attachments | mail | both."""
        if choice not in ("attachments", "mail", "both"):
            raise ValueError("Unbekannte Auswahl.")
        with self._lock:
            item = self.items.get(item_id)
            if item is None or item["status"] != "ready" or item["stage"] != "mail":
                raise ValueError("Die Mail wird gerade bearbeitet.")
            item["status"] = "moving"
        from ..docs import mailparts
        try:
            plan = mailparts.analyze(Path(item["src"]))
            if choice == "attachments" and not plan.docs:
                raise ValueError("Diese Mail hat keinen Anhang, den ich ablegen könnte.")
        except Exception:
            item["status"] = "ready"
            raise
        return self._expand_mail(item, plan, choice, from_review=True)

    def _expand_mail(self, item: dict, plan, choice: str, from_review: bool = False) -> int:
        """Legt Anhänge und/oder die Mail als PDF als neue Dokumente in den Scan-Ordner; die Mail selbst
        kommt in den Ordnungsliebe-Papierkorb (30 Tage, über den Verlauf zurückholbar)."""
        from ..docs import mailparts
        src = Path(item["src"])
        work = paths.cache_dir() / "mails" / item["id"]
        work.mkdir(parents=True, exist_ok=True)
        built: list[Path] = []
        try:
            if choice in ("attachments", "both"):
                for k, att in enumerate(plan.docs, 1):
                    stem, suffix = Path(att.name).stem, Path(att.name).suffix.lower() or ".pdf"
                    tmp = naming.unique_path(work / naming.clean_filename(stem or f"Anhang {k}", suffix))
                    tmp.write_bytes(att.data)
                    if tmp.stat().st_size != att.size:
                        raise IOError("Anhang unvollständig gespeichert.")
                    built.append(tmp)
            if choice in ("mail", "both"):
                title = " ".join(x for x in (plan.date, plan.subject or "E-Mail") if x)
                built.append(mailparts.to_pdf(plan, naming.unique_path(work / naming.clean_filename(title, ".pdf"))))
            if not built:
                raise ValueError("In dieser Mail habe ich nichts zum Ablegen gefunden.")
        except Exception:
            item["status"] = "ready" if from_review else item.get("status", "ready")
            if not from_review:  # automatische Entscheidung ging schief → Nutzer fragen
                item.update(stage="mail", status="ready", mail_checked=False)
                return 0
            raise
        hint = plan.note
        inbox = src.parent
        parts = []
        with self._lock:
            try:
                for b in built:
                    dst = library.move_file(b, naming.unique_path(inbox / b.name))
                    self._split_parts.add(str(dst))
                    info = {"mail_from": plan.subject or plan.sender}
                    if hint:
                        info["hint"] = hint
                    self._part_info[str(dst)] = info
                    parts.append(dst)
                kept = _trash(src)
            except Exception:
                for p in parts:
                    try:
                        p.unlink()
                    except OSError:
                        log.warning("Teil konnte nicht zurückgenommen werden: %s", p)
                    self._split_parts.discard(str(p))
                    self._part_info.pop(str(p), None)
                item["status"] = "ready"
                if not from_review:
                    item.update(stage="mail")
                    return 0
                raise RuntimeError("Die Mail ist gerade von einem anderen Programm geöffnet. "
                                   "Bitte schließe es und versuche es noch einmal.")
            self.history.add("mail", str(src), str(kept), "", parts=[str(p) for p in parts],
                             subject=plan.subject, choice=choice)
            self.items.pop(item["id"], None)
            for p in parts:
                self.add_file(p, origin="inbox")
        self._changed()
        return len(parts)

    def remove_origin(self, origin: str) -> None:
        with self._lock:
            if origin == "reorg":
                self.reorg_kept.clear()
                self._dirty = True
            for iid in [i for i, it in self.items.items() if it["origin"] == origin]:
                self.items.pop(iid, None)
        self._changed()

    def pending_count(self, origin: str) -> int:
        with self._lock:
            return sum(1 for i in self.items.values() if i["origin"] == origin)
