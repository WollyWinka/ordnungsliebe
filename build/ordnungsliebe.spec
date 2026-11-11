# PyInstaller-Bauplan für Ordnungsliebe (Ordner-Variante, startet schneller als eine Einzeldatei)
# Aufruf aus dem Projektordner:  pyinstaller --noconfirm build/ordnungsliebe.spec

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = SPECPATH + "/.."

datas = [(ROOT + "/ui", "ui")]
binaries = []
hiddenimports = collect_submodules("app")

for pkg in ("webview", "pymupdf", "extract_msg", "docx", "openpyxl", "send2trash"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += ["clr", "clr_loader", "pythonnet"]

a = Analysis(
    [ROOT + "/run.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "numpy.tests", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ordnungsliebe",
    icon=ROOT + "/build/icon.ico",
    console=False,
    upx=False,
    version=ROOT + "/build/version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Ordnungsliebe")
