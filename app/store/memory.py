"""Lerngedächtnis: bestätigte Entscheidungen als Beispiele für künftige Vorschläge."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from .. import jsonfile, paths
from . import textsim

MAX_ENTRIES = 1500
SNIPPET = 600


class Memory:
    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "gedaechtnis.json")
        self._lock = threading.Lock()
        self.entries: list[dict] = jsonfile.load(self.path, [])

    def _save(self) -> None:
        jsonfile.save(self.path, self.entries[-MAX_ENTRIES:])

    def add(self, text: str, folder: str, filename: str, ref: str = "", original_name: str = "") -> None:
        snippet = (text or "").strip()[:SNIPPET]
        with self._lock:
            self.entries.append({"text": snippet, "folder": folder, "filename": filename,
                                 "ref": ref, "orig": original_name, "ts": time.time(),
                                 "vec": textsim.vector(snippet)})
            self.entries = self.entries[-MAX_ENTRIES:]
            self._save()

    def remove_ref(self, ref: str) -> None:
        if not ref:
            return
        with self._lock:
            self.entries = [e for e in self.entries if e.get("ref") != ref]
            self._save()

    def rename_folder(self, old: str, new: str) -> None:
        with self._lock:
            for e in self.entries:
                if e["folder"] == old or e["folder"].startswith(old + "/"):
                    e["folder"] = new + e["folder"][len(old):]
            self._save()

    def similar(self, text: str, k: int = 3, min_score: float = 0.12) -> list[dict]:
        vec = textsim.vector(text[:3000])
        scored = []
        for e in self.entries:
            s = textsim.cosine(vec, e.get("vec") or textsim.vector(e["text"]))
            if s >= min_score:
                scored.append((s, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        out, seen = [], set()
        for s, e in scored:
            key = (e["folder"], e["filename"])
            if key in seen:
                continue
            seen.add(key)
            out.append({**{k: v for k, v in e.items() if k != "vec"}, "score": round(s, 3)})
            if len(out) >= k:
                break
        return out

    def count(self) -> int:
        return len(self.entries)

    def reset(self) -> None:
        with self._lock:
            self.entries = []
            self._save()
