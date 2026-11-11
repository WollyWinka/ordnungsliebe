"""Hinweise des Nutzers an die KI und Dateien, die nie mehr vorgeschlagen werden sollen."""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from .. import jsonfile, paths
from . import textsim

SIMILAR_MIN = 0.22     # ab dieser Ähnlichkeit gilt ein Hinweis auch für ein neues Dokument
MAX_SIMILAR = 3
MAX_RULES = 20


class Hints:
    """Einträge: {id, text, scope, snippet, vec, source, ts, used}

    scope "aehnlich": gilt für Dokumente, die dem ursprünglichen ähneln
    scope "alle":     Regel für alle Dokumente (z. B. selbst in den Einstellungen angelegt)
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "hinweise.json")
        self._lock = threading.Lock()
        self.items: list[dict] = jsonfile.load(self.path, [])

    def _save(self) -> None:
        jsonfile.save(self.path, self.items)

    def add(self, text: str, scope: str = "aehnlich", snippet: str = "", source: str = "") -> dict:
        text = (text or "").strip()[:500]
        if not text:
            raise ValueError("Bitte einen Hinweis eingeben.")
        snippet = (snippet or "")[:800]
        entry = {"id": uuid.uuid4().hex[:10], "text": text, "scope": scope, "snippet": snippet,
                 "vec": textsim.vector(snippet) if snippet else {}, "source": source, "ts": time.time(),
                 "used": 0}
        with self._lock:
            self.items.append(entry)
            self._save()
        return self.public(entry)

    def update(self, hint_id: str, text: str | None = None, scope: str | None = None) -> dict:
        with self._lock:
            for e in self.items:
                if e["id"] == hint_id:
                    if text is not None:
                        t = text.strip()[:500]
                        if not t:
                            raise ValueError("Ein Hinweis darf nicht leer sein.")
                        e["text"] = t
                    if scope in ("aehnlich", "alle"):
                        e["scope"] = scope
                    self._save()
                    return self.public(e)
        raise KeyError("Hinweis nicht gefunden.")

    def delete(self, hint_id: str) -> None:
        with self._lock:
            self.items = [e for e in self.items if e["id"] != hint_id]
            self._save()

    def relevant(self, text: str) -> list[str]:
        """Regeln für alle Dokumente plus die Hinweise zu ähnlichen Dokumenten."""
        rules = [e for e in self.items if e["scope"] == "alle"][-MAX_RULES:]
        vec = textsim.vector((text or "")[:3000])
        scored = []
        for e in self.items:
            if e["scope"] != "aehnlich" or not e.get("vec"):
                continue
            s = textsim.cosine(vec, e["vec"])
            if s >= SIMILAR_MIN:
                scored.append((s, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        chosen = rules + [e for _, e in scored[:MAX_SIMILAR]]
        out, seen = [], set()
        for e in chosen:
            if e["text"].lower() not in seen:
                seen.add(e["text"].lower())
                out.append(e["text"])
        return out

    @staticmethod
    def public(e: dict) -> dict:
        return {k: v for k, v in e.items() if k not in ("vec", "snippet")}

    def list(self) -> list[dict]:
        return [self.public(e) for e in reversed(self.items)]


class Ignored:
    """Dateien, die der Nutzer als „kein Dokument“ markiert hat (per Prüfsumme und Pfad)."""

    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "ignoriert.json")
        self._lock = threading.Lock()
        data = jsonfile.load(self.path, {"items": []})
        self.items: list[dict] = data.get("items", [])

    def _save(self) -> None:
        jsonfile.save(self.path, {"items": self.items})

    def add(self, sha: str, path: str, reason: str = "foto") -> dict:
        entry = {"id": uuid.uuid4().hex[:10], "sha": sha, "path": path, "reason": reason, "ts": time.time()}
        with self._lock:
            self.items.append(entry)
            self._save()
        return entry

    def remove(self, entry_id: str) -> dict | None:
        with self._lock:
            hit = next((e for e in self.items if e["id"] == entry_id), None)
            self.items = [e for e in self.items if e["id"] != entry_id]
            self._save()
        return hit

    def clear(self) -> int:
        with self._lock:
            n = len(self.items)
            self.items = []
            self._save()
        return n

    def has_path(self, path: str) -> bool:
        return any(e["path"] == path for e in self.items)

    def has_sha(self, sha: str) -> bool:
        return bool(sha) and any(e["sha"] == sha for e in self.items)

    def count(self) -> int:
        return len(self.items)
