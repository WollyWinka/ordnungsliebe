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
- Ähnliche, vom Nutzer bereits bestätigte Fälle haben Vorrang vor deinem eigenen Gefühl.
- "reason": ein bis zwei kurze deutsche Sätze, WARUM dieser Ordner passt (z. B. "Entgeltnachweis des Arbeitgebers; der Nutzer legt solche Nachweise in Arbeit/Gehalt/Entgeltnachweise ab."). Schreibe die Begründung, bevor du den Ordner wählst.
- KORREKTUREN des Nutzers bei ähnlichen Fällen sind verbindlich: Ist das Dokument von derselben Art wie ein korrigierter Fall, wähle den Ordner aus der Korrektur – auch wenn ein übergeordneter Ordner ebenfalls passen würde. Ein spezieller Unterordner, den der Nutzer gewählt hat, schlägt immer den allgemeinen Ordner darüber.
- UNTERORDNER: Hinter manchen Ordnern steht, wie viele Dokumente dort schon liegen. Ist der passende Ordner schon recht voll (ab etwa 20) und gehört das Dokument zu einer klar abgrenzbaren, wiederkehrenden Art (z. B. Entgeltnachweise, Kontoauszüge, Arztrechnungen, ein bestimmter Vertrag oder Anbieter), dann schlage einen neuen Unterordner DARUNTER vor ("__NEU__", z. B. new_folder "Arbeit/Gehalt/Entgeltnachweise"). Gibt es schon einen passenden Unterordner, nimm ihn statt des Oberordners. Keine Unterordner für Einzelstücke.
- Hinweise des Nutzers haben Vorrang vor allem anderen. Ein Hinweis zu genau diesem Dokument gilt für Ordner UND Dateinamen; nennt er einen Ordner, der nicht in der Liste steht, wähle "__NEU__" und trage ihn in "new_folder" ein.
- "deadlines": echte Fristen und Termine, bis zu denen der Nutzer etwas tun muss oder die er nicht verpassen darf (Zahlung, Kündigung, Widerspruch, Rückmeldung, Abgabe, Arzt- oder Behördentermin). Je Eintrag "date" als JJJJ-MM-TT und "what" als kurze Beschreibung (z. B. "Rechnung Stadtwerke bezahlen"). Relative Fristen ("innerhalb von 14 Tagen", "bis Monatsende") vom Datum des Dokuments aus ausrechnen. NICHT das Briefdatum, keine Zeiträume von Abrechnungen, keine bereits bezahlten Beträge. Höchstens 3; gibt es keine, dann [].
- "steuer": true, wenn das Dokument für die Einkommensteuererklärung nützlich sein kann (z. B. Lohnsteuerbescheinigung, Steuerbescheid, Spendenquittung, Handwerker- oder Nebenkostenabrechnung, Arzt- und Zahnarztrechnungen, Versicherungsbeiträge, Kinderbetreuung, Fortbildung, Arbeitsmittel, Riester/Rürup), sonst false."""

PERSON_RULE = """- "person": Für wen im Haushalt ist das Dokument (Empfänger oder betroffene Person)? Genau einer dieser Namen: {names}. Leer (""), wenn es den ganzen Haushalt betrifft oder unklar ist."""


def classify_schema(folders: list[str], persons: list[str] | None = None) -> dict:
    choices = list(folders) + [NEW_FOLDER]
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "doc_date": {"type": "string"},
            "reason": {"type": "string"},
            "folder": {"type": "string", "enum": choices},
            "new_folder": {"type": "string"},
            "alternative_folder": {"type": "string", "enum": list(folders) + [""]},
            "filename": {"type": "string"},
            "confidence": {"type": "string", "enum": CONFIDENCE_VALUES},
            "deadlines": {
                "type": "array", "maxItems": 3,
                "items": {"type": "object",
                          "properties": {"date": {"type": "string"}, "what": {"type": "string"}},
                          "required": ["date", "what"]},
            },
            "steuer": {"type": "boolean"},
        },
        "required": ["summary", "doc_date", "reason", "folder", "new_folder", "alternative_folder",
                     "filename", "confidence", "deadlines", "steuer"],
    }
    if persons:
        schema["properties"]["person"] = {"type": "string", "enum": list(persons) + [""]}
        schema["required"].append("person")
    return schema


TAXONOMY_SYSTEM = """Du entwirfst eine übersichtliche, gut gegliederte Ordnerstruktur für die privaten Dokumente eines Haushalts in Deutschland.

Ziel: Man soll jedes Dokument mit zwei, drei Klicks finden. Kein Ordner soll zur unübersichtlichen Sammelkiste werden.

Regeln:
- 6 bis 14 Hauptordner mit kurzen, allgemein verständlichen deutschen Namen (Umlaute erlaubt), z. B. "Versicherungen", "Finanzen", "Wohnen", "Arbeit", "Gesundheit", "Fahrzeuge", "Familie", "Behörden", "Verträge", "Einkäufe & Garantien".
- GLIEDERE GROSSZÜGIG IN UNTERORDNER: Jeder Hauptordner, in dem voraussichtlich mehr als etwa 8 Dokumente landen, bekommt Unterordner – nach Dokumentart, Vertrag/Anbieter, Objekt oder Person. Beispiele: "Versicherungen/Kfz", "Versicherungen/Hausrat", "Finanzen/Bank/Kontoauszüge", "Finanzen/Steuern/2025", "Arbeit/Gehalt/Entgeltnachweise", "Arbeit/Verträge & Zeugnisse", "Wohnen/Nebenkosten", "Gesundheit/Arztrechnungen".
- Höchstens drei Ebenen (getrennt mit "/"). Die dritte Ebene nur, wenn es viele gleichartige Dokumente gibt (z. B. Kontoauszüge, Entgeltnachweise, Steuerjahre).
- Ein Unterordner lohnt sich ab etwa drei passenden Dokumenten. Keine Ordner für Einzelstücke und keine reinen Jahresordner auf oberster Ebene.
- Jeder Ordner bekommt ein Namensschema für Dateinamen ("scheme") und einen Beispiel-Dateinamen ohne Endung ("example").
  Grundsatz: Der Ordner sagt, was für ein Dokument es ist; der Dateiname sagt, welches. Meist steht das Datum vorn ("JJJJ-MM Dokumentart", Beispiel "2026-11 Beitragsrechnung"); bei Verträgen, Urkunden und Zeugnissen steht der Name vorn ("Mietvertrag Wohnung 2021-04").
- Gib immer die vollständige Struktur aus, auch Ordner, die schon vorgegeben waren, und auch die Hauptordner selbst."""

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
