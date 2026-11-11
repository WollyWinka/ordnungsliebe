"""Verfügbare KI-Modelle (Qwen 2.5 Instruct, GGUF-Format für llama.cpp)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import paths

HF = "https://huggingface.co/bartowski"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str          # wie es dem Nutzer angezeigt wird
    description: str
    filename: str
    url: str
    size_gb: float      # ungefähre Downloadgröße
    min_vram_gb: float  # ab dieser Grafikspeichergröße läuft es komplett auf der Grafikkarte
    min_ram_gb: float   # ohne passende Grafikkarte nötiger Arbeitsspeicher

    @property
    def path(self) -> Path:
        return paths.models_dir() / self.filename

    @property
    def installed(self) -> bool:
        return self.path.exists()


MODELS: dict[str, ModelSpec] = {
    "gruendlich": ModelSpec(
        "gruendlich", "Gründlich", "Die treffsichersten Vorschläge. Braucht eine starke Grafikkarte.",
        "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        f"{HF}/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        9.0, 11.5, 24.0),
    "ausgewogen": ModelSpec(
        "ausgewogen", "Ausgewogen", "Gute Vorschläge, läuft auf den meisten Computern.",
        "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        f"{HF}/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        4.7, 6.0, 12.0),
    "schnell": ModelSpec(
        "schnell", "Schnell", "Für ältere oder kleine Computer. Vorschläge sind einfacher.",
        "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        f"{HF}/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        1.9, 3.0, 6.0),
}

ORDER = ["gruendlich", "ausgewogen", "schnell"]


def get(model_id: str) -> ModelSpec | None:
    return MODELS.get(model_id)
