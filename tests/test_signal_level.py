import array
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent.signal_level import rms16


def _pcm(values):
    return array.array("h", values).tobytes()


def test_rms_of_silence_is_zero():
    assert rms16(b"") == 0
    assert rms16(_pcm([0] * 4000)) == 0


def test_rms_of_constant_and_sine():
    assert rms16(_pcm([1000] * 100)) == 1000
    sine = [int(8000 * math.sin(2 * math.pi * i / 40)) for i in range(4000)]
    assert abs(rms16(_pcm(sine)) - 8000 / math.sqrt(2)) < 60


def test_rms_ignores_trailing_odd_byte():
    assert rms16(_pcm([500, 500]) + b"\x01") == 500
