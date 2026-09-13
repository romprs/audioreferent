"""Уровень сигнала PCM16 — для определения тишины после речи (см.
assistant._accept). Без numpy/audioop (последний удалён в Python 3.13)."""

from __future__ import annotations

import array
import math


def rms16(chunk: bytes) -> int:
    """Среднеквадратичный уровень моно PCM16 (0..32767). Пустой чанк — 0."""
    if len(chunk) < 2:
        return 0
    samples = array.array("h")
    samples.frombytes(chunk[: len(chunk) - len(chunk) % 2])
    total = 0
    for value in samples:
        total += value * value
    return int(math.sqrt(total / len(samples)))
