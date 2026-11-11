"""Anweisungen (Prompts) und JSON-Schemata für die KI."""

from __future__ import annotations

NEW_FOLDER = "__NEU__"
CONFIDENCE_VALUES = ["sehr sicher", "ziemlich sicher", "unsicher"]

CLASSIFY_SYSTEM = """Du bist ein sorgfältiger Ablage-Assistent für private Dokumente in Deutschland.
Du ordnest ein Dokument in eine bestehende Ordnerstruktur ein und schlägst einen Dateinamen vor.

Regeln:
- Wähle für "folder" genau einen Ordner aus der Liste. Nur wenn wirklich keiner passt, wähle "__NEU__" und nenne in "new_folder" einen kurzen neuen Ordnerpfad (höchstens zwei Ebenen, getrennt mit "/", z. B. "Versicherungen/Haftpflicht"), passend zum Stil der vorhandenen Ordner. Sonst ist "new_folder" leer.
- Die Ordner sagen, WAS für ein Dokument es ist. Der Dateiname sagt, WELCHES es ist. Wiederhole im Dateinamen nichts, was schon im Ordnerpfad steht.
- Richte den Dateinamen nach dem Namensschema und den Beispieldateien des Zielordners. Ohne Schema gilt: "JJJJ-MM Dokumentart", Datum aus dem Dokument selbst (Rechnungs-, Brief- oder Ausstellungsdatum), nicht das heutige Datum.
- Dateiname ohne Dateiendung, ohne die Zeichen / \\ : * ? " < > |, höchstens 60 Zeichen, auf Deutsch.
- "summary": ein kurzer deutscher Satz, was das Dokument ist, z. B. "Beitragsrechnung der Hausratversicherung für 2027".
- "alternative_folder": der zweitbeste Ordner aus der Liste oder "".
- "confidence": "sehr sicher", "ziemlich sicher" oder "unsicher". Sei ehrlich: Wenn zwei Ordner gleich gut passen, ist es "unsicher".
- Ähnliche, vom Nutzer bereits bestätigte Fälle haben Vorrang vor deinem eigenen Gefühl."""


def classify_schema(folders: list[str]) -> dict:
    choices = list(folders) + [NEW_FOLDER]
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "doc_date": {"type": "string"},
            "folder": {"type": "string", "enum": choices},
            "new_folder": {"type": "string"},
            "alternative_folder": {"type": "string", "enum": list(folders) + [""]},
            "filename": {"type": "string"},
            "confidence": {"type": "string", "enum": CONFIDENCE_VALUES},
        },
        "required": ["summary", "doc_date", "folder", "new_folder", "alternative_folder",
                     "filename", "confidence"],
    }


TAXONOMY_SYSTEM = """Du entwirfst eine übersichtliche Ordnerstruktur für die privaten Dokumente eines Haushalts in Deutschland.

Regeln:
- Höchstens zwei Ebenen: Hauptordner und Unterordner, getrennt mit "/" (z. B. "Versicherungen/Hausrat").
- 5 bis 15 Hauptordner mit kurzen, allgemein verständlichen deutschen Namen (Umlaute erlaubt).
- Keine Ordner für Jahreszahlen und keine Ordner für einzelne Dokumente. Ein Unterordner lohnt sich erst ab etwa drei passenden Dokumenten; sonst gehört das Dokument direkt in den Hauptordner.
- Jeder Ordner bekommt ein Namensschema für Dateinamen ("scheme") und einen Beispiel-Dateinamen ohne Endung ("example").
  Grundsatz: Der Ordner sagt, was für ein Dokument es ist; der Dateiname sagt, welches. Meist steht das Datum vorn ("JJJJ-MM Dokumentart", Beispiel "2026-11 Beitragsrechnung"); bei Verträgen, Urkunden und Zeugnissen steht der Name vorn ("Mietvertrag Wohnung 2021-04").
- Gib immer die vollständige Struktur aus, auch Ordner, die schon vorgegeben waren."""

TAXONOMY_SCHEMA = {
    "type": "object",
    "properties": {
        "folders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "scheme": {"type": "string"},
                    "example": {"type": "string"},
                },
                "required": ["path", "scheme", "example"],
            },
        }
    },
    "required": ["folders"],
}


SPLIT_SYSTEM = """Du prüfst, ob in einer gescannten Datei mehrere verschiedene Dokumente stecken (zum Beispiel eine Arztrechnung, danach ein Rezept, danach ein Kontoauszug).
Du bekommst den Anfang jeder Seite. Gib in "starts" die Seitennummern an, auf denen ein NEUES Dokument beginnt. Seite 1 ist immer dabei.
Sei zurückhaltend: Fortsetzungsseiten desselben Briefs, Anlagen, Rückseiten und Seiten mit "Seite 2 von 3" gehören zum vorherigen Dokument. Im Zweifel ist es EIN Dokument, also nur [1]."""

SPLIT_SCHEMA = {
    "type": "object",
    "properties": {"starts": {"type": "array", "items": {"type": "integer"}}},
    "required": ["starts"],
}
