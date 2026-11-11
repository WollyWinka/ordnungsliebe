"""Ereignisse vom Hintergrund an die Oberfläche schicken (thread-sicher)."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)


class EventBus:
    """Sendet Ereignisse an das Programmfenster: window.onBackendEvent(name, daten)."""

    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._listeners: list[Callable[[str, Any], None]] = []

    def attach_window(self, window) -> None:
        self._window = window

    def subscribe(self, fn: Callable[[str, Any], None]) -> None:
        self._listeners.append(fn)

    def emit(self, name: str, payload: Any = None) -> None:
        for fn in list(self._listeners):
            try:
                fn(name, payload)
            except Exception:  # pragma: no cover - nur Protokoll
                log.exception("Listener-Fehler bei %s", name)
        window = self._window
        if window is None:
            return
        script = "window.onBackendEvent && window.onBackendEvent(%s, %s)" % (
            json.dumps(name), json.dumps(payload, ensure_ascii=False, default=str))
        with self._lock:
            try:
                window.evaluate_js(script)
            except Exception:  # Fenster geschlossen o. ä.
                log.debug("Ereignis %s konnte nicht gesendet werden", name, exc_info=True)


bus = EventBus()
