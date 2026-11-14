"""MpvPlayer: speed changes while playing, positions stay in file time."""
import math
import struct
import time
import wave

import pytest

mpv = pytest.importorskip("mpv")
from textreader.player import MpvPlayer  # noqa: E402


@pytest.fixture
def tone(tmp_path):
    path = tmp_path / "tone.wav"
    rate = 22050
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(rate * 10)))
    return str(path)


@pytest.fixture
def player():
    try:
        p = MpvPlayer(ao="null")
    except Exception as e:
        pytest.skip(f"libmpv not available: {e}")
    yield p
    p.close()


def test_play_pause_resume_stop(player, tone):
    assert player.play(tone, 1.0)
    assert player.busy() and player.playing()
    player.pause()
    assert player.busy() and not player.playing()
    held = player.position()
    time.sleep(0.3)
    assert abs(player.position() - held) < 0.05
    player.resume()
    assert player.playing()
    player.stop()
    assert not player.busy() and player.position() is None


def test_speed_changes_while_playing(player, tone):
    assert player.play(tone, 1.0)
    time.sleep(0.3)
    player.set_speed(2.0)
    time.sleep(0.5)  # mpv takes a moment to switch speed
    before, start = player.position(), time.monotonic()
    time.sleep(1.0)
    rate = (player.position() - before) / (time.monotonic() - start)
    assert 1.8 < rate < 2.2  # two seconds of file per real second
