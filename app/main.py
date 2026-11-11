"""Startpunkt: öffnet das Programmfenster."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys


def _setup_logging() -> None:
    from . import paths
    log_dir = paths.local_dir() / "protokolle"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_dir / "ordnungsliebe.log", maxBytes=2_000_000,
                                                   backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not getattr(sys, "frozen", False):
        root.addHandler(logging.StreamHandler())


def _single_instance() -> bool:
    """Nur ein Fenster gleichzeitig (Windows). Gibt False zurück, wenn schon eins läuft."""
    if not sys.platform.startswith("win"):
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "Ordnungsliebe-EinzigeInstanz")  # type: ignore[attr-defined]
    already = ctypes.windll.kernel32.GetLastError() == 183  # type: ignore[attr-defined]
    if already:
        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None, "Ordnungsliebe ist bereits geöffnet.", "Ordnungsliebe", 0x40)
    return not already


def main() -> None:
    _setup_logging()
    if not _single_instance():
        return
    import webview

    from . import APP_NAME, paths
    from .api import Api, make_bridge

    api = Api()
    s = api.settings_store.get()
    dark = s.theme == "dunkel"
    window = webview.create_window(
        APP_NAME, url=str(paths.ui_dir() / "index.html"), js_api=make_bridge(api),
        width=1280, height=880, min_size=(960, 680),
        background_color="#17161D" if dark else "#F6F5FA", text_select=False)
    api.set_window(window)
    window.events.loaded += api.start_background
    window.events.closed += api.shutdown
    gui = "edgechromium" if sys.platform.startswith("win") else None
    webview.start(gui=gui, debug=bool(os.environ.get("ORDNUNGSLIEBE_DEBUG")), private_mode=False,
                  storage_path=str(paths.local_dir() / "webview"))


if __name__ == "__main__":
    main()
