"""Verlauf aller Aktionen – Grundlage für „Rückgängig“.

Gespeichert als Zeilen-Datei (JSON Lines): Jede Änderung wird angehängt, nichts wird gekürzt.
Beim Laden gewinnt je Eintrag die letzte Zeile. Gelegentlich wird die Datei verdichtet.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from .. import jsonfile, paths


class History:
    """Einträge: {id, ts, action, src, dst, name, folder, group, undone, info}.

    action: "move" (Einsortieren aus dem Scan-Eingang), "reorg" (Verschieben bei der Neuordnung),
            "trash" (zur Seite gelegt), "split" (Stapel aufgeteilt).
    group:  Kennung einer Neuordnung, damit sie gesamt rückgängig gemacht werden kann.
    info:   u. a. dst_sha/dst_size (Prüfung vor dem Rückgängigmachen), created_dirs.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "verlauf.jsonl")
        self.groups_path = self.path.with_name("verlauf-gruppen.json")
        self._lock = threading.RLock()
        self.entries: list[dict] = []
        self._index: dict[str, dict] = {}
        self._lines = 0
        self._load()
        self.groups: dict[str, dict] = jsonfile.load(self.groups_path, {})

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    self._lines += 1
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # halbe Zeile nach Stromausfall
                    if e.get("id") in self._index:
                        self._index[e["id"]].clear()
                        self._index[e["id"]].update(e)
                    else:
                        self._index[e["id"]] = e
                        self.entries.append(e)
        except FileNotFoundError:
            pass

    def _append(self, entry: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._lines += 1
        if self._lines > 2 * len(self.entries) + 500:
            self._compact()

    def _compact(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for e in self.entries:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        self._lines = len(self.entries)

    def _save_groups(self) -> None:
        jsonfile.save(self.groups_path, self.groups)

    def add(self, action: str, src: str, dst: str, folder: str = "", group: str = "", **info) -> dict:
        entry = {"id": uuid.uuid4().hex[:12], "ts": time.time(), "action": action, "src": src,
                 "dst": dst, "name": Path(dst or src).name, "folder": folder, "group": group,
                 "undone": False, "info": info}
        with self._lock:
            self.entries.append(entry)
            self._index[entry["id"]] = entry
            self._append(entry)
        return entry

    def get(self, entry_id: str) -> dict | None:
        return self._index.get(entry_id)

    def update(self, entry_id: str, **changes) -> None:
        with self._lock:
            e = self._index.get(entry_id)
            if e is None:
                return
            e.update(changes)
            self._append(e)

    def mark_undone(self, entry_id: str) -> None:
        self.update(entry_id, undone=True, undone_ts=time.time())

    def start_group(self, kind: str, **info) -> str:
        gid = uuid.uuid4().hex[:10]
        with self._lock:
            self.groups[gid] = {"id": gid, "kind": kind, "ts": time.time(), "done": False,
                                "undone": False, **info}
            self._save_groups()
        return gid

    def update_group(self, gid: str, **changes) -> None:
        with self._lock:
            if gid in self.groups:
                self.groups[gid].update(changes)
                self._save_groups()

    def group_entries(self, gid: str) -> list[dict]:
        return [e for e in self.entries if e.get("group") == gid]

    def recent(self, limit: int = 200) -> list[dict]:
        return list(reversed(self.entries[-limit:]))
