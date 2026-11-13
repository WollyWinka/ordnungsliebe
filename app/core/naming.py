"""Datei- und Ordnernamen: bereinigen, eindeutig machen."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_NAME = 80


def clean_part(name: str, fallback: str = "Dokument") -> str:
    """Ein einzelner Datei- oder Ordnername ohne verbotene Zeichen (Windows/iCloud-tauglich)."""
    name = unicodedata.normalize("NFC", name or "")
    name = _BAD.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > MAX_NAME:
        name = name[:MAX_NAME].rstrip(" .")
    if not name:
        name = fallback
    if name.split(".")[0].strip().upper() in _RESERVED:
        name = "_" + name
    return name


MAX_LEVELS = 4  # höchstens vier Ordner-Ebenen


def clean_folder(path: str) -> str:
    """Relativer Ordnerpfad mit „/“, höchstens vier Ebenen, jede Ebene bereinigt."""
    parts = [p for p in re.split(r"[/\\]+", path or "") if p.strip()]
    parts = [clean_part(p, "Sonstiges") for p in parts][:MAX_LEVELS]
    return "/".join(parts)


def clean_filename(stem: str, suffix: str) -> str:
    stem = stem or ""
    if suffix and stem.lower().endswith(suffix.lower()):
        stem = stem[: -len(suffix)]
    return clean_part(stem) + suffix.lower()


MAX_PATH = 240


def fit_path(target: Path) -> Path:
    """Kürzt den Dateinamen, falls der ganze Pfad für Windows zu lang würde."""
    total = len(str(target))
    if total <= MAX_PATH:
        return target
    stem = target.stem[: max(12, len(target.stem) - (total - MAX_PATH))].rstrip(" .")
    return target.with_name(stem + target.suffix)


def unique_path(target: Path) -> Path:
    target = fit_path(target)
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    i = 2
    while True:
        candidate = target.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def folder_to_path(root: Path, folder: str) -> Path:
    rel = clean_folder(folder)
    return root.joinpath(*rel.split("/")) if rel else root


def display_folder(folder: str) -> str:
    return " › ".join(p for p in folder.split("/") if p)


# --- Personen im Haushalt ----------------------------------------------------------

PERSON_SEP = " – "


def _split_suffix(filename: str) -> tuple[str, str]:
    m = re.match(r"^(.*?)(\.[A-Za-z0-9]{1,5})?$", filename or "")
    return (m.group(1) or ""), (m.group(2) or "")


def strip_person(folder: str, filename: str, persons: list[str]) -> tuple[str, str]:
    """Entfernt einen Personennamen aus Ordner (letzte Ebene) und Dateiname (Endung „ – Name“)."""
    names = {p.strip().lower() for p in persons if p and p.strip()}
    parts = [p for p in (folder or "").split("/") if p]
    if len(parts) > 1 and parts[-1].lower() in names:
        parts = parts[:-1]
    stem, suffix = _split_suffix(filename)
    for name in names:
        tail = PERSON_SEP.lower() + name
        if stem.lower().endswith(tail):
            stem = stem[: -len(tail)].rstrip()
            break
    return "/".join(parts), stem + suffix


def apply_person(folder: str, filename: str, person: str, persons: list[str], mode: str) -> tuple[str, str]:
    """Setzt die Person je nach Einstellung in den Dateinamen oder als Unterordner (vorher alte entfernen)."""
    folder, filename = strip_person(folder, filename, persons)
    person = clean_part(person or "", "")
    if not person or mode == "merken":
        return folder, filename
    parts = [p for p in folder.split("/") if p]
    if mode == "unterordner" and parts and len(parts) < MAX_LEVELS:
        return "/".join(parts + [person]), filename
    stem, suffix = _split_suffix(filename)
    return folder, f"{stem}{PERSON_SEP}{person}{suffix}"
