# Ordnungsliebe

Sortiert eingescannte und vorhandene Dokumente mit einer **KI, die nur auf dem eigenen Computer läuft**,
in eine übersichtliche Ordnerstruktur. Die KI schlägt vor, du entscheidest.

## Installation (für alle)

1. **[Ordnungsliebe-Setup.exe herunterladen](https://github.com/WollyWinka/ordnungsliebe/releases/latest/download/Ordnungsliebe-Setup.exe)**
2. Die Datei doppelt anklicken.
   Zeigt Windows „Der Computer wurde durch Windows geschützt“, auf **Weitere Informationen → Trotzdem ausführen** klicken.
   (Das erscheint bei Programmen ohne kostenpflichtige Signatur.)
3. Ordnungsliebe startet und führt durch die Einrichtung. Beim ersten Start wird die KI einmalig
   heruntergeladen (2–9 GB, je nach Computer). Danach läuft alles ohne Internet.

Es werden keine Administratorrechte benötigt. Deinstallieren über *Einstellungen → Apps*.

## Was es kann

- Neue Scans im Scan-Ordner erkennen, lesen (auch Fotos und gescannte PDFs) und einen Ordner,
  einen verständlichen Dateinamen und eine Kurzbeschreibung vorschlagen.
- Sichere Vorschläge gesammelt abhaken, unsichere einzeln prüfen; „Passt nicht“ liefert einen neuen Vorschlag.
- Lernt aus deinen Entscheidungen.
- Macht gescannte PDFs durchsuchbar, wandelt Fotos in PDFs um.
- Erkennt doppelte Dokumente und mehrere zusammengescannte Dokumente in einer Datei.
- Ordnet die bestehende Ablage einmalig neu – mit vollständiger Sicherung und Rückgängig-Funktion.
- Verlauf mit „Rückgängig“ für jedes Dokument.
- PDF, Bilder, Word, Excel, E-Mails (.eml/.msg).

## Technik

| Teil | Lösung |
|---|---|
| Oberfläche | HTML/CSS/JS in einem Windows-Fenster (pywebview + Edge WebView2) |
| KI | llama.cpp (`llama-server`, Vulkan) mit Qwen 2.5 Instruct (14B / 7B / 3B, je nach Hardware), Antworten per JSON-Schema erzwungen |
| Texterkennung | Tesseract-Engine in PyMuPDF, deutsche Sprachdaten |
| Office-Vorschau | mitgeliefertes LibreOffice (eigenes Profil) |
| Setup | PyInstaller + Inno Setup, gebaut über GitHub Actions |

Daten liegen unter `%APPDATA%\Ordnungsliebe` (Einstellungen, Gedächtnis, Verlauf) und
`%LOCALAPPDATA%\Ordnungsliebe` (KI-Modell, Zwischenspeicher, Sicherungen, Protokolle).

## Entwicklung

```bash
pip install -r requirements.txt pytest pillow
python -m pytest tests                       # Tests mit Test-KI
ORDNUNGSLIEBE_FAKE_AI=1 python tests/devserver.py   # Oberfläche im Browser: http://127.0.0.1:8765
python run.py                                # Programmfenster
```

Umgebungsvariablen: `ORDNUNGSLIEBE_FAKE_AI=1` (Test-KI ohne Modell), `ORDNUNGSLIEBE_FAKE_HW=16,32`
(Grafikspeicher, RAM in GB), `ORDNUNGSLIEBE_TOOLS` (Ordner mit llama, tessdata, libreoffice),
`ORDNUNGSLIEBE_DEBUG=1` (Entwicklerwerkzeuge im Fenster).

Jeder Push auf `main` baut automatisch eine neue `Ordnungsliebe-Setup.exe` und veröffentlicht sie als Release.

Schrift: Figtree (SIL Open Font License, siehe `ui/fonts/OFL.txt`).
