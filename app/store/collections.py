"""Mappen: Zusammenstellungen von Dokumenten (z. B. für die Steuer oder einen Antrag).

Eine Mappe ist nur eine Liste von Verweisen – die Dokumente bleiben in ihren eigenen Ordnern.
Beim Export entstehen Kopien.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from .. import jsonfile, paths


class Collections:
    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "mappen.json")
        self._lock = threading.RLock()
        data = jsonfile.load(self.path, {})
        self.items: list[dict] = data.get("mappen", []) if isinstance(data, dict) else []

    def _save(self) -> None:
        jsonfile.save(self.path, {"mappen": self.items})

    def _get(self, cid: str) -> dict:
        for c in self.items:
            if c["id"] == cid:
                return c
        raise KeyError("Diese Mappe gibt es nicht mehr.")

    def list(self) -> list[dict]:
        with self._lock:
            return [{**c, "docs": [dict(d) for d in c["docs"]]} for c in self.items]

    def get(self, cid: str) -> dict:
        with self._lock:
            c = self._get(cid)
            return {**c, "docs": [dict(d) for d in c["docs"]]}

    def create(self, name: str) -> dict:
        name = " ".join((name or "").split())[:60]
        if not name:
            raise ValueError("Bitte gib der Mappe einen Namen.")
        with self._lock:
            c = {"id": uuid.uuid4().hex[:10], "name": name, "created": time.time(), "docs": []}
            self.items.append(c)
            self._save()
            return dict(c)

    def rename(self, cid: str, name: str) -> None:
        name = " ".join((name or "").split())[:60]
        if not name:
            raise ValueError("Bitte gib der Mappe einen Namen.")
        with self._lock:
            self._get(cid)["name"] = name
            self._save()

    def delete(self, cid: str) -> None:
        with self._lock:
            self._get(cid)
            self.items = [c for c in self.items if c["id"] != cid]
            self._save()

    def add(self, cid: str, path: str, sha: str = "") -> bool:
        with self._lock:
            c = self._get(cid)
            if any(d["path"] == path or (sha and d.get("sha") == sha) for d in c["docs"]):
                return False
            c["docs"].append({"path": path, "sha": sha, "added": time.time()})
            self._save()
            return True

    def remove(self, cid: str, path: str) -> None:
        with self._lock:
            c = self._get(cid)
            c["docs"] = [d for d in c["docs"] if d["path"] != path]
            self._save()

    def update_path(self, cid: str, old: str, new: str) -> None:
        with self._lock:
            for d in self._get(cid)["docs"]:
                if d["path"] == old:
                    d["path"] = new
            self._save()
