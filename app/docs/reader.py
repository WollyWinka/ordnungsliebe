"""Text aus Dokumenten lesen – mit Zwischenspeicher, damit nichts doppelt erkannt wird."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

from .. import jsonfile, paths
from . import ocr, office

log = logging.getLogger(__name__)

PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
SUPPORTED_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES | office.OFFICE_SUFFIXES | office.EMAIL_SUFFIXES

CACHE_VERSION = 2


def file_kind(path: Path) -> str | None:
    s = path.suffix.lower()
    if s in PDF_SUFFIXES:
        return "pdf"
    if s in IMAGE_SUFFIXES:
        return "image"
    if s in office.OFFICE_SUFFIXES:
        return "office"
    if s in office.EMAIL_SUFFIXES:
        return "email"
    return None


def is_supported(path: Path) -> bool:
    return (path.is_file() and file_kind(path) is not None
            and not path.name.startswith((".", "~$")))


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class DocText:
    kind: str
    text: str
    page_texts: list[str] = field(default_factory=list)
    page_count: int = 1
    ocr_used: bool = False
    email: dict | None = None
    sha256: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _cache_path(sha: str) -> Path:
    d = paths.cache_dir() / "texte" / sha[:2]
    return d / f"{sha}.json"


def _read_pdf(doc: "pymupdf.Document") -> tuple[list[str], bool]:
    texts, used = [], False
    for page in doc:
        t, u = ocr.page_text(page)
        texts.append(t.strip())
        used = used or u
    return texts, used


def read_document(path: Path, sha: str | None = None, use_cache: bool = True) -> DocText:
    """Liest den Text eines Dokuments. Scans werden per Texterkennung gelesen."""
    kind = file_kind(path)
    if kind is None:
        raise ValueError(f"Nicht unterstützter Dateityp: {path.suffix}")
    sha = sha or file_hash(path)
    cp = _cache_path(sha)
    if use_cache:
        cached = jsonfile.load(cp, None)
        if cached and cached.get("_v") == CACHE_VERSION:
            cached.pop("_v", None)
            return DocText(**cached)

    result: DocText
    if kind == "pdf":
        doc = pymupdf.open(str(path))
        texts, used = _read_pdf(doc)
        result = DocText(kind, "\n\n".join(texts), texts, doc.page_count, used, sha256=sha)
        doc.close()
    elif kind == "image":
        doc = ocr.image_to_pdf(path)
        texts, used = _read_pdf(doc)
        result = DocText(kind, "\n\n".join(texts), texts, doc.page_count, used, sha256=sha)
        doc.close()
    elif kind == "office":
        pdf = office.office_to_pdf(path)
        if pdf is not None:
            doc = pymupdf.open(str(pdf))
            texts = [p.get_text().strip() for p in doc]
            result = DocText(kind, "\n\n".join(texts), texts, doc.page_count, sha256=sha)
            doc.close()
        else:
            text = office.office_text_fallback(path)
            result = DocText(kind, text, [text], 1, sha256=sha)
    else:  # email
        view = office.parse_email(path)
        text = office.email_text(view)
        result = DocText(kind, text, [text], 1, email=view, sha256=sha)

    data = result.to_dict()
    data["_v"] = CACHE_VERSION
    try:
        jsonfile.save(cp, data)
    except OSError:
        log.warning("Text-Zwischenspeicher konnte nicht geschrieben werden")
    return result
