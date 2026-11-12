"""Die Ablage: Ordnerstruktur lesen, Namensschemata, Cloud-Platzhalter, sicheres Verschieben."""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
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


# EXIF-Merkmale, die nur Kameras schreiben (Belichtungszeit, Brennweite, Blende, ISO)
_CAMERA_TAGS = (33434, 37386, 33437, 34855)


def is_photo(path: Path) -> bool:
    """True für Kamerafotos und kleine Bilder (Symbole). Gescannte Dokumente sind keine Fotos.

    Bilder, die nur in der Cloud liegen, werden nicht geöffnet (das würde sie herunterladen)
    und vorsichtshalber wie Fotos behandelt, also nicht angefasst.
    """
    if reader.file_kind(path) != "image":
        return False
    if is_cloud_only(path):
        return True
    try:
        from PIL import Image
        with Image.open(path) as img:
            if min(img.size) < 500:
                return True
            exif = img.getexif()
            sub = exif.get_ifd(0x8769) if exif else {}
            return any(t in sub or t in exif for t in _CAMERA_TAGS)
    except Exception:
        return False


def walk_documents(root: Path, include_cloud_only: bool = True, skip_photos: bool = False):
    """Alle unterstützten Dokumente unterhalb von root (ohne versteckte Ordner).

    skip_photos: Kamerafotos auslassen (für Neuordnung und Zählung der Ablage).
    """
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "$")) and d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if fn.startswith((".", "~$")) or reader.file_kind(p) is None:
                continue
            if not include_cloud_only and is_cloud_only(p):
                continue
            if skip_photos and is_photo(p):
                continue
            yield p


def long_path(p: Path) -> str:
    """Windows-Pfad mit Langpfad-Präfix, damit auch Pfade über 260 Zeichen funktionieren."""
    s = str(Path(p).absolute())
    if not paths.IS_WINDOWS or s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


# Windows-Fehlernummern der Cloud-Dateien-Schnittstelle (iCloud, OneDrive …)
CLOUD_ERRORS = set(range(362, 400))


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


def folder_counts(root: Path, skip_photos: bool = True) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in walk_documents(root, skip_photos=skip_photos):
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
    """(Anzahl, Bytes) der Dokumente (ohne Bilder), die nur in der Cloud liegen."""
    count = size = 0
    for p in walk_documents(root):
        if reader.file_kind(p) != "image" and is_cloud_only(p):
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
    files = [p for p in walk_documents(root) if reader.file_kind(p) != "image" and is_cloud_only(p)]
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


# Alle Verschiebungen laufen nacheinander – so kann keine Datei eine andere überschreiben.
_MOVE_LOCK = threading.RLock()
_ERROR_NOT_SAME_DEVICE = 17  # Windows


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def missing_parents(target: Path) -> list[Path]:
    """Ordner, die für target erst angelegt werden müssen (von außen nach innen)."""
    out = []
    p = target.parent
    while not p.exists():
        out.append(p)
        if p.parent == p:
            break
        p = p.parent
    return list(reversed(out))


def move_file(src: Path, dst: Path) -> Path:
    """Verschiebt src nach dst, ohne jemals eine vorhandene Datei zu überschreiben.

    Ist dst belegt, wird „Name (2)“ usw. gewählt. Zwischen Laufwerken wird erst kopiert,
    die Kopie geprüft (Größe und Prüfsumme) und erst dann das Original entfernt.
    """
    with _MOVE_LOCK:
        if not src.exists():
            raise FileNotFoundError(f"Die Datei {src.name} ist nicht mehr da.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst = naming.unique_path(dst)
        try:
            if dst.exists():  # Sicherheitsnetz (POSIX-rename würde überschreiben)
                dst = naming.unique_path(dst)
            os.rename(src, dst)
            return dst
        except OSError as exc:
            cross = exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == _ERROR_NOT_SAME_DEVICE
            if not cross:
                raise
        tmp = dst.with_name(f".~ordnungsliebe-{uuid.uuid4().hex[:8]}.part")
        try:
            shutil.copy2(src, tmp)
            if tmp.stat().st_size != src.stat().st_size or _sha(tmp) != _sha(src):
                raise OSError("Die Kopie ist unvollständig.")
            dst = naming.unique_path(dst)
            os.rename(tmp, dst)
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        try:
            os.unlink(src)
        except OSError:
            log.warning("Original %s konnte nach dem Kopieren nicht entfernt werden", src)
        return dst


def quarantine_dir() -> Path:
    return paths.local_dir() / "Papierkorb"


def quarantine(path: Path) -> Path:
    """Legt eine Datei für 30 Tage in den Ordnungsliebe-Papierkorb (statt sie zu löschen)."""
    day = time.strftime("%Y-%m-%d")
    return move_file(path, quarantine_dir() / day / path.name)


def purge_quarantine(days: int = 30) -> int:
    root = quarantine_dir()
    if not root.exists():
        return 0
    limit = time.time() - days * 86400
    removed = 0
    for d in root.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


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
                found.append({"id": key, "title": label, "path": str(target), "base": str(base), "cloud": True,
                              "display": label + (" › " + target.name if docs else "")})
                break
    return found


FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def _hidden(p: Path) -> bool:
    if p.name.startswith((".", "$", "~")) or p.name in SKIP_DIRS:
        return True
    if paths.IS_WINDOWS:
        try:
            attrs = os.stat(p, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
            return bool(attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))
        except (OSError, AttributeError):
            return False
    return False


def subfolders(path: Path) -> list[Path]:
    """Sichtbare Unterordner (für die Ordnerauswahl im Programm)."""
    out = []
    try:
        for d in path.iterdir():
            try:
                if d.is_dir() and not _hidden(d):
                    out.append(d)
            except OSError:
                continue
    except OSError:
        return []
    return sorted(out, key=lambda d: d.name.lower())


def start_places() -> list[dict]:
    """Ausgangspunkte für die Ordnerauswahl: Cloud-Ordner, persönliche Ordner, Laufwerke."""
    home = Path.home()
    places, seen = [], set()

    def add(title, p):
        p = Path(p)
        if p.is_dir() and str(p).lower() not in seen:
            seen.add(str(p).lower())
            places.append({"name": title, "path": str(p)})

    for r in known_cloud_roots():
        add(r["title"], r["base"])
    for title, names in (("Dokumente", ("Documents", "Dokumente")), ("Desktop", ("Desktop",)),
                         ("Downloads", ("Downloads",)), ("Bilder", ("Pictures", "Bilder"))):
        for n in names:
            if (home / n).is_dir():
                add(title, home / n)
                break
    add("Persönlicher Ordner", home)
    if paths.IS_WINDOWS:
        import string
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:/")
            try:
                if drive.exists():
                    add(f"Laufwerk {letter}:", drive)
            except OSError:
                continue
    else:
        add("Computer", Path("/"))
    return places
