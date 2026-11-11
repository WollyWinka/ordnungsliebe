"""Sicheres Lesen und Schreiben kleiner JSON-Dateien (atomar, mit Sperre)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


def _bak(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def load(path: Path, default: Any) -> Any:
    with _lock_for(path):
        for candidate in (path, _bak(path)):
            try:
                with open(candidate, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
                continue
        return default


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(path):
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            if path.exists():
                try:
                    shutil.copy2(path, _bak(path))
                except OSError:
                    pass
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
