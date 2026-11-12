"""Volltextsuche über alle Dokumente der Ablage (SQLite FTS5, liegt lokal unter %LOCALAPPDATA%).

Der Index wird im Hintergrund aufgebaut: bereits gelesene Texte kommen aus dem Zwischenspeicher,
ungelesene Dokumente werden langsam nachgelesen, wenn sonst nichts zu tun ist. Cloud-Platzhalter
werden nicht heruntergeladen.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, sha TEXT, size INTEGER, mtime REAL, indexed REAL);
CREATE INDEX IF NOT EXISTS files_sha ON files(sha);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    path UNINDEXED, name, folder, extra, body, tokenize = 'unicode61 remove_diacritics 2');
"""

_TOKEN = re.compile(r"[\w\-]+", re.UNICODE)


def _query(text: str) -> str:
    """Nutzereingabe → FTS-Abfrage: alle Wörter müssen vorkommen, Wortanfänge genügen."""
    words = [w.strip("-") for w in _TOKEN.findall(text or "")]
    words = [w for w in words if w][:12]
    return " AND ".join(f'"{w}"*' for w in words)


class SearchIndex:
    def __init__(self, path: Path | None = None):
        self.path = path or (paths.local_dir() / "suche.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._db.commit()
        self.status = {"running": False, "done": 0, "total": 0, "pending": 0}

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- Schreiben ---------------------------------------------------------------------
    def put(self, path: Path, *, root: Path, sha: str, text: str, extra: str = "") -> None:
        try:
            st = path.stat()
            rel = path.parent.relative_to(root)
        except (OSError, ValueError):
            return
        folder = " › ".join(rel.parts)
        with self._lock:
            self._db.execute("DELETE FROM fts WHERE path = ?", (str(path),))
            self._db.execute("INSERT INTO fts (path, name, folder, extra, body) VALUES (?, ?, ?, ?, ?)",
                             (str(path), path.stem, folder, extra or "", text or ""))
            self._db.execute("INSERT OR REPLACE INTO files (path, sha, size, mtime, indexed) VALUES (?, ?, ?, ?, ?)",
                             (str(path), sha, st.st_size, st.st_mtime, time.time()))
            self._db.commit()

    def remove(self, path: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM fts WHERE path = ?", (path,))
            self._db.execute("DELETE FROM files WHERE path = ?", (path,))
            self._db.commit()

    def is_current(self, path: Path) -> bool:
        with self._lock:
            row = self._db.execute("SELECT size, mtime FROM files WHERE path = ?", (str(path),)).fetchone()
        if not row:
            return False
        try:
            st = path.stat()
        except OSError:
            return False
        return row[0] == st.st_size and abs(row[1] - st.st_mtime) < 2

    def paths(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._db.execute("SELECT path FROM files")]

    def path_for_sha(self, sha: str) -> str | None:
        with self._lock:
            for (p,) in self._db.execute("SELECT path FROM files WHERE sha = ?", (sha,)):
                if Path(p).exists():
                    return p
        return None

    def sha_for_path(self, path: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT sha FROM files WHERE path = ?", (path,)).fetchone()
        return row[0] if row else None

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    # --- Suchen ------------------------------------------------------------------------
    def search(self, text: str, limit: int = 60) -> list[dict]:
        q = _query(text)
        if not q:
            return []
        sql = ("SELECT path, folder, snippet(fts, 4, '\u0002', '\u0003', ' … ', 14), "
               "bm25(fts, 0, 6.0, 3.0, 4.0, 1.0) AS rank FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?")
        with self._lock:
            try:
                rows = self._db.execute(sql, (q, limit * 2)).fetchall()
            except sqlite3.OperationalError:
                log.warning("Suchanfrage ungültig: %r", q)
                return []
        out = []
        for path, folder, snip, _ in rows:
            p = Path(path)
            if not p.exists():
                continue
            out.append({"path": path, "name": p.name, "folder": folder, "snippet": snip or ""})
            if len(out) >= limit:
                break
        return out
