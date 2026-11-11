"""Einrichtung: Hardware prüfen, Modell laden, Scan-Ordner finden, Ablage prüfen."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from .. import paths
from ..ai import download, hardware, models
from ..docs import reader
from . import library

log = logging.getLogger(__name__)


class ModelManager:
    def __init__(self, settings_store, bus):
        self.settings_store = settings_store
        self.bus = bus
        self.downloader: download.Downloader | None = None
        self.last: dict = {"state": "idle"}

    def status(self) -> dict:
        model_id = self.settings_store.get().model_id
        spec = models.get(model_id)
        st = dict(self.last)
        st.update(model_id=model_id, installed=bool(spec and spec.installed),
                  label=spec.label if spec else "", size_gb=spec.size_gb if spec else 0)
        return st

    def start(self, model_id: str) -> dict:
        spec = models.get(model_id)
        if spec is None:
            raise ValueError("Unbekanntes Modell")
        self.settings_store.update(model_id=model_id)
        if spec.installed:
            self.last = {"state": "done", "percent": 100}
            self.bus.emit("download", self.status())
            return self.status()
        if self.downloader and self.downloader.target == spec.path and self.downloader.state == "running":
            return self.status()

        def on_progress(p):
            self.last = p
            self.bus.emit("download", self.status())

        self.downloader = download.Downloader(spec.url, spec.path, on_progress)
        self.last = {"state": "running", "percent": 0}
        self.downloader.start()
        return self.status()

    def pause(self) -> None:
        if self.downloader:
            self.downloader.pause()

    def delete_other_models(self, keep: str) -> None:
        for mid, spec in models.MODELS.items():
            if mid != keep and spec.path.exists():
                try:
                    spec.path.unlink()
                except OSError:
                    pass


def hardware_report() -> dict:
    hw = hardware.detect()
    rec, gpu = hardware.recommend(hw)
    spec = models.MODELS[rec]
    return {
        "hardware": hw.to_dict(),
        "recommended": rec,
        "gpu": gpu,
        "models": [{"id": m.id, "label": m.label, "description": m.description, "size_gb": m.size_gb,
                    "installed": m.installed, "gpu_ok": hw.vram_gb >= m.min_vram_gb,
                    "ram_ok": hw.ram_gb >= m.min_ram_gb} for m in (models.MODELS[i] for i in models.ORDER)],
        "enough_disk": hw.free_disk_gb >= spec.size_gb + 1,
        "free_disk_gb": hw.free_disk_gb,
    }


# --- Scan-Ordner automatisch finden ------------------------------------------------------

def _candidate_dirs() -> list[Path]:
    home = Path.home()
    names = ["Documents", "Dokumente", "Pictures", "Bilder", "Downloads", "Desktop", "Scans", "Scan",
             "OneDrive", "iCloudDrive", "Dropbox"]
    dirs = [home / n for n in names if (home / n).is_dir()]
    for var in ("OneDrive", "OneDriveConsumer", "USERPROFILE"):
        v = os.environ.get(var)
        if v and Path(v).is_dir():
            dirs.append(Path(v))
    if paths.IS_WINDOWS:
        public = Path(os.environ.get("PUBLIC", "C:/Users/Public"))
        for n in ("Documents", "Pictures"):
            if (public / n).is_dir():
                dirs.append(public / n)
    seen, out = set(), []
    for d in dirs:
        if str(d) not in seen:
            seen.add(str(d))
            out.append(d)
    return out


def _snapshot(dirs: list[Path], max_depth: int = 3) -> dict[str, float]:
    snap = {}
    for root in dirs:
        base_depth = len(root.parts)
        for dirpath, dirnames, files in os.walk(root):
            if len(Path(dirpath).parts) - base_depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$")) and d not in ("AppData", "node_modules")]
            for f in files:
                p = Path(dirpath) / f
                if reader.file_kind(p) in ("pdf", "image"):
                    try:
                        snap[str(p)] = p.stat().st_mtime
                    except OSError:
                        pass
    return snap


class ScanFinder:
    """Wartet auf einen Test-Scan und meldet den Ordner, in dem er auftaucht."""

    def __init__(self, bus):
        self.bus = bus
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, timeout: int = 240) -> None:
        self.stop()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(timeout, self._stop), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self, timeout: int, stop: threading.Event) -> None:
        dirs = _candidate_dirs()
        self.bus.emit("scanfinder", {"state": "waiting"})
        before = _snapshot(dirs)
        started = time.time()
        while not stop.is_set() and time.time() - started < timeout:
            stop.wait(3)
            now = _snapshot(dirs)
            fresh = [p for p, m in now.items() if p not in before and m >= started - 5]
            if fresh:
                newest = max(fresh, key=lambda p: now[p])
                folder = str(Path(newest).parent)
                self.bus.emit("scanfinder", {"state": "found", "folder": folder,
                                             "display": pretty_path(folder), "file": Path(newest).name})
                return
        if not stop.is_set():
            self.bus.emit("scanfinder", {"state": "timeout"})


def pretty_path(p: str) -> str:
    """Pfad für Menschen: Benutzerordner weglassen, „›“ statt Backslash."""
    path = Path(p)
    home = Path.home()
    try:
        rel = path.relative_to(home)
        parts = list(rel.parts)
    except ValueError:
        parts = [x for x in path.parts if x not in ("\\", "/")]
    mapping = {"Documents": "Dokumente", "Pictures": "Bilder", "Desktop": "Desktop", "iCloudDrive": "iCloud Drive"}
    parts = [mapping.get(x, x).rstrip("\\/:") for x in parts]
    return " › ".join(parts[-3:]) if parts else str(path)


def inbox_info(folder: str) -> dict:
    p = Path(folder)
    if not p.is_dir():
        return {"ok": False, "count": 0}
    try:
        count = sum(1 for x in p.iterdir() if reader.is_supported(x))
    except OSError:
        count = 0
    return {"ok": True, "count": count, "display": pretty_path(folder)}


def library_info(folder: str) -> dict:
    p = Path(folder)
    if not p.is_dir():
        return {"ok": False}
    count = sum(1 for _ in library.walk_documents(p))
    cloud_count, cloud_bytes = library.cloud_only_files(p)
    return {"ok": True, "count": count, "cloud_only": cloud_count, "cloud_mb": round(cloud_bytes / 1e6),
            "display": pretty_path(folder)}
