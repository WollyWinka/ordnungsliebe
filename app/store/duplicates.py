"""Erkennt Doppelte: identische Dateien (Prüfsumme) und erneut gescannte Dokumente (Textähnlichkeit)."""

from __future__ import annotations

import threading
from pathlib import Path

from .. import jsonfile, paths
from . import textsim

SIMILAR_THRESHOLD = 0.9


class DuplicateIndex:
    def __init__(self, path: Path | None = None):
        self.path = path or (paths.local_dir() / "dubletten.json")
        self._lock = threading.Lock()
        data = jsonfile.load(self.path, {"files": {}, "texts": {}})
        # files: pfad -> {sha, size, mtime}; texts: pfad -> fingerprint
        self.files: dict[str, dict] = data.get("files", {})
        self.texts: dict[str, list[int]] = data.get("texts", {})

    def save(self) -> None:
        with self._lock:
            jsonfile.save(self.path, {"files": self.files, "texts": self.texts})

    def known_sha(self, path: Path) -> str | None:
        rec = self.files.get(str(path))
        if not rec:
            return None
        try:
            st = path.stat()
        except OSError:
            return None
        if rec.get("size") == st.st_size and abs(rec.get("mtime", 0) - st.st_mtime) < 2:
            return rec["sha"]
        return None

    def add_file(self, path: Path, sha: str, fingerprint: list[int] | None = None) -> None:
        try:
            st = path.stat()
        except OSError:
            return
        with self._lock:
            self.files[str(path)] = {"sha": sha, "size": st.st_size, "mtime": st.st_mtime}
            if fingerprint:
                self.texts[str(path)] = fingerprint

    def move(self, old: Path, new: Path) -> None:
        with self._lock:
            if str(old) in self.files:
                rec = self.files.pop(str(old))
                try:
                    st = new.stat()
                    rec["mtime"] = st.st_mtime
                    rec["size"] = st.st_size
                except OSError:
                    pass
                self.files[str(new)] = rec
            if str(old) in self.texts:
                self.texts[str(new)] = self.texts.pop(str(old))

    def remove(self, path: Path) -> None:
        with self._lock:
            self.files.pop(str(path), None)
            self.texts.pop(str(path), None)

    def prune_missing(self) -> None:
        with self._lock:
            for p in [p for p in self.files if not Path(p).exists()]:
                self.files.pop(p, None)
                self.texts.pop(p, None)

    def find(self, sha: str, fingerprint: list[int], exclude: Path | None = None) -> dict | None:
        """Gibt {path, reason} des ersten Doppelten zurück oder None."""
        ex = str(exclude) if exclude else None
        for p, rec in list(self.files.items()):
            if p != ex and rec.get("sha") == sha and self.known_sha(Path(p)) == sha:
                return {"path": p, "reason": "identisch"}
        if fingerprint and len(fingerprint) >= 20:
            best, best_p = 0.0, None
            for p, fp in list(self.texts.items()):
                if p == ex:
                    continue
                s = textsim.fingerprint_similarity(fingerprint, fp)
                if s > best:
                    best, best_p = s, p
            if best_p and best >= SIMILAR_THRESHOLD and Path(best_p).exists():
                return {"path": best_p, "reason": "gleicher Inhalt", "score": round(best, 2)}
        return None
