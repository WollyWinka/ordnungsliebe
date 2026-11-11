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
    if not name or name.upper() in _RESERVED:
        name = fallback
    return name


def clean_folder(path: str) -> str:
    """Relativer Ordnerpfad mit „/“, höchstens drei Ebenen, jede Ebene bereinigt."""
    parts = [p for p in re.split(r"[/\\]+", path or "") if p.strip()]
    parts = [clean_part(p, "Sonstiges") for p in parts][:3]
    return "/".join(parts)


def clean_filename(stem: str, suffix: str) -> str:
    stem = stem or ""
    if suffix and stem.lower().endswith(suffix.lower()):
        stem = stem[: -len(suffix)]
    return clean_part(stem) + suffix.lower()


def unique_path(target: Path) -> Path:
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
