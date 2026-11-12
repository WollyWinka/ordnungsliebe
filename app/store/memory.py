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

    def add(self, text: str, folder: str, filename: str, ref: str = "", original_name: str = "",
            ai_folder: str = "", ai_reason: str = "", hint: str = "") -> dict:
        """Speichert eine bestätigte Entscheidung.

        ai_folder/ai_reason: was die KI vorgeschlagen und wie sie es begründet hatte.
        Weicht folder davon ab, ist es eine Korrektur – die zählt bei ähnlichen Dokumenten besonders.
        """
        snippet = (text or "").strip()[:SNIPPET]
        corrected = bool(ai_folder) and ai_folder != folder
        entry = {"text": snippet, "folder": folder, "filename": filename, "ref": ref, "orig": original_name,
                 "ts": time.time(), "vec": textsim.vector(snippet), "ai_folder": ai_folder,
                 "ai_reason": (ai_reason or "")[:300], "corrected": corrected, "hint": (hint or "")[:300]}
        with self._lock:
            self.entries.append(entry)
            self.entries = self.entries[-MAX_ENTRIES:]
            self._save()
        return entry

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

    def similar(self, text: str, k: int = 4, min_score: float = 0.12) -> list[dict]:
        """Ähnlichste frühere Entscheidungen. Korrekturen und neuere Fälle werden bevorzugt."""
        vec = textsim.vector(text[:3000])
        scored = []
        for e in self.entries:
            s = textsim.cosine(vec, e.get("vec") or textsim.vector(e["text"]))
            if s >= min_score:
                bonus = 0.08 if e.get("corrected") else 0.0
                scored.append((s + bonus, s, e))
        scored.sort(key=lambda x: (x[0], x[2].get("ts", 0)), reverse=True)
        scored = [(s, e) for _, s, e in scored]
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
