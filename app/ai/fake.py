"""Attrappe der KI für Tests und Vorführungen (ORDNUNGSLIEBE_FAKE_AI=1).

Liefert plausible Antworten anhand einfacher Stichwörter, ohne Modell.
"""

from __future__ import annotations

import re
import time

from . import prompts

KEYWORDS = [
    (["kontoauszug", "girokonto", "kontostand"], "Finanzen/Bank", "Kontoauszug"),
    (["steuerbescheid", "finanzamt", "einkommensteuer"], "Finanzen/Steuern", "Steuerbescheid"),
    (["hausrat"], "Versicherungen/Hausrat", "Beitragsrechnung"),
    (["kfz", "fahrzeug", "kennzeichen"], "Versicherungen/Kfz", "Beitragsrechnung"),
    (["versicherung", "police", "beitrag"], "Versicherungen", "Versicherungsschreiben"),
    (["strom", "gas", "stadtwerke", "abschlag"], "Wohnen/Strom & Gas", "Stromabrechnung"),
    (["miete", "mietvertrag", "vermieter", "nebenkosten"], "Wohnen/Miete", "Mietschreiben"),
    (["gehalt", "lohn", "entgelt", "abrechnung der brutto"], "Arbeit/Gehalt", "Gehaltsabrechnung"),
    (["schule", "elternbrief", "klasse", "kindergarten", "kita"], "Familie/Schule", "Elternbrief"),
    (["arzt", "praxis", "rezept", "krankenkasse"], "Gesundheit", "Arztrechnung"),
    (["rechnung", "betrag", "zahlbar"], "Rechnungen", "Rechnung"),
]

_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2}|19\d{2})\b")


_DUE = re.compile(r"(?:zahlbar bis|fällig am|bis zum|spätestens am|frist[^0-9]{0,20})\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_STEUER = ["lohnsteuer", "spende", "handwerker", "nebenkosten", "steuer", "arzt", "zahnarzt"]


def _extras(user: str, doc: str, schema: dict) -> dict:
    out = {"deadlines": [], "steuer": any(w in doc for w in _STEUER)}
    for m in _DUE.finditer(doc):
        out["deadlines"].append({"date": f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}",
                                 "what": "Frist aus dem Dokument"})
    persons = schema["properties"].get("person", {}).get("enum")
    if persons:
        out["person"] = next((p for p in persons if p and p.lower() in doc), "")
    return out


class FakeAI:
    def __init__(self, on_status=None):
        self.on_status = on_status or (lambda *a: None)
        self.started = False

    def warmup(self):
        if not self.started:
            self.on_status("starting", "Test-KI")
            time.sleep(0.2)
            self.started = True
            self.on_status("ready", "Test-KI")

    def shutdown(self):
        pass

    def chat_json(self, system, user, schema, name, max_tokens=600):
        self.warmup()
        time.sleep(0.15)
        if name == "einordnung":
            return {**self._classify(user, schema), **_extras(user, self._doc_part(user), schema)}
        if name == "struktur":
            return self._taxonomy(user)
        if name == "stapel":
            return self._split(user)
        return {}

    def _doc_part(self, user: str) -> str:
        i = user.rfind("Dokument (Typ")
        return user[i:].lower() if i >= 0 else user.lower()

    def _classify(self, user: str, schema: dict) -> dict:
        allowed = schema["properties"]["folder"]["enum"]
        doc = self._doc_part(user)
        m = re.search(r"ZU GENAU DIESEM DOKUMENT[^:]*: (.*)", user)
        if m:  # Test-KI: nennt der Hinweis einen Ordner, nimm ihn
            hint = m.group(1).lower()
            for f in allowed:
                if f != prompts.NEW_FOLDER and f.split("/")[-1].lower() in hint:
                    return {"summary": "Nach Hinweis eingeordnet", "doc_date": "", "folder": f, "new_folder": "",
                            "alternative_folder": "", "filename": "2026-11 Dokument", "confidence": "sehr sicher"}
        corr = re.findall(r"→ Ordner: (.+?), Dateiname: .*?\(KORREKTUR", user)
        for f in corr:  # Test-KI: Korrekturen bei ähnlichen Fällen übernehmen
            if f in allowed:
                return {"summary": "Wie zuvor korrigiert", "doc_date": "", "reason": "Wie bei der Korrektur des Nutzers.",
                        "folder": f, "new_folder": "", "alternative_folder": "", "filename": "2026-11 Dokument",
                        "confidence": "sehr sicher"}
        folder, doc_type, hits, new_folder = None, "Dokument", 0, ""
        # Regeln sind von speziell nach allgemein sortiert: die erste passende gewinnt.
        for words, target, dtype in KEYWORDS:
            n = sum(doc.count(w) for w in words)
            if not n:
                continue
            candidates = [f for f in allowed if f.lower() == target.lower()]
            if candidates:
                folder = candidates[0]
            elif prompts.NEW_FOLDER in allowed:
                folder, new_folder = prompts.NEW_FOLDER, target
            else:
                continue
            hits, doc_type = n + 1, dtype
            break
        if folder is None:
            real = [f for f in allowed if f != prompts.NEW_FOLDER]
            folder = real[0] if real else prompts.NEW_FOLDER
            new_folder = "Sonstiges" if folder == prompts.NEW_FOLDER else ""
        m = _DATE.search(doc)
        date = f"{m.group(3)}-{int(m.group(2)):02d}" if m else time.strftime("%Y-%m")
        real = [f for f in allowed if f not in (prompts.NEW_FOLDER, folder)]
        return {
            "summary": f"{doc_type} vom {date}",
            "reason": f"Stichwort für {doc_type} gefunden.",
            "doc_date": date,
            "folder": folder,
            "new_folder": new_folder if folder == prompts.NEW_FOLDER else "",
            "alternative_folder": real[0] if real and hits < 3 else "",
            "filename": f"{date} {doc_type}",
            "confidence": "sehr sicher" if hits >= 3 else ("ziemlich sicher" if hits else "unsicher"),
        }

    def _taxonomy(self, user: str) -> dict:
        text = user.lower()
        folders = []
        for words, target, dtype in KEYWORDS:
            if any(w in text for w in words):
                folders.append({"path": target, "scheme": "JJJJ-MM Dokumentart", "example": f"2026-01 {dtype}"})
        folders.append({"path": "Sonstiges", "scheme": "JJJJ-MM Dokumentart", "example": "2026-01 Schreiben"})
        return {"folders": folders}

    def _split(self, user: str) -> dict:
        starts = [1]
        for line in user.splitlines():
            m = re.match(r"Seite (\d+): (.*)", line)
            if m and int(m.group(1)) > 1 and re.search(r"\b(GmbH|AG|Sehr geehrte)\b", m.group(2)):
                starts.append(int(m.group(1)))
        return {"starts": starts}
