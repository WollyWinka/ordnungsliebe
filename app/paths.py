"""Zentrale Pfade: Benutzerdaten, Modelle, Sicherungen und mitgelieferte Werkzeuge."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import APP_NAME

IS_WINDOWS = sys.platform.startswith("win")
IS_FROZEN = getattr(sys, "frozen", False)


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def install_dir() -> Path:
    """Ordner, in dem das Programm liegt (bei der installierten Version neben der exe)."""
    if IS_FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Ordner mit eingebetteten Dateien (Oberfläche)."""
    if IS_FROZEN and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return install_dir()


def ui_dir() -> Path:
    return resource_dir() / "ui"


def tools_dir() -> Path:
    override = os.environ.get("ORDNUNGSLIEBE_TOOLS")
    if override:
        return Path(override)
    return install_dir() / "tools"


def data_dir() -> Path:
    """Kleine Benutzerdaten: Einstellungen, Gedächtnis, Verlauf."""
    override = os.environ.get("ORDNUNGSLIEBE_DATA")
    if override:
        return _ensure(Path(override))
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return _ensure(base / APP_NAME)


def local_dir() -> Path:
    """Große, rechnerbezogene Daten: KI-Modelle, Zwischenspeicher, Sicherungen."""
    override = os.environ.get("ORDNUNGSLIEBE_LOCAL")
    if override:
        return _ensure(Path(override))
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return _ensure(base / APP_NAME)
    return data_dir()


def models_dir() -> Path:
    return _ensure(local_dir() / "Modelle")


def cache_dir() -> Path:
    return _ensure(local_dir() / "Zwischenspeicher")


def backups_dir() -> Path:
    return _ensure(local_dir() / "Sicherungen")


def lo_profile_dir() -> Path:
    return _ensure(local_dir() / "libreoffice-profil")


def tessdata_dir() -> Path | None:
    candidates = [tools_dir() / "tessdata"]
    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        candidates.append(Path(env))
    candidates += [
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
        Path("/usr/share/tessdata"),
    ]
    for c in candidates:
        if (c / "deu.traineddata").exists():
            return c
    return None


def soffice_path() -> Path | None:
    bundled = tools_dir() / "libreoffice" / "program" / ("soffice.exe" if IS_WINDOWS else "soffice")
    if bundled.exists():
        return bundled
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return Path(found) if found else None


def llama_server_path() -> Path | None:
    name = "llama-server.exe" if IS_WINDOWS else "llama-server"
    bundled = tools_dir() / "llama" / name
    if bundled.exists():
        return bundled
    found = shutil.which("llama-server")
    return Path(found) if found else None
