"""Verlauf aller Aktionen – Grundlage für „Rückgängig“."""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from .. import jsonfile, paths

MAX_ENTRIES = 5000


class History:
    """Einträge: {id, ts, action, src, dst, name, folder, group, undone, info}.

    action: "move" (Einsortieren aus dem Scan-Eingang), "reorg" (Verschieben bei der Neuordnung),
            "trash" (Doppelte in den Papierkorb), "split" (Stapel aufgeteilt).
    group:  Kennung einer Neuordnung, damit sie gesamt rückgängig gemacht werden kann.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "verlauf.json")
        self._lock = threading.Lock()
        data = jsonfile.load(self.path, {"entries": [], "groups": {}})
        self.entries: list[dict] = data.get("entries", [])
        self.groups: dict[str, dict] = data.get("groups", {})

    def _save(self) -> None:
        jsonfile.save(self.path, {"entries": self.entries[-MAX_ENTRIES:], "groups": self.groups})

    def add(self, action: str, src: str, dst: str, folder: str = "", group: str = "", **info) -> dict:
        entry = {"id": uuid.uuid4().hex[:12], "ts": time.time(), "action": action, "src": src,
                 "dst": dst, "name": Path(dst or src).name, "folder": folder, "group": group,
                 "undone": False, "info": info}
        with self._lock:
            self.entries.append(entry)
            self._save()
        return entry

    def get(self, entry_id: str) -> dict | None:
        return next((e for e in self.entries if e["id"] == entry_id), None)

    def mark_undone(self, entry_id: str) -> None:
        with self._lock:
            for e in self.entries:
                if e["id"] == entry_id:
                    e["undone"] = True
            self._save()

    def update(self, entry_id: str, **changes) -> None:
        with self._lock:
            for e in self.entries:
                if e["id"] == entry_id:
                    e.update(changes)
            self._save()

    def start_group(self, kind: str, **info) -> str:
        gid = uuid.uuid4().hex[:10]
        with self._lock:
            self.groups[gid] = {"id": gid, "kind": kind, "ts": time.time(), "done": False,
                                "undone": False, **info}
            self._save()
        return gid

    def update_group(self, gid: str, **changes) -> None:
        with self._lock:
            if gid in self.groups:
                self.groups[gid].update(changes)
                self._save()

    def group_entries(self, gid: str) -> list[dict]:
        return [e for e in self.entries if e.get("group") == gid]

    def recent(self, limit: int = 200) -> list[dict]:
        return list(reversed(self.entries[-limit:]))
