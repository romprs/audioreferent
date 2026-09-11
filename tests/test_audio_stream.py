import queue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

sounddevice = pytest.importorskip("sounddevice", reason="audio.py импортирует sounddevice")

from audioreferent.audio import ChunkStream  # noqa: E402


def test_drain_drops_everything_queued_during_playback():
    q: queue.Queue[bytes] = queue.Queue()
    for _ in range(5):
        q.put(b"\x00\x01")
    stream = ChunkStream(q)
    assert stream.drain() == 5
    assert stream.drain() == 0
    q.put(b"\x02\x03")
    assert next(iter(stream)) == b"\x02\x03"
