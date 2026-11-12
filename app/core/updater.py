"""Updates direkt im Programm: neue Version bei GitHub erkennen, laden, still installieren.

Das ist die einzige Stelle, an der Ordnungsliebe ins Internet geht – und nur, um die
Versionsnummer abzufragen bzw. die Installationsdatei zu laden. Dokumente bleiben lokal.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import requests

from .. import APP_VERSION, paths

log = logging.getLogger(__name__)

REPO = "WollyWinka/ordnungsliebe"
ASSET = "Ordnungsliebe-Setup.exe"
API = "https://api.github.com/repos/{repo}/releases/latest"


def _ver(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def _clean_notes(body: str) -> list[str]:
    lines = []
    for line in (body or "").splitlines():
        t = line.strip().lstrip("-*• ").strip()
        if not t or t.lower().startswith(("co-authored", "claude-session", "installation:", "beim ersten start",
                                          "danach läuft")):
            continue
        lines.append(t)
    return lines[:12]


class Updater:
    def __init__(self, settings_store, bus):
        self.settings_store = settings_store
        self.bus = bus
        self.info: dict = {"available": False}
        self.state = "idle"          # idle | downloading | ready | installing | error
        self.progress = 0.0
        self.file: Path | None = None
        self._lock = threading.Lock()

    def status(self) -> dict:
        return {**self.info, "state": self.state, "percent": round(self.progress, 1), "current": APP_VERSION,
                "can_install": bool(getattr(__import__("sys"), "frozen", False)) and paths.IS_WINDOWS}

    def check(self) -> dict:
        try:
            r = requests.get(API.format(repo=REPO), timeout=8,
                             headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.info("Update-Prüfung fehlgeschlagen: %s", exc)
            return {**self.status(), "error": "Keine Verbindung zum Update-Server."}
        latest = data.get("tag_name", "")
        assets = data.get("assets", [])
        asset = next((a for a in assets if a.get("name") == ASSET), None)
        sha_asset = next((a for a in assets if a.get("name") == ASSET + ".sha256"), None)
        digest = str((asset or {}).get("digest") or "")
        available = asset is not None and _ver(latest) > _ver(APP_VERSION)
        self.info = {"available": available, "version": latest.lstrip("v"), "url": asset["browser_download_url"] if asset else "",
                     "size": asset.get("size", 0) if asset else 0, "notes": _clean_notes(data.get("body", "")),
                     "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
                     "sha_url": sha_asset["browser_download_url"] if sha_asset else "",
                     "checked": time.time()}
        self.bus.emit("update", self.status())
        return self.status()

    def check_in_background(self, delay: float = 15) -> None:
        if not getattr(self.settings_store.get(), "auto_update", True) or os.environ.get("ORDNUNGSLIEBE_NO_UPDATE"):
            return

        def run():
            time.sleep(delay)
            self.check()
        threading.Thread(target=run, name="update-pruefung", daemon=True).start()

    def download(self) -> None:
        if not self.info.get("available") or not self.info.get("url"):
            raise ValueError("Es gibt gerade keine neue Version.")
        with self._lock:
            if self.state == "downloading":
                return
            self.state = "downloading"
            self.progress = 0.0
        threading.Thread(target=self._download, name="update-download", daemon=True).start()

    def _download(self) -> None:
        target_dir = paths.local_dir() / "update"
        target_dir.mkdir(parents=True, exist_ok=True)
        for old in target_dir.glob("*.exe"):
            try:
                old.unlink()
            except OSError:
                pass
        target = target_dir / f"Ordnungsliebe-Setup-{self.info['version']}.exe"
        part = target.with_suffix(".part")
        try:
            with requests.get(self.info["url"], stream=True, timeout=(15, 60)) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0)) or self.info.get("size", 0)
                done, last = 0, 0.0
                with open(part, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
                        done += len(chunk)
                        if total and time.monotonic() - last > 0.4:
                            last = time.monotonic()
                            self.progress = done * 100 / total
                            self.bus.emit("update", self.status())
            expected = self.info.get("size", 0)
            if expected and part.stat().st_size != expected:
                raise IOError("Die heruntergeladene Datei ist unvollständig.")
            want = self.info.get("sha256") or self._sha_from_asset()
            if not want:
                raise IOError("Die Prüfsumme der neuen Version fehlt.")
            h = hashlib.sha256()
            with open(part, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    h.update(block)
            if h.hexdigest().lower() != want:
                raise IOError("Die heruntergeladene Datei ist beschädigt (Prüfsumme stimmt nicht).")
            part.replace(target)
            self.file = target
            self.state = "ready"
            self.progress = 100.0
        except Exception as exc:
            log.warning("Update-Download fehlgeschlagen: %s", exc)
            self.state = "error"
            self.info["error"] = "Der Download ist fehlgeschlagen. Bitte später noch einmal versuchen."
            try:
                part.unlink()
            except OSError:
                pass
        self.bus.emit("update", self.status())

    def _sha_from_asset(self) -> str:
        url = self.info.get("sha_url")
        if not url:
            return ""
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            m = re.search(r"\b([0-9a-fA-F]{64})\b", r.text)
            return m.group(1).lower() if m else ""
        except Exception:
            return ""

    def check_ready(self) -> None:
        if self.state != "ready" or not self.file or not self.file.exists():
            raise ValueError("Die neue Version ist noch nicht heruntergeladen.")
        if not self.status()["can_install"]:
            raise ValueError("Updates lassen sich nur in der installierten Windows-Version einspielen.")

    def install(self) -> None:
        """Startet die stille Installation. Das Programm muss sich direkt danach beenden."""
        self.check_ready()
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([str(self.file), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                          "/UPDATE"], creationflags=flags, close_fds=True)
        self.state = "installing"
