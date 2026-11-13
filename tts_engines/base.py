from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple


class SynthesisCancelled(Exception):
    """Raised by an engine when synthesis was stopped by a cancel request."""


# A voice is (voice_id, label). voice_id is what the engine understands;
# label is what the UI shows.
Voice = Tuple[str, str]

# Where engines may keep downloaded voice data
DATA_DIR = Path.home() / ".textReader"


@dataclass
class TTSEngine:
    name: str
    output_ext: str

    def check_dependencies(self) -> List[str]:
        return []

    def list_voices(self) -> List[Voice]:
        """Voices this engine offers, best default first. May be slow (runs off the UI thread).

        Return an empty list if the engine has no voice choice.
        """
        return []

    # --- Optional: engines the app can install for the user -------------------
    install_note: str = ""  # shown when asking the user whether to install

    def can_install(self) -> bool:
        """True if install() can set up this engine's missing dependencies."""
        return False

    def install(self, log: Callable[[str], None], cancel_event: threading.Event) -> None:
        """Install missing dependencies, reporting progress lines through `log`.

        Raise SynthesisCancelled if `cancel_event` is set, or another exception on failure.
        """
        raise NotImplementedError()

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
        voice: Optional[str] = None,
    ) -> None:
        """Write speech for `text` to `output_path`.

        `voice` is a voice_id from list_voices(), or None for the engine default.
        Engines should check `cancel_event` where they can and raise
        SynthesisCancelled when it is set. Engines that cannot be interrupted
        may ignore it; the caller discards their output.
        """
        raise NotImplementedError()


def run_cancellable(
    cmd: Sequence[str],
    cancel_event: Optional[threading.Event] = None,
    input_text: Optional[str] = None,
    timeout: float = 60.0,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    """Run an external command, killing it if `cancel_event` is set
    (or `cancel_check()` returns True).

    Raises SynthesisCancelled on cancel and subprocess.TimeoutExpired on timeout.
    """
    proc = subprocess.Popen(
        list(cmd),
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if input_text is not None:
        # Feed stdin from a thread so a large input can't block cancellation.
        def feed():
            try:
                proc.stdin.write(input_text)
                proc.stdin.close()
            except Exception:
                pass
        threading.Thread(target=feed, daemon=True).start()

    waited = 0.0
    step = 0.05
    while True:
        try:
            proc.wait(timeout=step)
            return
        except subprocess.TimeoutExpired:
            waited += step
        if (cancel_event is not None and cancel_event.is_set()) or (cancel_check is not None and cancel_check()):
            proc.kill()
            proc.wait()
            raise SynthesisCancelled()
        if waited >= timeout:
            proc.kill()
            proc.wait()
            raise subprocess.TimeoutExpired(cmd, timeout)
