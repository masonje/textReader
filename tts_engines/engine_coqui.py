"""Coqui TTS: a neural voice that runs offline, using PyTorch.

Coqui and PyTorch are far too large to bundle with the app, so the app can
install them into a private Python environment in ~/.textReader/engines/coqui
(CPU-only PyTorch, about 1 GB on disk). Speech is then made by a small worker
process running in that environment, which keeps the model loaded between reads.
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, List, Optional

from .base import DATA_DIR, SynthesisCancelled, TTSEngine

ENV_DIR = DATA_DIR / "engines" / "coqui"
READY_MARKER = ENV_DIR / ".installed"
WORKER_SCRIPT = DATA_DIR / "engines" / "coqui_worker.py"
WORKER_LOG = DATA_DIR / "engines" / "coqui_worker.log"
MODEL = "tts_models/en/ljspeech/tacotron2-DDC"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"

# Runs inside the Coqui environment. Protocol: one JSON object per line.
# stdout carries only protocol messages; everything the libraries print goes to stderr.
WORKER_SOURCE = r'''
import json, os, sys
proto = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1)
sys.stdout = sys.stderr
def send(**msg):
    proto.write(json.dumps(msg) + "\n")
try:
    from TTS.api import TTS
    tts = TTS(model_name=sys.argv[1], progress_bar=False)
except Exception as e:
    send(error=f"Could not load Coqui: {e}")
    sys.exit(1)
send(ready=True)
for line in sys.stdin:
    try:
        job = json.loads(line)
        tts.tts_to_file(text=job["text"], file_path=job["out"])
        send(ok=True)
    except Exception as e:
        send(error=str(e))
'''


def _env_python() -> str:
    if os.name == "nt":
        return str(ENV_DIR / "Scripts" / "python.exe")
    return str(ENV_DIR / "bin" / "python")


def _system_python() -> Optional[str]:
    """A Python that can create the environment (not the frozen app itself)."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in ("python3", "python"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _worker_python() -> Optional[str]:
    """Python to run the worker with, or None if Coqui isn't available."""
    if READY_MARKER.exists() and os.path.exists(_env_python()):
        return _env_python()
    if not getattr(sys, "frozen", False):
        import importlib.util
        if importlib.util.find_spec("TTS") is not None:
            return sys.executable  # coqui-tts installed in the app's own environment
    return None


class _Worker:
    """A long-running Coqui process, so the model only loads once."""

    def __init__(self, python: str) -> None:
        WORKER_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
        WORKER_SCRIPT.write_text(WORKER_SOURCE)
        self._log = open(WORKER_LOG, "a")
        self.proc = subprocess.Popen(
            [python, str(WORKER_SCRIPT), MODEL],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log, text=True, bufsize=1,
        )
        self.lines: "queue.Queue[Optional[str]]" = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.ready = False

    def _read(self) -> None:
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)  # process ended

    def wait(self, cancel_event: Optional[threading.Event], timeout: float) -> dict:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cancel_event is not None and cancel_event.is_set():
                raise SynthesisCancelled()
            try:
                line = self.lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError(f"Coqui stopped unexpectedly (see {WORKER_LOG})")
            try:
                return json.loads(line)
            except ValueError:
                continue
        raise TimeoutError("Coqui took too long to respond")

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass
        try:
            self._log.close()
        except Exception:
            pass


_worker: Optional[_Worker] = None
_worker_lock = threading.Lock()


def _stop_worker_at_exit() -> None:
    if _worker is not None:
        _worker.stop()


atexit.register(_stop_worker_at_exit)


def _run_logged(cmd: List[str], log: Callable[[str], None], cancel_event: threading.Event) -> None:
    """Run a command, passing its output to `log`, killing it on cancel."""
    log("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines: "queue.Queue[Optional[str]]" = queue.Queue()

    def read():
        for line in proc.stdout:
            lines.put(line.rstrip())
        lines.put(None)
    threading.Thread(target=read, daemon=True).start()
    while True:
        if cancel_event.is_set():
            proc.kill()
            proc.wait()
            raise SynthesisCancelled()
        try:
            line = lines.get(timeout=0.1)
        except queue.Empty:
            continue
        if line is None:
            break
        if line:
            log(line)
    if proc.wait() != 0:
        raise RuntimeError(f"Command failed (exit {proc.returncode}): {' '.join(cmd[:4])} …")


class CoquiEngine(TTSEngine):
    def __init__(self) -> None:
        super().__init__(name="Coqui TTS", output_ext="wav")
        self.install_note = (
            "Coqui TTS needs PyTorch, which is too big to ship with the app. Installing it downloads "
            "about 1 GB (CPU-only PyTorch, Coqui, and its voice model) into ~/.textReader/engines/coqui. "
            "This can take several minutes."
        )

    def check_dependencies(self) -> List[str]:
        return [] if _worker_python() else ["coqui-tts"]

    def can_install(self) -> bool:
        return _worker_python() is None and _system_python() is not None

    def install(self, log: Callable[[str], None], cancel_event: threading.Event) -> None:
        python = _system_python()
        if python is None:
            raise RuntimeError("Python 3 is needed to install Coqui TTS, but it wasn't found.")
        try:
            if not os.path.exists(_env_python()):
                log("Creating a private Python environment…")
                ENV_DIR.parent.mkdir(parents=True, exist_ok=True)
                _run_logged([python, "-m", "venv", str(ENV_DIR)], log, cancel_event)
            log("Installing PyTorch (CPU) and Coqui TTS. This is the slow part…")
            _run_logged(
                [_env_python(), "-m", "pip", "install", "--progress-bar", "off",
                 "--extra-index-url", TORCH_CPU_INDEX, "coqui-tts[cpu,codec]",
                 "six"],  # coqui-tts 0.28 imports six without declaring it
                log, cancel_event,
            )
            log("Downloading the voice model and testing it…")
            READY_MARKER.touch()
            test_path = str(ENV_DIR / "install-test.wav")
            self.synthesize("Coqui is ready.", test_path, cancel_event)
            os.remove(test_path)
            log("Coqui TTS is installed.")
        except BaseException:
            READY_MARKER.unlink(missing_ok=True)
            raise

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
        voice: Optional[str] = None,
    ) -> None:
        global _worker
        python = _worker_python()
        if python is None:
            raise RuntimeError("Coqui TTS isn't installed")
        with _worker_lock:
            try:
                if _worker is None or not _worker.alive():
                    _worker = _Worker(python)
                if not _worker.ready:
                    # First start loads PyTorch and the model (and downloads the model once)
                    msg = _worker.wait(cancel_event, timeout=600)
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    _worker.ready = True
                _worker.proc.stdin.write(json.dumps({"text": text, "out": output_path}) + "\n")
                _worker.proc.stdin.flush()
                msg = _worker.wait(cancel_event, timeout=600)
                if "error" in msg:
                    raise RuntimeError(msg["error"])
            except BaseException:
                # On cancel or failure, stop the worker; the next read starts a fresh one
                if _worker is not None:
                    _worker.stop()
                    _worker = None
                raise
