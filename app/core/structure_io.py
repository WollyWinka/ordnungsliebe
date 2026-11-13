"""Ordnerstruktur als einfache Textdatei: einlesen, speichern und eine Anleitung für eine KI erzeugen.

Format (eine Zeile pro Ordner, Unterordner eingerückt, Beschreibung optional nach „ – “):

    Finanzen – Bank, Kredite, Geldanlagen
      Girokonto – Kontoauszüge
      Kredit Haus
    Arbeit
      Entgeltnachweise

Verstanden werden außerdem Markdown-Listen („- Finanzen“), Überschriften („## Finanzen“) und
Pfade („Finanzen/Girokonto“ oder „Finanzen › Girokonto“).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from . import naming

_BULLET = re.compile(r"^([-*+•·▪◦‣]|\d{1,3}[.)])\s+")
_HEADING = re.compile(r"^(#{1,6})\s+")
_DESC_SPLIT = re.compile(r"\s+[–—-]\s+|:\s+|\s+\(|\s{2,}#\s*")
_PATH_SPLIT = re.compile(r"\s*(?:/|›|»|>|\\)\s*")
_TREE_CHARS = re.compile(r"^[\s│├└┬─┃┣┗━|`]+")


def _split_desc(text: str) -> tuple[str, str]:
    m = _DESC_SPLIT.search(text)
    if not m:
        return text.strip(), ""
    name, desc = text[:m.start()], text[m.end():]
    if m.group(0).strip() == "(":
        desc = desc.rstrip(")")
    return name.strip(), desc.strip()


def parse(text: str) -> tuple[list[dict], list[str]]:
    """Text → ([{"path", "desc", "scheme", "example"}], Hinweise)."""
    warnings: list[str] = []
    out: dict[str, dict] = {}
    order: list[str] = []
    head: list[str] = []                 # Pfad aus Markdown-Überschriften
    stack: list[tuple[int, str]] = []    # (Einrückung, Name) für eingerückte Zeilen
    too_deep = skipped = 0
    in_fence = False
    for raw in (text or "").replace("﻿", "").splitlines():
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            continue
        line = raw.replace("\t", "    ").rstrip()
        if not line.strip():
            continue
        # Baum-Zeichen (├──, │) wie Einrückung behandeln
        tm = _TREE_CHARS.match(line)
        if tm and any(c in tm.group(0) for c in "│├└┬─┃┣┗━|`"):
            line = " " * len(tm.group(0)) + line[tm.end():]
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        hm = _HEADING.match(content)
        level_from_heading = None
        if hm:
            level_from_heading = len(hm.group(1)) - 1
            content = content[hm.end():]
        else:
            bm = _BULLET.match(content)
            if bm:
                content = content[bm.end():]
        content = content.strip().strip("*_`").strip()
        name, desc = _split_desc(content)
        name = name.strip().strip("*_`\"'„“").rstrip(":").strip()
        if not name:
            continue
        # Fließtext („Hier ist deine Struktur:“) überspringen
        if len(name.split()) > 6 or (content.endswith(":") and not desc and indent == 0 and not hm
                                     and not _BULLET.match(line.strip())):
            skipped += 1
            continue
        parts = [p for p in _PATH_SPLIT.split(name) if p.strip()]
        if level_from_heading is not None:
            head = head[:level_from_heading] + ["/".join(parts)]
            stack = []
            path_parts = "/".join(head).split("/")
        else:
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, "/".join(parts)))
            path_parts = "/".join(head + [n for _, n in stack]).split("/")
        clean = [naming.clean_part(p, "") for p in path_parts]
        clean = [p for p in clean if p]
        if not clean:
            continue
        if len(clean) > naming.MAX_LEVELS:
            too_deep += 1
            clean = clean[:naming.MAX_LEVELS]
        for depth in range(1, len(clean) + 1):
            path = "/".join(clean[:depth])
            key = path.lower()
            if key not in out:
                out[key] = {"path": path, "desc": "", "scheme": "JJJJ-MM Dokumentart", "example": ""}
                order.append(key)
        if desc and not out["/".join(clean).lower()]["desc"]:
            out["/".join(clean).lower()]["desc"] = desc[:160]
    result = [out[k] for k in order]
    # Steht alles unter einem einzigen obersten Ordner (z. B. „Ablage“), ist das die Wurzel selbst
    tops = {f["path"].split("/")[0] for f in result}
    if len(tops) == 1 and len(result) > 2:
        root = next(iter(tops))
        result = [dict(f, path=f["path"].split("/", 1)[1]) for f in result if "/" in f["path"]]
        warnings.append(f"„{root}“ habe ich als die Ablage selbst verstanden und nicht als eigenen Ordner angelegt.")
    if too_deep:
        warnings.append(f"{too_deep} Ordner lagen tiefer als {naming.MAX_LEVELS} Ebenen und wurden auf "
                        f"{naming.MAX_LEVELS} Ebenen gekürzt.")
    if skipped:
        warnings.append(f"{skipped} Zeilen sahen nicht nach Ordnern aus und wurden übersprungen.")
    return result, warnings


def export(folders: list[dict]) -> str:
    """Struktur → Text im Importformat (Unterordner mit zwei Leerzeichen eingerückt)."""
    lines = []
    for f in sorted(folders, key=lambda x: [p.lower() for p in x["path"].split("/")]):
        parts = f["path"].split("/")
        desc = (f.get("desc") or "").strip()
        lines.append("  " * (len(parts) - 1) + parts[-1] + (f" – {desc}" if desc else ""))
    return "\n".join(lines) + "\n"


FORMAT_HELP = """Format: eine Zeile pro Ordner. Unterordner werden mit zwei Leerzeichen eingerückt (höchstens 4 Ebenen).
Hinter dem Ordnernamen darf nach „ – “ eine kurze Beschreibung stehen, was hineingehört.
Beispiel:
Finanzen – Bank, Kredite, Geldanlagen
  Girokonto – Kontoauszüge
  Kredit Haus
Arbeit
  Entgeltnachweise
  Arbeitsvertrag"""


def ai_brief(docs: list[dict], current: list[dict]) -> str:
    """Text für eine KI (z. B. Claude): beschreibt das Format und was in der Ablage liegt – ohne Inhalte."""
    by_folder: dict[str, list[str]] = {}
    for d in docs:
        rel = d.get("rel", "")
        folder = "/".join(rel.split("/")[:-1]) or "(direkt in der Ablage)"
        by_folder.setdefault(folder, []).append(rel.split("/")[-1])
    kinds = Counter()
    for d in docs:
        stem = Path(d.get("rel", "")).stem
        words = re.sub(r"^[\d\-_. ]+", "", stem)  # Datum vorne weg
        words = re.sub(r"[_\d]+", " ", words).split()
        if words:
            kinds[" ".join(words[:2]).lower()] += 1
    lines = [
        "Ich sortiere meine privaten Dokumente (Rechnungen, Verträge, Bescheide, Kontoauszüge usw.) mit dem "
        "Programm „Ordnungsliebe“. Bitte entwirf mir eine übersichtliche, logische Ordnerstruktur dafür.",
        "",
        "Wünsche:",
        "- 6 bis 14 Hauptordner, darunter sinnvolle Unterordner (höchstens 4 Ebenen).",
        "- Kurze, verständliche deutsche Ordnernamen ohne die Zeichen / \\ : * ? \" < > |",
        "- So aufgeteilt, wie man später etwas sucht (nach Lebensbereich, Vertrag, Anbieter, Person).",
        "",
        "Antworte bitte NUR mit der Struktur in genau diesem Format, damit ich sie importieren kann:",
        FORMAT_HELP,
        "",
        f"So sieht meine Ablage im Moment aus ({len(docs)} Dokumente; Ordner, Anzahl, Beispiel-Dateinamen):",
    ]
    for folder in sorted(by_folder, key=str.lower):
        names = by_folder[folder]
        sample = "; ".join(sorted(names)[:5])
        lines.append(f"- {folder.replace('/', ' › ')} ({len(names)}): {sample}")
    if kinds:
        lines += ["", "Häufige Dokumentarten (aus den Dateinamen geschätzt):",
                  ", ".join(f"{k} ({n})" for k, n in kinds.most_common(40))]
    if current:
        lines += ["", "Vorschlag des Programms (darfst du gern verbessern):", export(current).rstrip()]
    return "\n".join(lines) + "\n"
