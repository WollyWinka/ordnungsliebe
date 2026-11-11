"""Die lokale KI: startet llama-server (llama.cpp) und stellt Anfragen mit JSON-Schema.

Das Schema wird von llama.cpp in eine Grammatik übersetzt; die Antwort ist daher immer
gültiges JSON in der verlangten Form.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

import requests

from .. import paths
from . import hardware, models

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
CONTEXT_SIZE = 8192


class LLMError(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMError("Die KI hat keine gültige Antwort geliefert.")


class LlamaServer:
    """Verwaltet den Hintergrundprozess llama-server."""

    def __init__(self, on_status=None):
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.model_id = ""
        self.gpu = False
        self.on_status = on_status or (lambda status, detail="": None)
        self._lock = threading.Lock()        # Start/Stopp
        self._req_lock = threading.Lock()    # eine Anfrage zur Zeit
        self._pidfile = paths.local_dir() / "ki.pid"

    # --- Lebenszyklus -------------------------------------------------------------
    def _kill_stale(self) -> None:
        try:
            pid = int(self._pidfile.read_text().strip())
        except (OSError, ValueError):
            return
        try:
            if paths.IS_WINDOWS:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                               creationflags=CREATE_NO_WINDOW)
            else:
                os.kill(pid, 15)
        except Exception:
            pass
        self._pidfile.unlink(missing_ok=True)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure(self, model_id: str) -> None:
        with self._lock:
            if self.running() and self.model_id == model_id:
                return
            self._stop_locked()
            spec = models.get(model_id)
            if spec is None or not spec.installed:
                raise LLMError("Das KI-Modell ist noch nicht heruntergeladen.")
            exe = paths.llama_server_path()
            if exe is None:
                raise LLMError("Die KI-Laufzeit fehlt. Bitte Ordnungsliebe neu installieren.")
            self._kill_stale()
            hw = hardware.detect()
            want_gpu = hardware.use_gpu_for(model_id, hw)
            self.on_status("starting", spec.label)
            for gpu in ([True, False] if want_gpu else [False]):
                if self._start(exe, spec.path, gpu, hw.cpu_threads):
                    self.model_id, self.gpu = model_id, gpu
                    self.on_status("ready", spec.label)
                    return
            self.on_status("error", "")
            raise LLMError("Die KI konnte nicht gestartet werden.")

    def _start(self, exe: Path, model_path: Path, gpu: bool, threads: int) -> bool:
        self.port = _free_port()
        log_dir = paths.local_dir() / "protokolle"
        log_dir.mkdir(parents=True, exist_ok=True)
        cmd = [str(exe), "-m", str(model_path), "--host", "127.0.0.1", "--port", str(self.port),
               "-c", str(CONTEXT_SIZE), "-np", "1", "-ngl", "99" if gpu else "0",
               "-t", str(max(2, threads // 2))]
        log.info("Starte KI: %s", " ".join(cmd))
        logfile = open(log_dir / "ki.log", "ab")
        kwargs = {"creationflags": CREATE_NO_WINDOW} if paths.IS_WINDOWS else {}
        self.proc = subprocess.Popen(cmd, stdout=logfile, stderr=subprocess.STDOUT,
                                     cwd=str(exe.parent), **kwargs)
        try:
            self._pidfile.write_text(str(self.proc.pid))
        except OSError:
            pass
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                log.warning("KI-Prozess beendet (Code %s, GPU=%s)", self.proc.returncode, gpu)
                self.proc = None
                return False
            try:
                r = requests.get(f"http://127.0.0.1:{self.port}/health", timeout=2)
                if r.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(0.7)
        self._stop_locked()
        return False

    def _stop_locked(self) -> None:
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=10)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None
        self._pidfile.unlink(missing_ok=True)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    # --- Anfragen -----------------------------------------------------------------
    def chat_json(self, system: str, user: str, schema: dict, name: str,
                  max_tokens: int = 600, temperature: float = 0.1) -> dict:
        if not self.running():
            raise LLMError("Die KI läuft nicht.")
        body = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
        }
        with self._req_lock:
            try:
                r = requests.post(f"http://127.0.0.1:{self.port}/v1/chat/completions",
                                  json=body, timeout=600)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
            except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
                raise LLMError(f"Anfrage an die KI fehlgeschlagen: {exc}") from exc
        return _extract_json(content)


class AI:
    """Schnittstelle, die der Rest des Programms benutzt."""

    def __init__(self, settings_store, on_status=None):
        self.settings_store = settings_store
        self.server = LlamaServer(on_status)

    def chat_json(self, system: str, user: str, schema: dict, name: str, max_tokens: int = 600) -> dict:
        model_id = self.settings_store.get().model_id
        self.server.ensure(model_id)
        return self.server.chat_json(system, user, schema, name, max_tokens)

    def warmup(self) -> None:
        self.server.ensure(self.settings_store.get().model_id)

    def shutdown(self) -> None:
        self.server.stop()


def make_ai(settings_store, on_status=None):
    if os.environ.get("ORDNUNGSLIEBE_FAKE_AI"):
        from .fake import FakeAI
        return FakeAI(on_status)
    return AI(settings_store, on_status)
