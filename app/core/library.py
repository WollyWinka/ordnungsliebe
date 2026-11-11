"""Die Ablage: Ordnerstruktur lesen, Namensschemata, Cloud-Platzhalter, sicheres Verschieben."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from .. import jsonfile, paths
from ..docs import reader
from . import naming

log = logging.getLogger(__name__)

MAX_DEPTH = 3
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", ".Trash", "__MACOSX"}

# Windows-Dateiattribute für Cloud-Dateien, die (noch) nicht lokal vorliegen
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


def is_cloud_only(path: Path) -> bool:
    if not paths.IS_WINDOWS:
        return False
    try:
        attrs = os.stat(path, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    return bool(attrs & CLOUD_ONLY_MASK)


def walk_documents(root: Path, include_cloud_only: bool = True):
    """Alle unterstützten Dokumente unterhalb von root (ohne versteckte Ordner)."""
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if fn.startswith((".", "~$")) or reader.file_kind(p) is None:
                continue
            if not include_cloud_only and is_cloud_only(p):
                continue
            yield p


def list_folders(root: Path) -> list[str]:
    """Relative Ordnerpfade (mit „/“), bis zu drei Ebenen tief, alphabetisch."""
    out = []
    if not root.exists():
        return out
    for dirpath, dirnames, _ in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        depth = len(rel.parts)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS)
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        if depth:
            out.append("/".join(rel.parts))
    return sorted(out, key=str.lower)


def folder_examples(root: Path, folder: str, limit: int = 3) -> list[str]:
    d = naming.folder_to_path(root, folder)
    try:
        files = [p for p in d.iterdir() if p.is_file() and reader.file_kind(p) and not p.name.startswith(".")]
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in files[:limit]]


def folder_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in walk_documents(root):
        rel = p.parent.relative_to(root)
        key = "/".join(rel.parts)
        counts[key] = counts.get(key, 0) + 1
    return counts


class Schemes:
    """Namensschema je Ordner (z. B. „JJJJ-MM Dokumentart“), gespeichert je Ablage."""

    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "namensschemata.json")
        self.data: dict[str, dict[str, dict]] = jsonfile.load(self.path, {})

    def for_library(self, root: Path) -> dict[str, dict]:
        return self.data.get(str(root), {})

    def set_all(self, root: Path, folders: list[dict]) -> None:
        self.data[str(root)] = {f["path"]: {"scheme": f.get("scheme", ""), "example": f.get("example", "")}
                                for f in folders}
        jsonfile.save(self.path, self.data)

    def set_one(self, root: Path, folder: str, scheme: str, example: str = "") -> None:
        self.data.setdefault(str(root), {})[folder] = {"scheme": scheme, "example": example}
        jsonfile.save(self.path, self.data)


def cloud_only_files(root: Path) -> tuple[int, int]:
    """(Anzahl, Bytes) der Dateien, die nur in der Cloud liegen."""
    count = size = 0
    for p in walk_documents(root):
        if is_cloud_only(p):
            count += 1
            try:
                size += p.stat().st_size
            except OSError:
                pass
    return count, size


def keep_local(root: Path, on_progress=None) -> int:
    """Lädt Cloud-Dateien herunter und markiert sie als „Immer auf diesem Gerät behalten“."""
    if paths.IS_WINDOWS:
        try:
            subprocess.run(["attrib", "+P", "-U", "/S", "/D", str(root / "*")], capture_output=True,
                           creationflags=0x08000000, timeout=120)
        except Exception:
            log.exception("attrib +P fehlgeschlagen")
    files = [p for p in walk_documents(root) if is_cloud_only(p)]
    for i, p in enumerate(files, 1):
        try:
            with open(p, "rb") as fh:
                while fh.read(1 << 20):
                    pass
        except OSError:
            log.warning("Konnte %s nicht herunterladen", p)
        if on_progress:
            on_progress(i, len(files))
    return len(files)


def move_file(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst = naming.unique_path(dst)
    shutil.move(str(src), str(dst))
    return dst


def remove_empty_dirs(root: Path) -> list[str]:
    """Löscht leere Ordner unterhalb von root. Gibt die relativen Pfade zurück."""
    removed = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        if p == root or any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        try:
            if not any(p.iterdir()):
                p.rmdir()
                removed.append("/".join(p.relative_to(root).parts))
        except OSError:
            continue
    return removed


def known_cloud_roots() -> list[dict]:
    """Findet übliche Cloud-Ordner (iCloud Drive, OneDrive, Dropbox, Google Drive)."""
    home = Path.home()
    found = []
    candidates = [
        ("icloud", "iCloud Drive", [home / "iCloudDrive", home / "iCloud Drive"]),
        ("onedrive", "OneDrive", [Path(os.environ[v]) for v in ("OneDrive", "OneDriveConsumer") if os.environ.get(v)]
         + [home / "OneDrive"]),
        ("dropbox", "Dropbox", [home / "Dropbox"]),
        ("gdrive", "Google Drive", [home / "Google Drive", Path("G:/Meine Ablage"), Path("G:/My Drive")]),
    ]
    for key, label, paths_ in candidates:
        for base in paths_:
            if base.exists() and base.is_dir():
                docs = None
                for sub in ("Dokumente", "Documents"):
                    if (base / sub).is_dir():
                        docs = base / sub
                        break
                target = docs or base
                found.append({"id": key, "title": label, "path": str(target), "cloud": True,
                              "display": label + (" › " + target.name if docs else "")})
                break
    return found
