"""Einstellungen des Programms (liegen unter %APPDATA%\\Ordnungsliebe\\einstellungen.json)."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import jsonfile, paths

# Ab welcher Sicherheit ein Vorschlag in der Sammelliste landet.
BATCH_THRESHOLDS = {"wenig": 0.9, "mittel": 0.8, "viel": 0.65}


@dataclass
class Settings:
    setup_done: bool = False
    inbox_dir: str = ""
    library_dir: str = ""
    model_id: str = ""
    font_size: str = "gross"      # normal | gross | sehr
    theme: str = "auto"           # auto | hell | dunkel
    batch_level: str = "mittel"   # wenig | mittel | viel
    keep_cloud_local: bool = True
    auto_update: bool = True
    first_run_choice: str = ""    # "reorg" | "direct" – nur zur Anzeige
    extra: dict = field(default_factory=dict)

    @property
    def batch_threshold(self) -> float:
        return BATCH_THRESHOLDS.get(self.batch_level, 0.8)


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "einstellungen.json")
        self._lock = threading.Lock()
        raw = jsonfile.load(self.path, {})
        known = {f.name for f in fields(Settings)}
        self.settings = Settings(**{k: v for k, v in raw.items() if k in known})

    def get(self) -> Settings:
        return self.settings

    def update(self, **changes) -> Settings:
        with self._lock:
            known = {f.name for f in fields(Settings)}
            for key, value in changes.items():
                if key in known:
                    setattr(self.settings, key, value)
            jsonfile.save(self.path, asdict(self.settings))
            return self.settings

    def as_dict(self) -> dict:
        data = asdict(self.settings)
        data["batch_threshold"] = self.settings.batch_threshold
        return data
