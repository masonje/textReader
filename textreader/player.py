"""Audio playback for the read-aloud audio.

Two backends share one interface:

* MpvPlayer (preferred): plays the file as it is and changes speed while it
  plays, keeping the voice's pitch (mpv's scaletempo filter). Nothing has to be
  processed before speech starts. Needs libmpv and the python-mpv package.
* PygamePlayer (fallback when libmpv is missing): makes a sped-up copy with
  ffmpeg before playing, so speed can only change between reads.

All positions and durations are in the original file's time, so word timing
works the same whatever the speed. Real (wall-clock) time is that divided by
the speed.
"""

import os
import threading
import time
from typing import Callable, Optional


class MpvPlayer:
    live_speed = True
    name = "mpv"

    def __init__(self, **options) -> None:
        import mpv

        log_file = os.environ.get("TR_MPV_LOG")  # set to a file path for a full mpv log (debugging)
        def log(level, component, message):
            if log_file:
                with open(log_file, "a") as f:
                    f.write(f"{time.monotonic():.3f} {level} {component}: {message}")
            elif level in ("error", "fatal"):
                print(f"⚠️ mpv: {component}: {message.strip()}")
        options.setdefault("log_handler", log)
        options.setdefault("loglevel", "v" if log_file else "error")
        self._mpv = mpv.MPV(video=False, ytdl=False, idle=True, input_default_bindings=False,
                            input_vo_keyboard=False, audio_display=False, keep_open=False, **options)
        self._mpv["audio-pitch-correction"] = True
        self._lock = threading.Lock()
        self._loaded = False  # a file was started and has not been stopped

    def play(self, path: str, speed: float, cancel_check: Callable[[], bool] = lambda: False) -> bool:
        with self._lock:
            self._mpv.speed = speed
            self._mpv.pause = False
            self._mpv.play(path)
            self._loaded = True
        # Wait (briefly) until mpv has really started the file, so busy() is accurate.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not cancel_check():
            if self._mpv.time_pos is not None:
                return True
            time.sleep(0.01)
        return self._mpv.time_pos is not None

    def pause(self) -> None:
        self._mpv.pause = True

    def resume(self) -> None:
        self._mpv.pause = False

    def stop(self) -> None:
        with self._lock:
            self._loaded = False
            self._mpv.pause = False
            self._mpv.stop()

    def busy(self) -> bool:
        """True while a file is playing or paused."""
        return self._loaded and not self._mpv.idle_active

    def playing(self) -> bool:
        return self.busy() and not self._mpv.pause

    def position(self) -> Optional[float]:
        return self._mpv.time_pos if self.busy() else None

    def set_speed(self, speed: float) -> None:
        self._mpv.speed = speed

    def close(self) -> None:
        try:
            self._mpv.terminate()
        except Exception:
            pass


class PygamePlayer:
    live_speed = False
    name = "pygame"

    def __init__(self, speed_file_dir: str) -> None:
        import pygame

        self._music = pygame.mixer.music
        self._dir = speed_file_dir
        self._speed = 1.0
        self._paused = False
        self._loaded = False
        self._start = None
        self._pause_start = None
        self._pause_accum = 0.0

    def play(self, path: str, speed: float, cancel_check: Callable[[], bool] = lambda: False) -> bool:
        from .engines.base import SynthesisCancelled, run_cancellable

        to_play = path
        if abs(speed - 1.0) > 1e-6:
            # WAV, so the sped-up copy is never compressed again
            to_play = os.path.join(self._dir, "clipboard_speech_speed.wav")
            try:
                run_cancellable(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                                 "-filter:a", f"atempo={speed}", to_play], cancel_check=cancel_check)
            except SynthesisCancelled:
                return False
            except Exception as e:
                print(f"⚠️ Speed change failed, playing at normal speed: {e}")
                to_play, speed = path, 1.0
        if cancel_check():
            return False
        self._music.load(to_play)
        self._speed = speed
        self._paused = False
        self._pause_start = None
        self._pause_accum = 0.0
        self._start = time.monotonic()
        self._music.play()
        self._loaded = True
        return True

    def pause(self) -> None:
        if self.busy() and not self._paused:
            self._music.pause()
            self._paused = True
            self._pause_start = time.monotonic()

    def resume(self) -> None:
        if self._paused:
            self._music.unpause()
            self._paused = False
            if self._pause_start is not None:
                self._pause_accum += time.monotonic() - self._pause_start
                self._pause_start = None

    def stop(self) -> None:
        self._music.stop()
        self._loaded = False
        self._paused = False
        self._start = None

    def busy(self) -> bool:
        # pygame reports get_busy() == False while paused, so track pause ourselves
        return self._loaded and (self._paused or self._music.get_busy())

    def playing(self) -> bool:
        return self.busy() and not self._paused

    def position(self) -> Optional[float]:
        if not self.busy() or self._start is None:
            return None
        now = self._pause_start if self._paused and self._pause_start is not None else time.monotonic()
        return max(0.0, (now - self._start - self._pause_accum) * self._speed)

    def set_speed(self, speed: float) -> None:
        pass  # takes effect on the next read

    def close(self) -> None:
        pass


def create_player(speed_file_dir: str):
    """Return an MpvPlayer, or a PygamePlayer if libmpv isn't available."""
    try:
        return MpvPlayer()
    except Exception as e:
        print(f"⚠️ mpv isn't available ({e}); speed changes will take effect on the next read")
        return PygamePlayer(speed_file_dir)
