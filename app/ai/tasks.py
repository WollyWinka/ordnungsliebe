"""Die drei KI-Aufgaben: Dokument einordnen, Ordnerstruktur entwerfen, Scan-Stapel erkennen."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..core import naming
from . import prompts

log = logging.getLogger(__name__)

TEXT_HEAD = 3500
TEXT_TAIL = 500

CONFIDENCE_SCORES = {"sehr sicher": 0.92, "ziemlich sicher": 0.78, "unsicher": 0.45}


def _doc_excerpt(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= TEXT_HEAD + TEXT_TAIL:
        return text
    return text[:TEXT_HEAD] + "\n[…]\n" + text[-TEXT_TAIL:]


def output_suffix(kind: str, original: Path) -> str:
    return ".pdf" if kind in ("pdf", "image") else original.suffix.lower()


def classify(ai, *, text: str, original: Path, kind: str, page_count: int,
             folders: list[str], folder_info: dict[str, dict], examples: list[dict],
             excluded: list[str] | None = None, allow_new: bool = True,
             user_hints: list[str] | None = None, doc_hint: str = "",
             folder_counts: dict[str, int] | None = None, new_only_below: bool = False) -> dict:
    """Schlägt Ordner, Dateinamen und Kurzbeschreibung vor.

    folder_info: Ordner -> {"scheme": str, "files": [Beispieldateinamen]}
    examples:    ähnliche bestätigte Fälle aus dem Gedächtnis
    """
    excluded = [f for f in (excluded or []) if f]
    allowed = [f for f in folders if f not in excluded]

    lines = []
    for f in allowed:
        info = folder_info.get(f, {})
        parts = [f]
        if info.get("scheme"):
            parts.append(f"Schema: {info['scheme']}")
        if folder_counts and folder_counts.get(f):
            parts.append(f"{folder_counts[f]} Dokumente")
        if info.get("files"):
            parts.append("z. B. " + "; ".join(info["files"][:3]))
        lines.append("- " + " — ".join(parts))
    folder_block = "\n".join(lines) if lines else "(noch keine Ordner vorhanden)"

    user = [f"Ordnerstruktur:\n{folder_block}"]
    if examples:
        ex_lines = []
        ordered = sorted(examples, key=lambda e: not e.get("corrected"))  # Korrekturen zuerst
        for i, e in enumerate(ordered, 1):
            snippet = re.sub(r"\s+", " ", e.get("text", ""))[:300]
            if e.get("corrected"):
                why = f'; deine Begründung damals: „{e["ai_reason"]}“' if e.get("ai_reason") else ""
                note = f"KORREKTUR – du hattest {e['ai_folder']} vorgeschlagen{why}, der Nutzer hat {e['folder']} gewählt"
            elif e.get("ai_folder"):
                note = "dein Vorschlag wurde bestätigt"
            else:
                note = "vom Nutzer so abgelegt"
            if e.get("hint"):
                note += f'; Hinweis des Nutzers: „{e["hint"]}“'
            ex_lines.append(f"{i}) Text: «{snippet}» → Ordner: {e['folder']}, Dateiname: {e['filename']} ({note})")
        user.append("Ähnliche, vom Nutzer bereits entschiedene Fälle:\n" + "\n".join(ex_lines))
    if user_hints:
        user.append("Allgemeine Hinweise des Nutzers (immer beachten):\n" + "\n".join(f"- {h}" for h in user_hints))
    if excluded:
        user.append("Der Nutzer hat diese Ordner für dieses Dokument abgelehnt, nicht verwenden: "
                    + ", ".join(excluded))
    if doc_hint:
        user.append(f"HINWEIS DES NUTZERS ZU GENAU DIESEM DOKUMENT (hat Vorrang vor allem anderen): {doc_hint}")
    if not allow_new:
        user.append('Wähle unbedingt einen vorhandenen Ordner, nicht "__NEU__".')
    elif new_only_below:
        user.append('Neue Ordner ("__NEU__") nur als Unterordner eines vorhandenen Ordners aus der Liste.')
    type_label = {"pdf": "PDF", "image": "Bild/Scan", "office": "Office-Datei", "email": "E-Mail"}.get(kind, kind)
    user.append(f"Dokument (Typ: {type_label}, Originalname: {original.name}, Seiten: {page_count}):\n"
                f"«{_doc_excerpt(text) or '(kein Text erkennbar)'}»")

    schema = prompts.classify_schema(allowed if allowed or not allow_new else [])
    if not allow_new and not allowed:
        allowed = folders[:]  # Notfall: alles erlaubt
        schema = prompts.classify_schema(allowed)
    if not allow_new:
        schema["properties"]["folder"]["enum"] = allowed or [prompts.NEW_FOLDER]

    raw = ai.chat_json(prompts.CLASSIFY_SYSTEM, "\n\n".join(user), schema, "einordnung", max_tokens=400)
    return _postprocess(raw, original=original, kind=kind, folders=folders, excluded=excluded,
                        allow_new=allow_new, examples=examples, new_only_below=new_only_below)


def _postprocess(raw: dict, *, original: Path, kind: str, folders: list[str], excluded: list[str],
                 allow_new: bool, examples: list[dict], new_only_below: bool = False) -> dict:
    lower_map = {f.lower(): f for f in folders}
    excluded_lower = {e.lower() for e in excluded}
    folder = str(raw.get("folder") or "")
    alt = str(raw.get("alternative_folder") or "")
    is_new = False
    if folder == prompts.NEW_FOLDER or folder not in folders or folder in excluded:
        candidate = naming.clean_folder(str(raw.get("new_folder") or ""))
        if candidate.lower() in lower_map and candidate.lower() not in excluded_lower:
            folder = lower_map[candidate.lower()]
        elif (candidate and allow_new and candidate.lower() not in lower_map
              and (not new_only_below or "/".join(candidate.split("/")[:-1]).lower() in lower_map)):
            folder = "/".join(candidate.split("/")[:3])  # höchstens drei Ebenen
            is_new = True
        else:
            # Die KI wollte einen abgelehnten Ordner „neu“ anlegen → nächstbesten nehmen
            fallback = ([alt] if alt in folders and alt not in excluded else []) + \
                       [f for f in folders if f not in excluded]
            folder = fallback[0] if fallback else "Sonstiges"
            is_new = folder not in folders
    if alt not in folders or alt == folder or alt in excluded:
        alt = ""

    label = str(raw.get("confidence") or "unsicher")
    score = CONFIDENCE_SCORES.get(label, 0.45)
    if examples:
        top = examples[0]
        if top.get("score", 0) >= 0.35:
            if top["folder"] == folder:
                score += 0.06
            else:
                score -= 0.25 if top.get("corrected") else 0.15
    if is_new:
        score = min(score, 0.7)
    if excluded:
        score = min(score, 0.79)
    score = max(0.05, min(score, 0.99))

    suffix = output_suffix(kind, original)
    filename = naming.clean_filename(str(raw.get("filename") or original.stem), suffix)
    return {
        "folder": folder,
        "is_new_folder": is_new,
        "alt_folder": alt,
        "filename": filename,
        "summary": str(raw.get("summary") or "").strip()[:200],
        "reason": str(raw.get("reason") or "").strip()[:300],
        "doc_date": str(raw.get("doc_date") or ""),
        "confidence": round(score, 2),
    }


# --- Ordnerstruktur ----------------------------------------------------------------

def _batches(items: list[str], budget: int = 9000) -> list[list[str]]:
    out, cur, size = [], [], 0
    for it in items:
        if cur and size + len(it) > budget:
            out.append(cur)
            cur, size = [], 0
        cur.append(it)
        size += len(it)
    if cur:
        out.append(cur)
    return out


def build_taxonomy(ai, docs: list[dict], mode: str, existing: dict[str, int], on_progress=None,
                   should_stop=None) -> list[dict]:
    """docs: [{"rel": "Ordner/Datei.pdf", "text": "..."}]; mode: "neu" oder "verbessern"."""
    lines = []
    for d in docs:
        snippet = re.sub(r"\s+", " ", d.get("text") or "")[:220]
        lines.append(f"- [{d['rel']}] {snippet}")
    batches = _batches(lines)
    structure: list[dict] = []
    for i, batch in enumerate(batches, 1):
        if should_stop and should_stop():
            return structure
        parts = []
        if mode == "verbessern" and existing:
            parts.append("Vorhandene Ordner des Nutzers (mit Anzahl Dokumente). Behalte sinnvolle Ordner, "
                         "fasse ähnliche zusammen, benenne unklare verständlich um:\n"
                         + "\n".join(f"- {k} ({v})" for k, v in sorted(existing.items()) if k))
        elif mode == "neu":
            parts.append("Entwirf eine komplett neue Struktur. Die bisherigen Ordnernamen in eckigen Klammern "
                         "sind nur ein Hinweis, du musst sie nicht übernehmen.")
        if structure:
            parts.append("Bisher entworfene Struktur (übernehmen und nur bei Bedarf ergänzen oder verfeinern):\n"
                         + "\n".join(f"- {f['path']} — Schema: {f['scheme']} — Beispiel: {f['example']}"
                                     for f in structure))
        parts.append(f"Dokumente (Teil {i} von {len(batches)}; in eckigen Klammern der bisherige Ablageort):\n"
                     + "\n".join(batch))
        raw = ai.chat_json(prompts.TAXONOMY_SYSTEM, "\n\n".join(parts), prompts.TAXONOMY_SCHEMA,
                           "struktur", max_tokens=1800)
        structure = clean_structure(raw.get("folders") or []) or structure
        if on_progress:
            on_progress(i, len(batches))
    return structure


def clean_structure(folders: list[dict]) -> list[dict]:
    seen, out = set(), []
    for f in folders:
        path = naming.clean_folder(str(f.get("path") or ""))
        path = "/".join(path.split("/")[:3])
        if not path or path.lower() in seen:
            continue
        seen.add(path.lower())
        out.append({"path": path,
                    "scheme": str(f.get("scheme") or "JJJJ-MM Dokumentart").strip()[:80],
                    "example": naming.clean_part(str(f.get("example") or ""), "")[:80]})
    # Elternordner ergänzen, falls nur tiefere Ordner genannt wurden
    for f in list(out):
        parts = f["path"].split("/")
        for depth in range(1, len(parts)):
            parent = "/".join(parts[:depth])
            if parent.lower() not in seen:
                seen.add(parent.lower())
                out.append({"path": parent, "scheme": "JJJJ-MM Dokumentart", "example": ""})
    out.sort(key=lambda f: f["path"].lower())
    return out


# --- Scan-Stapel -------------------------------------------------------------------

def detect_starts(ai, page_texts: list[str]) -> list[int]:
    n = len(page_texts)
    if n < 2 or n > 30:
        return [1]
    lines = []
    for i, t in enumerate(page_texts, 1):
        snippet = re.sub(r"\s+", " ", t or "")[:300] or "(leere oder unleserliche Seite)"
        lines.append(f"Seite {i}: {snippet}")
    raw = ai.chat_json(prompts.SPLIT_SYSTEM, "\n".join(lines), prompts.SPLIT_SCHEMA, "stapel", max_tokens=120)
    starts = sorted({int(s) for s in raw.get("starts", []) if isinstance(s, (int, float)) and 1 <= int(s) <= n})
    if 1 not in starts:
        starts.insert(0, 1)
    return starts
