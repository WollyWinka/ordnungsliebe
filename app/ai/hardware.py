"""Hardware-Erkennung: Grafikspeicher, Arbeitsspeicher, freier Platz – und passende Modellwahl."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import asdict, dataclass

from .. import paths
from . import models

log = logging.getLogger(__name__)


@dataclass
class Hardware:
    gpu_name: str
    vram_gb: float
    ram_gb: float
    free_disk_gb: float
    cpu_threads: int

    def to_dict(self) -> dict:
        return asdict(self)


def _windows_gpus() -> list[tuple[str, float]]:
    """Liest Grafikkarten und deren Speicher aus der Registry (zuverlässiger als WMI über 4 GB)."""
    import winreg  # type: ignore

    result = []
    base = r"SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return result
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        if not sub.isdigit():
            continue
        try:
            key = winreg.OpenKey(root, sub)
        except OSError:
            continue
        name, mem = "", 0
        try:
            name = str(winreg.QueryValueEx(key, "DriverDesc")[0])
        except OSError:
            pass
        for value_name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
            try:
                raw = winreg.QueryValueEx(key, value_name)[0]
                if isinstance(raw, bytes):
                    raw = int.from_bytes(raw, "little")
                mem = int(raw)
                if mem:
                    break
            except (OSError, ValueError, TypeError):
                continue
        if name:
            result.append((name, mem / (1024 ** 3)))
    return result


def _windows_ram_gb() -> float:
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
    return stat.ullTotalPhys / (1024 ** 3)


def detect() -> Hardware:
    fake = os.environ.get("ORDNUNGSLIEBE_FAKE_HW")  # z. B. "16,32" für Tests
    free = shutil.disk_usage(paths.models_dir()).free / (1024 ** 3)
    threads = os.cpu_count() or 4
    if fake:
        vram, ram = (float(x) for x in fake.split(","))
        return Hardware("Test-Grafikkarte", vram, ram, free, threads)
    gpu_name, vram, ram = "", 0.0, 8.0
    if paths.IS_WINDOWS:
        try:
            gpus = _windows_gpus()
            # Integrierte Grafik mit geteiltem Speicher ignorieren, wenn eine echte Karte da ist.
            gpus.sort(key=lambda g: g[1], reverse=True)
            if gpus:
                gpu_name, vram = gpus[0]
        except Exception:
            log.exception("Grafikkarte konnte nicht ermittelt werden")
        try:
            ram = _windows_ram_gb()
        except Exception:
            log.exception("Arbeitsspeicher konnte nicht ermittelt werden")
    else:
        try:
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        ram = int(line.split()[1]) / (1024 ** 2)
                        break
        except OSError:
            pass
    return Hardware(gpu_name, round(vram, 1), round(ram, 1), round(free, 1), threads)


def recommend(hw: Hardware) -> tuple[str, bool]:
    """Wählt das passende Modell. Gibt (modell_id, auf_grafikkarte) zurück."""
    for model_id in models.ORDER:
        spec = models.MODELS[model_id]
        if hw.vram_gb >= spec.min_vram_gb:
            return model_id, True
    for model_id in models.ORDER:
        spec = models.MODELS[model_id]
        if hw.ram_gb >= spec.min_ram_gb:
            return model_id, False
    return "schnell", False


def use_gpu_for(model_id: str, hw: Hardware) -> bool:
    spec = models.get(model_id)
    return bool(spec and hw.vram_gb >= spec.min_vram_gb)
