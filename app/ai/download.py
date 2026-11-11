"""Modell-Download mit Fortschritt, Pause und Fortsetzen nach Abbruch."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

import requests

log = logging.getLogger(__name__)

CHUNK = 1 << 20


class Downloader:
    """Lädt eine Datei in Teilen herunter. Unterbrochene Downloads werden fortgesetzt."""

    def __init__(self, url: str, target: Path, on_progress: Callable[[dict], None]):
        self.url = url
        self.target = target
        self.part = target.with_suffix(target.suffix + ".part")
        self.on_progress = on_progress
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = "idle"      # idle | running | paused | done | error
        self.error = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            self._pause.clear()
            return
        self._pause.clear()
        self._thread = threading.Thread(target=self._run, name="modell-download", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._pause.set()

    def _report(self, done: int, total: int, speed: float) -> None:
        remaining = (total - done) / speed if speed > 0 and total else None
        self.on_progress({"state": self.state, "done": done, "total": total,
                          "percent": round(done * 100 / total, 1) if total else 0,
                          "seconds_left": round(remaining) if remaining else None,
                          "error": self.error})

    def _run(self) -> None:
        self.state = "running"
        self.error = ""
        retries = 0
        while True:
            try:
                self._download_once()
                return
            except _Paused:
                self.state = "paused"
                self._report(self._have(), self._total or 0, 0)
                return
            except Exception as exc:  # Netzwerkfehler → einige Male neu versuchen
                retries += 1
                log.warning("Download-Fehler (%s), Versuch %s", exc, retries)
                if retries > 8:
                    self.state = "error"
                    self.error = "Die Verbindung ist abgebrochen. Prüfe das Internet und versuche es erneut."
                    self._report(self._have(), self._total or 0, 0)
                    return
                time.sleep(min(30, 2 ** retries))

    _total: int | None = None

    def _have(self) -> int:
        return self.part.stat().st_size if self.part.exists() else 0

    def _download_once(self) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        have = self._have()
        headers = {"Range": f"bytes={have}-"} if have else {}
        with requests.get(self.url, headers=headers, stream=True, timeout=(15, 60),
                          allow_redirects=True) as resp:
            if resp.status_code == 416:  # schon vollständig
                self._finish()
                return
            resp.raise_for_status()
            if have and resp.status_code != 206:
                have = 0  # Server kann nicht fortsetzen → neu beginnen
            length = int(resp.headers.get("Content-Length", 0))
            self._total = have + length if length else None
            mode = "ab" if have else "wb"
            last_t, last_b = time.monotonic(), have
            speed = 0.0
            with open(self.part, mode) as fh:
                done = have
                for chunk in resp.iter_content(CHUNK):
                    if self._pause.is_set():
                        raise _Paused()
                    fh.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_t >= 0.5:
                        inst = (done - last_b) / (now - last_t)
                        speed = inst if speed == 0 else speed * 0.8 + inst * 0.2
                        last_t, last_b = now, done
                        self._report(done, self._total or 0, speed)
        if self._total and self._have() < self._total:
            raise IOError("Download unvollständig")
        self._finish()

    def _finish(self) -> None:
        self.part.replace(self.target)
        self.state = "done"
        size = self.target.stat().st_size
        self._report(size, size, 0)


class _Paused(Exception):
    pass
