from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence


class SynthesisCancelled(Exception):
    """Raised by an engine when synthesis was stopped by a cancel request."""


@dataclass
class TTSEngine:
    name: str
    output_ext: str

    def check_dependencies(self) -> List[str]:
        return []

    def synthesize(
        self,
        text: str,
        output_path: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        """Write speech for `text` to `output_path`.

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
